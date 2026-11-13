import json
import re
import tempfile
from copy import deepcopy
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, Client
from django.utils import translation
from .models import Persona, ReviewRun, Source
from .agents.memory.context import assigned_claim
from .agents.planning import next_phase, next_stage
from .agents.progress import feedback_letters, pipeline_text, plain_text
from .agents.schemas import report
from .agents.runner import MAX_TOOL_ROUNDS
from .agents.tools.documents import align_citations, check_quote
from .agents.tools.personas import match_persona
from .agents.tools.sources import new_research, read_source, search_sources
from .agents.validation import validate_moderator, validate_report
from .integrations import transport

TEXT = '임차인은 월세를 지원받는다. 임대인은 임대차 신고에 협조한다. 지자체는 지원 대상을 따로 정할 수 있다.'
CITATION = {'page': 1, 'quote': '임차인은 월세를 지원받는다.'}


def role(name, basis='explicit'):
    return {'name': name, 'basis': basis, 'doc_role': '문서상 위치', 'gains': '얻는 것', 'burdens': '지는 부담',
            'goal': '지키려는 것', 'red_line': '양보하기 어려운 것',
            'impact': '정책의 의미', 'why_distinct': '이해가 다름', 'citation': CITATION,
            'persona_hint': {'age_min': 19, 'age_max': 39, 'keywords': ['월세']}}


ANALYSIS = {'document_type': '지원 공고', 'policy_field': '청년 주거', 'purpose': '월세 지원', 'applies_to': '청년',
            'summary': '월세 지원 정책', 'status': 'ok', 'selection_note': '수혜자·부담자·집행자',
            'other_stakeholders': [], 'roles': [role('임차인'), role('임대인', 'implied'), role('지자체')]}
TWO_ROLES = dict(ANALYSIS, roles=ANALYSIS['roles'][:2])
ISSUE = {'issue': '지원 대상 기준', 'signal': '재량 집중', 'priority': '높음', 'reason': '결정권 집중', 'contested': '입장 차이 내용', 'question': '기준은 무엇인가?', 'low_relevance': []}


def positions(count):
    return [{'role': index, 'stance': f'역할 {index}의 한 줄 입장'} for index in range(count)]


ITEMS = {
    'issues': {**ISSUE, 'positions': positions(3)},
    'debate': {'issue': '지원 대상 기준', 'claim_summary': '상대 주장 요약', 'response': '반박', 'stake': '지원 대상에서 빠지지 않는 것', 'reason': '상대 주장 요약과 사정', 'request': '기준 공개 요청', 'condition': '기준 공개 시 수용', 'sources': []},
    'final': {'issue': '지원 대상 기준', 'signal': '재량 집중', 'priority': '높음', 'reason': '결정 전 확인 필요', 'impact': '지원에서 빠질 수 있다', 'phrase': '월세를 지원받는다', 'my_reading': '기준이 없으면 탈락할 수 있다고 읽는다', 'other_role': '지자체', 'other_reading': '지자체는 재량으로 대상을 정할 수 있다고 읽는다', 'check': '공고문 확인', 'question': '기준은 언제 공개되나?', 'uncertainty': '세부 기준이 문서에 없다', 'sources': []},
}


# A developer's .env may turn the dummy mode on; tests run on the real code paths unless they turn it on themselves.
DUMMY_OFF = patch.dict('os.environ', {'POLICYLENS_DUMMY': '0'})


def setUpModule():
    DUMMY_OFF.start()


def tearDownModule():
    DUMMY_OFF.stop()


def response(data):
    return {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(data)}]}]}


def data_of(payload):
    # A call with tools sends the conversation; its first message is the step input.
    body = payload['input']
    return json.loads(body[0]['content'] if isinstance(body, list) else body)


def stage_of(payload):
    top = payload['text']['format']['schema']['properties']
    if 'speaker' in top:
        return 'moderator'
    fields = top['items']['items']['properties']
    if 'quote' in fields:
        return 'format'
    return 'issues' if 'excluded' in top else 'debate' if 'response' in fields else 'final'


def moderation(data, statements=3):
    # A fake moderator: the roles take turns after whoever spoke last, and it closes the issue after a set number of statements.
    said = sum(1 for step in data['history'] if step['stage'] == 'debate' and step['moderator']['next'][0]['issue_id'] == data['current_issue_id'])
    if said >= statements:
        return {'summary': '새 의견이 없어요', 'close': True, 'speaker': -1, 'question': '같은 주장이 되풀이되어 닫아요.', 'shifted_by': 'none'}
    low = next(issue for issue in data['issues'] if issue['id'] == data['current_issue_id']).get('low_relevance', [])
    count = len(data['roles'])
    speaker = next(role % count for role in range(data['last_speaker'] + 1, data['last_speaker'] + count) if role % count not in low)
    return {'summary': '진행 중', 'close': False, 'speaker': speaker, 'question': '앞 발언에 답해 주세요.', 'shifted_by': 'none'}


def result_for(payload, issues=1):
    stage = stage_of(payload)
    data = data_of(payload)
    if stage == 'moderator':
        return moderation(data)
    if stage == 'format':
        return {'items': [formatted(data['baseline_answer'])]}
    item = {**ITEMS[stage], 'citation': CITATION}
    if stage == 'final':
        item['other_role'] = payload['text']['format']['schema']['properties']['items']['items']['properties']['other_role']['enum'][-1]
    if stage != 'issues':
        item['target_ids'] = data['allowed_target_ids']
        return {'summary': '검토 완료', 'items': [item]}
    items = [{**item, 'issue': item['issue'] if n == 1 else f'다른 쟁점 {n}', 'positions': positions(len(data['roles']))} for n in range(1, issues + 1)]
    return {'summary': '검토 완료', 'items': items, 'excluded': ['시행일은 자명해 제외했다.']}


def formatted(answer):
    # A single-prompt answer moved into the caution fields; empty fields are what the answer did not say.
    return {'issue': answer, 'reason': '답변의 이유', 'page': 0, 'quote': '임차인은 월세를 지원받는다.', 'impact': '답변의 영향',
            'phrase': '', 'my_reading': '', 'other_role': '', 'other_reading': '', 'check': '', 'question': '', 'uncertainty': ''}


def two_issues(payload, key):
    return response(result_for(payload, issues=2))


def report_response(payload, key):
    return response(result_for(payload))


def persona(uuid, age, occupation, **extra):
    fields = {'persona': f'김하늘 씨는 {occupation}로 일하는 사람입니다.', 'professional_persona': '하늘 씨는 손이 빠릅니다.', 'family_persona': '김하늘 씨가 혼자 삽니다.', 'sex': '여자',
              'marital_status': '미혼', 'family_type': '1인 가구', 'housing_type': '다세대주택', 'education_level': '4년제 대학교',
              'district': '서울-관악구', 'province': '서울', **extra}
    return Persona.objects.create(uuid=uuid, age=age, occupation=occupation, **fields)


class PlanTests(SimpleTestCase):
    def test_server_fixes_the_phases_and_the_moderator_fills_the_debate(self):
        steps = lambda *stages: [{'stage': stage} for stage in stages]
        self.assertEqual(next_stage([]), 'issues')
        self.assertEqual(next_stage(steps('issues')), 'debate')
        self.assertEqual(next_stage(steps('issues', 'debate', 'debate')), 'debate')
        self.assertEqual(next_stage(steps('issues', 'debate', 'close')), 'final')
        self.assertIsNone(next_stage(steps('issues', 'debate', 'close', 'final')))
        self.assertEqual([next_phase(steps(*s)) for s in ((), ('issues',), ('issues', 'debate', 'close'), ('final',))],
                         ['discussion', 'review', 'proposal', None])

    def test_claims_are_counted_per_issue(self):
        step = lambda role, issue, n: {'stage': 'debate', 'role': role, 'result': {'items': [{'id': f's{n}-i1'}]}, 'moderator': {'next': [{'issue_id': issue}]}}
        context = [step(0, 'a', 2), step(1, 'b', 3), step(2, 'a', 4), step(0, 'a', 5)]
        self.assertEqual(assigned_claim(context, 'c', 2), {'issue_id': 'c', 'claim_id': None, 'reply_id': None})
        self.assertEqual(assigned_claim(context, 'b', 0), {'issue_id': 'b', 'claim_id': 's3-i1', 'reply_id': None})
        self.assertEqual(assigned_claim(context, 'a', 1), {'issue_id': 'a', 'claim_id': 's2-i1', 'reply_id': 's5-i1'})
        self.assertEqual(assigned_claim(context, 'a', 0), {'issue_id': 'a', 'claim_id': 's4-i1', 'reply_id': None})

    def test_moderator_decisions_are_checked(self):
        decision = lambda **extra: {'summary': 's', 'close': False, 'speaker': 1, 'question': 'q', 'shifted_by': 'none', **extra}
        validate_moderator([TEXT], decision(), 3, 0)
        for bad in (decision(speaker=0), decision(speaker=3), decision(speaker=-1),
                    decision(summary='토론을 承担한다'), decision(question='서준수 씨처럼 답해 주세요.')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_moderator([TEXT], bad, 3, 0)

    def test_low_relevance_roles_speak_only_over_a_statement_that_shifts_a_cost_onto_them(self):
        decision = lambda **extra: {'summary': 's', 'close': False, 'speaker': 1, 'question': 'q', 'shifted_by': 'none', **extra}
        statements = {'s2-i1': 0, 's4-i1': 2}
        for bad in (decision(speaker=2), decision(speaker=2, shifted_by='s4-i1')):  # Not without a statement, nor over its own.
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, '관련이 낮은'):
                validate_moderator([TEXT], bad, 3, 0, low=[2], statements=statements)
        validate_moderator([TEXT], decision(speaker=2, shifted_by='s2-i1'), 3, 0, low=[2], statements=statements)
        closing = decision(close=True, speaker=-1)
        with self.assertRaisesRegex(ValueError, '아직 발언하지 않은 관련 역할\\(1\\)'):
            validate_moderator([TEXT], closing, 3, 0, low=[2], spoken=[0])
        validate_moderator([TEXT], closing, 3, 0, low=[2], spoken=[0, 1])  # Role 2 never has to speak.

    def test_issue_relevance_marks_are_checked(self):
        from .agents.validation import validate_relevance
        validate_relevance([{'low_relevance': []}, {'low_relevance': [2]}], 3)
        for low in ([1, 2], [3], [0, 0], [-1]):
            with self.subTest(low=low), self.assertRaises(ValueError):
                validate_relevance([{'low_relevance': low}], 3)

    def test_pending_issue_follows_the_order_until_closed(self):
        from .agents.memory.context import pending_issue
        from .agents.planning import MAX_STATEMENTS
        issues = {'stage': 'issues', 'result': {'items': [{'id': 'a'}, {'id': 'b'}]}}
        said = lambda issue, n: [{'stage': 'debate', 'role': 0, 'result': {'items': []}, 'moderator': {'next': [{'issue_id': issue}]}}] * n
        closed = lambda issue: [{'stage': 'issue_close', 'role': None, 'result': {'items': []}, 'moderator': {'closed': issue}}]
        self.assertEqual(pending_issue([issues]), ({'id': 'a'}, 0))
        self.assertEqual(pending_issue([issues] + said('a', 5)), ({'id': 'a'}, 5))  # No fixed count: it goes on until the moderator closes it.
        self.assertEqual(pending_issue([issues] + said('a', 2) + closed('a')), ({'id': 'b'}, 0))
        self.assertEqual(pending_issue([issues] + said('a', MAX_STATEMENTS)), ({'id': 'b'}, 0))  # The safety limit.
        self.assertEqual(pending_issue([issues] + said('a', 2) + closed('a') + said('b', 2) + closed('b')), (None, 0))


class ProviderTests(SimpleTestCase):
    def test_vibehub_model_key_is_used_when_openai_settings_are_absent(self):
        hub = {'MINIAPP_LLM_API_KEY': 'hub-key', 'MINIAPP_LLM_BASE_URL': 'https://hub.example/v1/', 'POLICYLENS_API_MODE': 'chat_completions'}
        with patch('server.integrations.transport.dotenv_values', return_value={}), patch.dict('os.environ', hub, clear=True):
            self.assertEqual(transport.configuration()[0], 'hub-key')
            self.assertEqual(transport.provider(), ('https://hub.example/v1', 'chat_completions'))
            with patch.dict('os.environ', {'OPENAI_API_KEY': 'own-key'}):
                self.assertEqual(transport.configuration()[0], 'own-key')


class ReviewFlowTests(TestCase):
    def setUp(self):
        self.config = patch('server.integrations.transport.configuration', return_value=('test-key', 'test-model'))
        self.config.start()
        self.addCleanup(self.config.stop)

    def create_run(self, analysis=ANALYSIS):
        with patch('server.integrations.transport.call', return_value=response(analysis)):
            result = self.client.post('/', {'text': TEXT})
        self.assertEqual(result.status_code, 302)
        return ReviewRun.objects.latest('id')

    def run_steps(self, run, count, reply=report_response, **extra):
        results = []
        with patch('server.integrations.transport.call', side_effect=reply) as model:
            for _ in range(count):
                run.refresh_from_db()
                results.append(self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(len(run.steps))}, **extra))
        return model, results

    def run_to_end(self, run, reply=report_response):
        with patch('server.integrations.transport.call', side_effect=reply) as model:
            for _ in range(30):
                run.refresh_from_db()
                if run.steps and run.steps[-1]['stage'] == 'final':
                    break
                self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(len(run.steps))})
        return model

    def completed_run(self, analysis=ANALYSIS, selected='0'):
        run = self.create_run(analysis)
        self.client.post(f'/reviews/{run.pk}/select/', {'role': selected})
        self.run_to_end(run)
        run.refresh_from_db()
        return run

    def test_three_roles_full_flow_and_duplicate_cursor(self):
        run = self.create_run()
        self.assertContains(self.client.get(f'/reviews/{run.pk}/'), '임차인')
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        with patch('server.integrations.transport.call', side_effect=report_response) as model:
            for _ in range(7):
                run.refresh_from_db()
                self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(len(run.steps))})
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '6'})
            # Issues 1, opening 1, two moderated turns 2 each, the moderator closing the issue 1, close without a call, final 1.
            self.assertEqual(model.call_count, 8)
        run.refresh_from_db()
        self.assertEqual([(step['stage'], step['role']) for step in run.steps],
                         [('issues', None), ('debate', 0), ('debate', 1), ('debate', 2), ('issue_close', None), ('close', None), ('final', None)])
        self.assertContains(self.client.get(f'/reviews/{run.pk}/?page=proposal'), '주의 조항 정리')

    def test_two_roles_complete_the_same_way(self):
        run = self.completed_run(TWO_ROLES, '1')
        self.assertEqual([step['role'] for step in run.steps if step['stage'] == 'debate'], [1, 0, 1])
        review = self.client.get(f'/reviews/{run.pk}/?page=review')
        self.assertContains(review, 'id="s2-i1"')
        self.assertContains(review, 'id="s3-i1"')
        self.assertContains(review, 'AI · 2개의 관점')
        self.assertEqual(len(feedback_letters(run)), 2)
        self.assertEqual(self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '7'}).status_code, 302)

    def test_each_issue_gets_its_statements_and_opens_with_the_users_role(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '1'})
        model = self.run_to_end(run, two_issues)
        run.refresh_from_db()
        debate = [step for step in run.steps if step['stage'] == 'debate']
        self.assertEqual([step['role'] for step in debate], [1, 2, 0, 1, 2, 0])
        self.assertEqual([step['moderator']['next'][0]['issue_id'] for step in debate], ['s1-i1'] * 3 + ['s1-i2'] * 3)
        self.assertEqual(run.steps[-2]['result']['summary'], '모든 쟁점의 토론을 마쳤어요.')
        calls = [(stage_of(call.args[0]), data_of(call.args[0])) for call in model.call_args_list]
        openers = [data for stage, data in calls if stage == 'debate' and data['assigned_claims'][0]['claim_id'] is None]
        self.assertEqual([(data['acting_role']['name'], data['moderator_question']) for data in openers], [('임대인', ''), ('임대인', '')])
        self.assertEqual([data['current_issue_id'] for stage, data in calls if stage == 'moderator'], ['s1-i1'] * 3 + ['s1-i2'] * 3)
        self.assertEqual(model.call_count, 1 + 2 * 6 + 1)  # Issues, two issues of 1 opener, 2 moderated turns and 1 closing call, final.

    def test_the_moderator_decides_when_an_issue_ends(self):
        run = self.create_run(TWO_ROLES)
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        reply = lambda payload, key: response(moderation(data_of(payload), statements=2)) if stage_of(payload) == 'moderator' else two_issues(payload, key)
        self.run_to_end(run, reply)
        run.refresh_from_db()
        self.assertEqual([(step['stage'], step['role']) for step in run.steps if step['stage'] in ('debate', 'issue_close')],
                         [('debate', 0), ('debate', 1), ('issue_close', None)] * 2)
        closing = run.steps[3]
        self.assertEqual((closing['moderator']['closed'], closing['result']['summary']), ('s1-i1', '새 의견이 없어요'))
        self.assertContains(self.client.get(f'/reviews/{run.pk}/?page=review'), '새 의견이 없어요')

    def test_an_issue_the_moderator_never_closes_stops_at_the_safety_limit(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        reply = lambda payload, key: response(moderation(data_of(payload), statements=99)) if stage_of(payload) == 'moderator' else report_response(payload, key)
        with patch('server.agents.memory.context.MAX_STATEMENTS', 4):
            self.run_to_end(run, reply)
        run.refresh_from_db()
        self.assertEqual([step['stage'] for step in run.steps], ['issues'] + ['debate'] * 4 + ['close', 'final'])

    def test_the_first_role_the_issue_touches_opens_it_when_the_users_role_does_not(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        def reply(payload, key):
            result = result_for(payload)
            if stage_of(payload) == 'issues':
                result['items'][0]['low_relevance'] = [0]
            return response(result)
        self.run_steps(run, 1, reply)
        self.assertContains(self.client.get(f'/reviews/{run.pk}/?page=discussion'), '<span class="low-tag">관련 낮음</span>')
        self.run_to_end(run, reply)
        run.refresh_from_db()
        self.assertEqual([step['role'] for step in run.steps if step['stage'] == 'debate'], [1, 2, 1])

    def test_bad_moderator_choice_is_repaired_once(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        self.run_steps(run, 2)
        same = {'summary': 's', 'close': False, 'speaker': 0, 'question': 'q', 'shifted_by': 'none'}
        good = dict(same, speaker=2)
        debate = {'summary': 's', 'items': [{**ITEMS['debate'], 'citation': CITATION, 'target_ids': ['s1-i1', 's2-i1']}]}
        with patch('server.integrations.transport.call', side_effect=[response(same), response(good), response(debate)]) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '2'})
        run.refresh_from_db()
        self.assertEqual((run.error, len(run.steps), run.steps[2]['role']), ('', 3, 2))
        self.assertIn('직전 발언자', data_of(model.call_args_list[1].args[0])['validation_error'])
        self.assertNotIn('selected_role', data_of(model.call_args_list[0].args[0]))

    def test_moderator_calls_a_low_relevance_role_over_the_statement_that_shifts_a_cost(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        def reply(payload, key):
            result = result_for(payload)
            if stage_of(payload) == 'issues':
                result['items'][0]['low_relevance'] = [2]
                return response(result)
            if stage_of(payload) == 'moderator':
                data = data_of(payload)
                enum = payload['text']['format']['schema']['properties']['shifted_by']['enum']
                self.assertEqual(enum, ['none', 's2-i1'])  # Only this issue's statements can be named.
                return response({'summary': 's', 'close': False, 'speaker': 2, 'question': '임차인 발언대로면 지자체 업무가 늘어요. 답해 주세요.', 'shifted_by': 's2-i1'})
            return response(result)
        self.run_steps(run, 3, reply)
        run.refresh_from_db()
        called = run.steps[2]
        self.assertEqual((called['role'], called['moderator']['next'][0]['shifted_by']), (2, 's2-i1'))
        self.assertIn('지자체 업무가 늘어요', self.client.get(f'/reviews/{run.pk}/?page=review').content.decode())

    def test_user_moves_on_after_three_statements_without_a_model_call(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        headers = {'HTTP_ACCEPT': 'application/json'}
        reply = lambda payload, key: response(moderation(data_of(payload), statements=99)) if stage_of(payload) == 'moderator' else two_issues(payload, key)
        self.run_steps(run, 3, reply)
        run.refresh_from_db()
        early_bar = self.client.get(f'/reviews/{run.pk}/status/', **headers).json()['skip_html']
        self.assertIn('disabled', early_bar)
        self.assertIn('발언 1개 뒤에', early_bar)
        early = self.client.post(f'/reviews/{run.pk}/skip/', {'cursor': '3'}, **headers)
        self.assertEqual(early.status_code, 400)
        self.assertIn('3개 이상', early.json()['message'])
        self.run_steps(run, 1, reply)
        state = self.client.get(f'/reviews/{run.pk}/status/', **headers).json()
        self.assertIn('다음 쟁점으로', state['skip_html'])
        self.assertNotIn('disabled', state['skip_html'])
        self.assertEqual(self.client.post(f'/reviews/{run.pk}/skip/', {'cursor': '3'}, **headers).status_code, 409)  # Stale cursor.
        with patch('server.integrations.transport.call') as model:
            skipped = self.client.post(f'/reviews/{run.pk}/skip/', {'cursor': '4'}, **headers)
            model.assert_not_called()
        self.assertEqual(skipped.status_code, 200)
        run.refresh_from_db()
        self.assertEqual((run.steps[-1]['stage'], run.steps[-1]['moderator']['closed'], run.steps[-1]['moderator']['by']), ('issue_close', 's1-i1', 'user'))
        self.assertIn('쟁점 02', skipped.json()['current_issue_html'])
        self.assertIn('사용자가 충분하다고 보고', skipped.json()['steps_html'])
        self.run_steps(run, 3, reply)
        run.refresh_from_db()
        self.assertEqual([step['moderator']['next'][0]['issue_id'] for step in run.steps[-3:]], ['s1-i2'] * 3)
        self.assertIn('토론 마치기', self.client.get(f'/reviews/{run.pk}/status/', **headers).json()['skip_html'])  # The last issue.
        self.client.post(f'/reviews/{run.pk}/skip/', {'cursor': '8'}, **headers)
        run.refresh_from_db()
        self.assertEqual(next_stage(run.steps), 'debate')
        self.run_steps(run, 1, reply)  # Nothing left: the debate closes, then the final step reads which issues the user cut short.
        self.assertEqual([step['moderator'].get('by') for step in run.steps if step['stage'] == 'issue_close'], ['user', 'user'])

    def test_moderator_notes_new_issues_without_debating_them(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        self.run_steps(run, 2)
        def call(arguments, number):
            return {'status': 'completed', 'output': [{'type': 'function_call', 'call_id': f'c{number}', 'name': 'note_issue', 'arguments': json.dumps(arguments)}]}
        note = {'issue': '새로 부딪힌 조항', 'reason': '임대인 협조 의무와 부딪혀요', 'page': 1, 'quote': '임대인은 임대차 신고에 협조한다.'}
        seen, payloads = [], []
        def reply(payload, key):
            payloads.append(payload)
            if stage_of(payload) != 'moderator':
                return report_response(payload, key)
            seen.append(payload)
            if len(seen) == 1:
                return call({**note, 'quote': '문서에 없는 인용입니다'}, 1)  # Rejected back to the model, nothing saved.
            if len(seen) == 2:
                return call(note, 2)
            return response(moderation(data_of(payload)))
        _, results = self.run_steps(run, 1, reply, HTTP_ACCEPT='application/json')
        outputs = [item['output'] for item in seen[2]['input'] if item.get('type') == 'function_call_output']
        self.assertIn('error', json.loads(outputs[0]))
        self.assertEqual(json.loads(outputs[1]), {'saved': True})
        self.assertEqual(list(run.notes.values_list('step', 'during', 'issue', 'page')), [(3, 's1-i1', '새로 부딪힌 조항', 1)])
        self.assertIn('새로 부딪힌 조항', results[0].json()['new_issues_html'])
        review = self.client.get(f'/reviews/{run.pk}/?page=review').content.decode()
        panel = review.split('id="new-issues-section"')[1]
        note_id = f'note-{run.notes.get().pk}'
        self.assertIn(f'<article class="issue-card" id="{note_id}">', panel)
        self.assertIn('쟁점 01 토론 중', panel)
        self.assertIn(f'href="#{note_id}"', review.split('id="new-issues-section"')[0])  # The moderator's bubble points to the note.
        self.run_to_end(run, reply)
        run.refresh_from_db()
        self.assertEqual({step['moderator']['next'][0]['issue_id'] for step in run.steps if step['stage'] == 'debate'}, {'s1-i1'})  # Never debated.
        self.assertEqual(data_of(seen[-1])['noted_issues'][0]['issue'], '새로 부딪힌 조항')
        final = data_of(next(payload for payload in reversed(payloads) if stage_of(payload) == 'final'))
        self.assertEqual(final['noted_issues'], [{'issue': '새로 부딪힌 조항', 'reason': '임대인 협조 의무와 부딪혀요', 'citation': {'page': 1, 'quote': '임대인은 임대차 신고에 협조한다.'}, 'added': False}])

    def test_user_adds_a_note_to_the_debate_after_the_original_issues(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        headers = {'HTTP_ACCEPT': 'application/json'}
        self.run_steps(run, 2)
        note = {'issue': '새로 부딪힌 조항', 'reason': '임대인 협조 의무와 부딪혀요', 'page': 1, 'quote': '임대인은 임대차 신고에 협조한다.'}
        payloads, moderated = [], []
        def reply(payload, key):
            payloads.append(payload)
            if stage_of(payload) == 'moderator' and not moderated:
                moderated.append(payload)  # The first moderator call notes one clause, then the debate goes on.
                return {'status': 'completed', 'output': [{'type': 'function_call', 'call_id': 'c1', 'name': 'note_issue', 'arguments': json.dumps(note)}]}
            return report_response(payload, key)
        self.run_steps(run, 1, reply)
        run.refresh_from_db()
        saved = run.notes.get()
        url = f'/reviews/{run.pk}/notes/{saved.pk}/debate/'
        self.assertIn(f'data-add-note="{url}"', self.client.get(f'/reviews/{run.pk}/status/', **headers).json()['new_issues_html'])
        self.assertEqual(self.client.post(url, {'cursor': '2'}, **headers).status_code, 409)  # Stale cursor.
        with patch('server.integrations.transport.call') as model:
            added = self.client.post(url, {'cursor': '3'}, **headers)
            model.assert_not_called()
        self.assertEqual(added.status_code, 200)
        self.assertIn('토론에 추가했어요', added.json()['new_issues_html'])
        self.assertIn('쟁점 02', added.json()['new_issues_html'])
        self.assertEqual(self.client.post(url, {'cursor': '3'}, **headers).status_code, 400)  # Already added.
        self.run_to_end(run, reply)
        run.refresh_from_db()
        issues = [step['moderator']['next'][0]['issue_id'] for step in run.steps if step['stage'] == 'debate']
        self.assertEqual(issues, ['s1-i1'] * 3 + [f'note-{saved.pk}'] * 3)  # Debated after the original issue, like any other.
        self.assertEqual([step['moderator']['closed'] for step in run.steps if step['stage'] == 'issue_close'], ['s1-i1', f'note-{saved.pk}'])
        final = data_of(next(payload for payload in reversed(payloads) if stage_of(payload) == 'final'))
        self.assertTrue(final['noted_issues'][0]['added'])
        self.assertEqual(final['history'][-1]['stage'], 'added_issues')
        review = self.client.get(f'/reviews/{run.pk}/?page=review').content.decode()
        self.assertIn('쟁점 02 · 새로 부딪힌 조항', review)  # The divider in the chat.
        self.assertNotIn('data-add-note', review)  # The debate is closed.
        self.assertEqual(self.client.post(url, {'cursor': str(len(run.steps))}, **headers).status_code, 400)

    def test_a_clause_already_noted_is_not_noted_again(self):
        from .agents.tools.notes import note_issue
        notes = []
        arguments = lambda quote: {'type': 'function_call', 'name': 'note_issue', 'arguments': json.dumps({'issue': '쟁점', 'reason': '이유', 'page': 1, 'quote': quote})}
        self.assertEqual(json.loads(note_issue([TEXT], notes, arguments('임대인은 임대차 신고에 협조한다.'))), {'saved': True})
        self.assertIn('이미', json.loads(note_issue([TEXT], notes, arguments('임대인은  임대차 신고에 협조한다.')))['error'])
        self.assertIn('error', json.loads(note_issue([TEXT], notes, {'name': 'note_issue', 'arguments': '{}'})))
        self.assertEqual(len(notes), 1)

    def test_role_count_limits_are_enforced(self):
        for roles in (ANALYSIS['roles'][:1], ANALYSIS['roles'] + [role('시민')]):
            with self.subTest(count=len(roles)), patch('server.integrations.transport.call', return_value=response(dict(ANALYSIS, roles=roles))) as model:
                page = self.client.post('/', {'text': TEXT}, follow=True)
                self.assertEqual(model.call_count, 2)
                self.assertContains(page, '2~3명')
                self.assertContains(page, '문서 분석 재시도')

    def test_persona_hint_age_range_is_checked(self):
        bad = dict(ANALYSIS, roles=[{**role('임차인'), 'persona_hint': {'age_min': 40, 'age_max': 30, 'keywords': ['월세']}}, role('임대인')])
        with patch('server.integrations.transport.call', return_value=response(bad)) as model:
            page = self.client.post('/', {'text': TEXT}, follow=True)
            self.assertEqual(model.call_count, 2)
        self.assertContains(page, '문서 분석 재시도')

    def test_insufficient_document_explains_without_repair(self):
        result = dict(ANALYSIS, status='insufficient', roles=[], selection_note='역할 구분이 드러나지 않습니다.')
        with patch('server.integrations.transport.call', return_value=response(result)) as model:
            page = self.client.post('/', {'text': TEXT}, follow=True)
            self.assertEqual(model.call_count, 1)
        self.assertContains(page, '역할 구분이 드러나지 않습니다.')
        run = ReviewRun.objects.latest('id')
        self.assertEqual(run.analysis, {})
        with patch('server.integrations.transport.call', return_value=response(ANALYSIS)) as model:
            self.client.post(f'/reviews/{run.pk}/analyze/')
            self.client.post(f'/reviews/{run.pk}/analyze/')
            self.assertEqual(model.call_count, 1)
        run.refresh_from_db()
        self.assertEqual(run.analysis, ANALYSIS)

    def test_failed_first_analysis_keeps_document_for_retry(self):
        with patch('server.integrations.transport.call', side_effect=TimeoutError('timeout')):
            page = self.client.post('/', {'text': TEXT}, follow=True)
        self.assertContains(page, '문서 분석 재시도')
        self.assertEqual(ReviewRun.objects.latest('id').pages, [TEXT])

    def test_implied_role_is_labelled(self):
        run = self.create_run()
        self.assertContains(self.client.get(f'/reviews/{run.pk}/'), '문서에 직접 언급되지 않은 역할이에요.', count=1)

    def test_roles_get_a_matching_persona_that_agents_speak_as(self):
        persona('young', 27, '편의점 판매원', housing_type='월세 다세대주택')
        persona('old', 71, '하역 작업자', housing_type='월세 아파트')
        run = self.create_run()
        self.assertEqual([p and p['uuid'] for p in run.personas], ['young', None, None])  # One person per role, never reused.
        stored = run.personas[0]
        self.assertEqual((stored['persona'], stored['professional_persona'], stored['family_persona']),
                         ('편의점 판매원로 일하는 사람입니다.', '손이 빠릅니다.', '혼자 삽니다.'))  # The name is deleted before anything stores or sends it.
        summary = self.client.get(f'/reviews/{run.pk}/')
        self.assertContains(summary, 'Nemotron-Personas-Korea(CC BY 4.0)')
        for detail in ('하늘', '27세', '관악구', '편의점 판매원'):
            self.assertNotContains(summary, detail)
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        model, _ = self.run_steps(run, 2)
        issues, opening = [data_of(call.args[0]) for call in model.call_args_list]
        self.assertEqual(issues['history'], [])
        self.assertEqual([r['persona'] and r['persona']['uuid'] for r in issues['roles']], ['young', None, None])
        self.assertEqual(opening['acting_role']['persona']['occupation'], '편의점 판매원')
        self.assertNotIn('하늘', json.dumps(model.call_args_list[1].args[0], ensure_ascii=False))
        run.refresh_from_db()
        run.personas[0]['persona'] = '김하늘 씨는 예전에 저장된 인물입니다.'
        run.save()
        model, _ = self.run_steps(run, 1)
        self.assertNotIn('하늘', json.dumps([call.args[0] for call in model.call_args_list], ensure_ascii=False))

    def test_a_persons_name_in_a_statement_goes_back_for_repair(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        self.run_steps(run, 1)
        named = {'summary': 's', 'items': [{**ITEMS['debate'], 'reason': '서준수 씨처럼 첫 경력을 준비하는 청년은 불리합니다.', 'citation': CITATION, 'target_ids': ['s1-i1']}]}
        plain = {'summary': 's', 'items': [{**named['items'][0], 'reason': '첫 경력을 준비하는 청년은 불리합니다.'}]}
        with patch('server.integrations.transport.call', side_effect=[response(named), response(plain)]) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '1'})
        run.refresh_from_db()
        self.assertIn('사람 이름', data_of(model.call_args_list[1].args[0])['validation_error'])
        self.assertEqual(run.steps[1]['result']['items'][0]['reason'], '첫 경력을 준비하는 청년은 불리합니다.')
        validate_report(['담당자 홍길동 씨에게 제출한다.'], {'summary': 's', 'items': [{**ISSUE, 'reason': '홍길동 씨에게 내야 합니다.', 'citation': {'page': 1, 'quote': '담당자 홍길동 씨에게 제출한다.'}}]}, 'issues', [])
        self.assertEqual(run.analysis, ANALYSIS)  # The persona is kept apart from the extracted roles.

    def test_persona_must_fit_age_and_a_keyword(self):
        persona('old', 71, '하역 작업자', housing_type='월세')
        persona('young', 25, '카페 직원', family_type='1인 가구', housing_type='월세')
        hint = lambda *words: {'age_min': 19, 'age_max': 39, 'keywords': list(words)}
        self.assertIsNone(match_persona(hint('하역')))
        self.assertEqual(match_persona(hint('월세'))['uuid'], 'young')
        self.assertIsNone(match_persona(hint('월세'), ['young']))
        self.assertIsNone(match_persona(hint(' ')))

    def test_load_personas_stores_a_sample(self):
        row = {'uuid': 'p1', 'persona': '요약', 'professional_persona': '직업', 'family_persona': '가족', 'sex': '남자', 'age': 30,
               'marital_status': '미혼', 'family_type': '1인 가구', 'housing_type': '아파트', 'education_level': '대학교',
               'occupation': '사무원', 'district': '서울-강남구', 'province': '서울', 'country': '대한민국', 'arts_persona': '쓰지 않는 칸'}
        class Body:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, *args): return json.dumps({'rows': [{'row_idx': 0, 'row': row}]}).encode()
        with patch('server.management.commands.load_personas.urlopen', return_value=Body()) as opened, \
                patch('server.management.commands.load_personas.time.sleep'):
            call_command('load_personas', '--count', '200', stdout=StringIO())
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(list(Persona.objects.values_list('uuid', 'age', 'occupation')), [('p1', 30, '사무원')])

    def test_role_agents_do_not_learn_user_choice(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '2'})
        model, _ = self.run_steps(run, 7)
        calls = [(stage_of(call.args[0]), data_of(call.args[0])) for call in model.call_args_list]
        for stage, data in calls:
            with self.subTest(stage=stage):
                self.assertNotIn('selected_role', data)
                self.assertEqual('user_role' in data, stage == 'final')
                self.assertEqual('acting_role' in data, stage == 'debate')
        debate = [data for stage, data in calls if stage == 'debate']
        self.assertEqual([data['acting_role']['name'] for data in debate], ['지자체', '임차인', '임대인'])
        self.assertEqual(calls[-1][1]['user_role']['name'], '지자체')
        self.assertEqual({step['stage'] for step in calls[-1][1]['history']}, {'issues', 'debate', 'issue_close'})

    def test_debate_turns_answer_the_statements_on_their_issue(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        model = self.run_to_end(run)
        debate = [data_of(call.args[0]) for call in model.call_args_list if stage_of(call.args[0]) == 'debate']
        self.assertEqual([data['assigned_claims'] for data in debate], [
            [{'issue_id': 's1-i1', 'claim_id': None, 'reply_id': None}],
            [{'issue_id': 's1-i1', 'claim_id': 's2-i1', 'reply_id': None}],
            [{'issue_id': 's1-i1', 'claim_id': 's2-i1', 'reply_id': 's3-i1'}]])
        self.assertEqual([data['moderator_question'] for data in debate], ['', '앞 발언에 답해 주세요.', '앞 발언에 답해 주세요.'])
        self.assertEqual([[h['speaker'] for h in data['history'] if h['stage'] == 'debate'] for data in debate],
                         [[], ['임차인'], ['임차인', '임대인']])
        self.assertEqual(debate[0]['acting_role']['red_line'], '양보하기 어려운 것')

    def test_one_item_per_turn_and_at_most_three_issues(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        item = lambda stage, **extra: {**ITEMS[stage], 'citation': CITATION, **extra}
        four = {'summary': 's', 'items': [item('issues')] * 4, 'excluded': ['x']}
        with patch('server.integrations.transport.call', return_value=response(four)) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
            self.assertEqual(model.call_count, 2)
        run.refresh_from_db()
        self.assertIn('최대 3개', run.error)
        self.assertEqual(len(run.steps), 0)
        self.run_steps(run, 1)
        two = {'summary': 's', 'items': [item('debate', target_ids=['s1-i1'])] * 2}
        with patch('server.integrations.transport.call', return_value=response(two)):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '1'})
        run.refresh_from_db()
        self.assertIn('하나만', run.error)
        self.assertEqual(len(run.steps), 1)

    def test_prompts_match_the_moderated_flow(self):
        prompts = settings.BASE_DIR / 'prompts'
        self.assertFalse((prompts / 'independent.md').exists())
        self.assertIn('최대 3개', (prompts / 'issues.md').read_text(encoding='utf-8'))
        self.assertIn('쟁점 하나', (prompts / 'debate.md').read_text(encoding='utf-8'))
        moderator = (prompts / 'moderator.md').read_text(encoding='utf-8')
        self.assertIn('note_issue', moderator)
        self.assertIn('정해진 발언 수는 없다', moderator)
        self.assertIn('low_relevance', (prompts / 'issues.md').read_text(encoding='utf-8'))
        self.assertIn('shifted_by', moderator)
        self.assertIn('moderator.by가 user', (prompts / 'final.md').read_text(encoding='utf-8'))
        self.assertIn('stake', (prompts / 'debate.md').read_text(encoding='utf-8'))
        self.assertIn('○○ 씨', (prompts / 'common.md').read_text(encoding='utf-8'))

    def test_debate_targets_exclude_own_statement_and_are_schema_enums(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        model, _ = self.run_steps(run, 6, two_issues)
        payload = model.call_args_list[-1].args[0]
        self.assertEqual(data_of(payload)['acting_role']['name'], '임차인')
        others = ['s1-i1', 's1-i2', 's3-i1', 's4-i1']
        self.assertEqual(data_of(payload)['allowed_target_ids'], others)
        schema = payload['text']['format']['schema']['properties']['items']['items']['properties']['target_ids']
        self.assertEqual(schema['items']['enum'], others)
        self.assertNotIn('target_ids', report('issues', [])['properties']['items']['items']['properties'])

    def test_validation_failure_is_repaired_once_with_feedback(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        result = lambda quote: {'summary': 's', 'items': [{**ITEMS['issues'], 'citation': {'page': 1, 'quote': quote}}], 'excluded': ['x']}
        wrong, right = result('문서에 없는 인용입니다'), result(CITATION['quote'])
        with patch('server.integrations.transport.call', side_effect=[response(wrong), response(right)]) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        run.refresh_from_db()
        self.assertEqual(len(run.steps), 1)
        self.assertEqual(run.error, '')
        repair = data_of(model.call_args_list[1].args[0])
        self.assertIn('일치하지 않습니다', repair['validation_error'])
        self.assertIn('문서에 없는 인용', json.loads(repair['rejected_output'])['items'][0]['citation']['quote'])
        with patch('server.integrations.transport.call', return_value=response(wrong)) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '1'})
            self.assertEqual(model.call_count, 2)
        run.refresh_from_db()
        self.assertEqual(len(run.steps), 1)
        self.assertTrue(run.error)

    def test_incomplete_response_is_not_repaired(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        with patch('server.integrations.transport.call', return_value={'status': 'incomplete'}) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
            self.assertEqual(model.call_count, 1)

    def test_issues_may_not_be_empty(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        with patch('server.integrations.transport.call', return_value=response({'summary': '없음', 'items': [], 'excluded': []})):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        run.refresh_from_db()
        self.assertEqual(len(run.steps), 0)
        self.assertIn('하나 이상', run.error)

    def test_opening_statement_is_labelled_apart_from_replies(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '1'})
        self.run_steps(run, 4)
        page = self.client.get(f'/reviews/{run.pk}/?page=review')
        self.assertContains(page, '<strong>상대 주장</strong>', count=2)
        self.assertContains(page, '<strong>쟁점</strong>', count=1)

    def test_server_links_the_assigned_issue_and_claims_the_model_left_out(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        self.run_steps(run, 1)
        def reply(target_ids):
            item = {**ITEMS['debate'], 'citation': CITATION, 'target_ids': target_ids}
            return lambda payload, key: report_response(payload, key) if stage_of(payload) == 'moderator' else response({'summary': 's', 'items': [item]})
        # The opener forgot its issue, the second speaker the claim, the third the earlier reply: no repair call, no stop.
        for target_ids, expected in (([], ['s1-i1']), (['s1-i1'], ['s1-i1', 's2-i1']), (['s2-i1'], ['s1-i1', 's2-i1', 's3-i1'])):
            model, _ = self.run_steps(run, 1, reply(target_ids))
            run.refresh_from_db()
            self.assertEqual(run.error, '')
            self.assertNotIn('repair', [call.get('purpose') for call in run.calls[-model.call_count:]])
            self.assertEqual(run.steps[-1]['result']['items'][0]['target_ids'], expected)

    def test_hanzi_slip_goes_back_for_repair(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        slip = {**ITEMS['issues'], 'citation': CITATION, 'reason': '비용을 누가承担할지 없다'}
        fixed = {**slip, 'reason': '비용을 누가 부담할지 없다'}
        with patch('server.integrations.transport.call', side_effect=[response({'summary': 's', 'items': [item], 'excluded': []}) for item in (slip, fixed)]) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        run.refresh_from_db()
        self.assertEqual(model.call_count, 2)
        self.assertEqual(run.steps[0]['result']['items'][0]['reason'], '비용을 누가 부담할지 없다')

    def test_hanzi_from_the_document_is_allowed(self):
        pages = ['임차인은 月貰를 지원받는다.']
        item = {**ITEMS['issues'], 'reason': '月貰 기준이 없다', 'citation': {'page': 1, 'quote': '임차인은 月貰를 지원받는다.'}}
        validate_report(pages, {'summary': 's', 'items': [item]}, 'issues', [])

    def test_issue_cards_show_one_line_per_role_instead_of_a_chat(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '1'})
        self.run_steps(run, 1)
        page = self.client.get(f'/reviews/{run.pk}/?page=discussion')
        self.assertNotContains(page, 'class="chat-room glass"')
        self.assertContains(page, '<article class="issue-card" id="s1-i1">')
        for index, name in enumerate(['임차인', '임대인', '지자체']):
            self.assertContains(page, f'<strong>{name}</strong>')
            self.assertContains(page, f'역할 {index}의 한 줄 입장')
        self.assertContains(page, '<strong>임대인</strong><span class="self-tag">내 입장</span>')

    def test_every_role_needs_exactly_one_position(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        for wrong in (positions(2), positions(3) + positions(1), [{'role': 3, 'stance': 's'}] + positions(2)):
            with self.subTest(wrong=wrong), patch('server.integrations.transport.call',
                                                  return_value=response({'summary': 's', 'items': [{**ITEMS['issues'], 'positions': wrong, 'citation': CITATION}], 'excluded': []})):
                self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
                run.refresh_from_db()
                self.assertEqual(run.steps, [])
                self.assertIn('한 줄씩', run.error)

    def test_debate_shows_the_current_issue_and_where_it_changes(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        headers = {'HTTP_ACCEPT': 'application/json'}
        self.run_steps(run, 1, two_issues)
        self.assertIn('쟁점 01 · 지원 대상 기준', self.client.get(f'/reviews/{run.pk}/status/', **headers).json()['current_issue_html'])
        _, results = self.run_steps(run, 3, two_issues, **headers)
        self.assertIn('쟁점 01 · 지원 대상 기준', results[-1].json()['current_issue_html'])  # Still open until the moderator closes it.
        _, results = self.run_steps(run, 1, two_issues, **headers)
        self.assertIn('지금 토론 중인 쟁점', results[-1].json()['current_issue_html'])
        self.assertIn('쟁점 02 · 다른 쟁점 2', results[-1].json()['current_issue_html'])  # Shown before its first statement arrives.
        self.run_steps(run, 1, two_issues)
        review = self.client.get(f'/reviews/{run.pk}/?page=review')
        self.assertContains(review, 'id="s2-divider"')
        self.assertContains(review, 'id="s6-divider"')
        for same_issue in (3, 4, 5):
            self.assertNotContains(review, f'id="s{same_issue}-divider"')
        self.assertContains(review, 'id="new-issues-section" hidden')
        self.run_to_end(run, two_issues)
        self.assertIn('토론을 마쳤어요.', self.client.get(f'/reviews/{run.pk}/status/', **headers).json()['current_issue_html'])

    def test_runs_from_before_the_note_tool_still_list_their_added_issues(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        self.run_steps(run, 3)
        run.refresh_from_db()
        new = {**ISSUE, 'issue': '새로 부딪힌 조항', 'contested': '새 쟁점의 입장 차이', 'citation': CITATION}
        run.steps[2]['moderator']['new_issues'] = [new]
        run.save()
        review = self.client.get(f'/reviews/{run.pk}/?page=review').content.decode()
        panel = review.split('id="new-issues-section"')[1]
        self.assertIn('<article class="issue-card" id="s3-n1">', panel)
        self.assertIn('새 쟁점의 입장 차이', panel)
    def test_malformed_output_is_rejected(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        good = {'summary': 's', 'items': [{**ITEMS['issues'], 'citation': CITATION}], 'excluded': ['x']}
        bad = [dict(good, items='invalid'), dict(good, extra='unexpected')]
        for field, value in [('signal', '기타'), ('priority', '긴급')]:
            bad.append(dict(good, items=[{**good['items'][0], field: value}]))
        for result in bad:
            with self.subTest(result=result), patch('server.integrations.transport.call', return_value=response(result)):
                self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
                run.refresh_from_db()
                self.assertEqual(run.steps, [])
                self.assertTrue(run.error)

    def test_quote_rules(self):
        check_quote(['제1조 "학생"은 신고한다'], {'page': 1, 'quote': '제1조 “학생”은 신고한다'})
        for quote in ['은', '임차인', '위약금은 10억 원이다.', '임차인은 ... 지원받는다.']:
            with self.subTest(quote=quote), self.assertRaises(ValueError):
                check_quote([TEXT], {'page': 1, 'quote': quote})
        with self.assertRaises(ValueError):
            check_quote([TEXT], {'page': 2, 'quote': TEXT})

    def test_model_page_is_aligned_to_the_quote_but_user_page_is_not(self):
        printed = dict(ANALYSIS, roles=[{**role(name), 'citation': {'page': 12, 'quote': CITATION['quote']}} for name in ('임차인', '임대인')])
        with patch('server.integrations.transport.call', return_value=response(printed)) as model:
            self.client.post('/', {'text': TEXT})
            self.assertEqual(model.call_count, 1)
        run = ReviewRun.objects.latest('id')
        self.assertEqual(run.analysis['roles'][0]['citation']['page'], 1)
        fake = deepcopy(printed)
        fake['roles'][0]['citation']['quote'] = '문서에 없는 인용입니다'
        with patch('server.integrations.transport.call', return_value=response(fake)):
            page = self.client.post('/', {'text': TEXT}, follow=True)
        self.assertContains(page, '문서 분석 재시도')

    def test_quote_on_a_different_page_moves_the_citation(self):
        pages = ['첫 쪽의 내용입니다.', '둘째 쪽의 인용 문구입니다.']
        citations = [{'page': 1, 'quote': '둘째 쪽의 인용 문구입니다.'}, {'page': 1, 'quote': '어디에도 없는 문구입니다.'}]
        align_citations(pages, citations)
        self.assertEqual([citation['page'] for citation in citations], [2, 1])

    def test_quote_survives_punctuation_variants_and_invisible_characters(self):
        pages = ['주거‧결혼∙교육․창업 지원\uf000 기간：3개월∼6개월\x00 포함 접근･활용']
        check_quote(pages, {'page': 1, 'quote': '주거·결혼·교육·창업 지원 기간: 3개월~6개월 포함 접근·활용'})
        with self.assertRaises(ValueError):
            check_quote(pages, {'page': 1, 'quote': '주거·결혼·교육·창업 지급 기간'})

    def test_corrupt_pdf_shows_error(self):
        page = self.client.post('/', {'document': SimpleUploadedFile('a.pdf', b'not a pdf')})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'PDF를 읽을 수 없습니다')

    def test_empty_chat_choices_raise_handled_error(self):
        class Body:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, *args): return b'{"choices": []}'
        payload = {'model': 'm', 'instructions': 'i', 'input': 'x', 'max_output_tokens': 1,
                   'text': {'format': {'name': 'r', 'strict': True, 'schema': {}}}}
        with patch('server.integrations.transport.provider', return_value=('https://x', 'chat_completions')), \
                patch('server.integrations.transport.urlopen', return_value=Body()):
            with self.assertRaises(ValueError):
                transport.call(payload, 'k')

    def test_other_session_cannot_read_advance_or_download(self):
        run = self.completed_run()
        other = Client()
        self.assertEqual(other.get(f'/reviews/{run.pk}/').status_code, 404)
        self.assertEqual(other.post(f'/reviews/{run.pk}/step/', {'cursor': '0'}).status_code, 404)
        self.assertEqual(other.get(f'/reviews/{run.pk}/feedback/0/').status_code, 404)

    def test_failed_step_retries_without_losing_progress(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '2'})
        with patch('server.integrations.transport.call', side_effect=TimeoutError('timeout')):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        run.refresh_from_db()
        self.assertEqual(run.steps, [])
        self.assertTrue(run.error)
        self.run_steps(run, 1)
        run.refresh_from_db()
        self.assertEqual(len(run.steps), 1)
        self.assertEqual(run.error, '')

    def test_role_choice_keeps_the_extracted_roles(self):
        run = self.create_run()
        page = self.client.get(f'/reviews/{run.pk}/')
        self.assertNotContains(page, 'name="name_0"')
        self.assertNotContains(page, '왜 이 역할인가요?')
        form = {'role': '0', 'name_0': '변경 시도'}
        self.assertEqual(self.client.post(f'/reviews/{run.pk}/select/', form).status_code, 302)
        run.refresh_from_db()
        self.assertEqual(run.analysis, ANALYSIS)
        self.assertEqual(run.selected_role, 0)
        self.assertEqual(Client().post(f'/reviews/{run.pk}/select/', {'role': '0'}).status_code, 404)

    def test_third_role_cannot_be_selected_when_two_exist(self):
        run = self.create_run(TWO_ROLES)
        self.assertEqual(self.client.post(f'/reviews/{run.pk}/select/', {'role': '2'}).status_code, 400)

    def test_json_progress_runs_all_steps_and_rejects_stale_cursor(self):
        run = self.create_run()
        selected = self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        self.assertEqual(selected.url, f'/reviews/{run.pk}/?start=1')
        headers = {'HTTP_ACCEPT': 'application/json'}
        initial = self.client.get(f'/reviews/{run.pk}/status/', **headers)
        self.assertEqual(initial['Cache-Control'], 'no-store')
        self.assertEqual(initial.json()['next_label'], '쟁점 정리')
        self.assertEqual(initial.json()['next_phase'], 'discussion')
        with patch('server.integrations.transport.call', side_effect=report_response) as model:
            cursor = 0
            for _ in range(6):
                result = self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(cursor)}, **headers)
                self.assertEqual(result.status_code, 200)
                self.assertGreater(result.json()['cursor'], cursor)
                stale = self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(cursor)}, **headers)
                self.assertEqual(stale.status_code, 409)
                cursor = result.json()['cursor']
            finished = self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(cursor)}, **headers)
            self.assertTrue(finished.json()['complete'])
            self.assertIsNone(finished.json()['next_phase'])
            self.assertEqual(model.call_count, 8)
        self.assertIn('내게 미치는 영향', finished.json()['steps_html'])
        self.assertIn('입장 차이 내용', finished.json()['issues_html'])

    def test_json_failure_retains_checkpoint_until_explicit_retry(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        headers = {'HTTP_ACCEPT': 'application/json'}
        self.run_steps(run, 1, **headers)
        with patch('server.integrations.transport.call', side_effect=TimeoutError('timeout')):
            failed = self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '1'}, **headers)
        self.assertEqual(failed.status_code, 502)
        self.assertEqual(failed.json()['cursor'], 1)
        self.assertEqual(failed.json()['error'], 'timeout')
        self.assertIn('지원 대상', failed.json()['issues_html'])
        stale = self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'}, **headers)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()['error'], 'timeout')
        with patch('server.integrations.transport.call', side_effect=report_response):
            retried = self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '1'}, **headers)
        self.assertEqual(retried.json()['cursor'], 2)
        self.assertEqual(retried.json()['error'], '')

    def test_json_progress_ownership_selection_and_csrf(self):
        run = self.create_run()
        headers = {'HTTP_ACCEPT': 'application/json'}
        self.assertEqual(Client().get(f'/reviews/{run.pk}/status/', **headers).status_code, 404)
        self.assertEqual(self.client.post(f'/reviews/{run.pk}/status/', **headers).status_code, 405)
        with patch('server.integrations.transport.call') as model:
            unselected = self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'}, **headers)
            self.assertEqual(unselected.status_code, 400)
            model.assert_not_called()
        protected = Client(enforce_csrf_checks=True)
        protected.cookies = self.client.cookies
        self.assertEqual(protected.post(f'/reviews/{run.pk}/step/', {'cursor': '0'}, **headers).status_code, 403)

    def test_five_pages_show_their_own_steps(self):
        run = self.completed_run(selected='1')
        self.assertContains(self.client.get(f'/reviews/{run.pk}/?page=summary'), '먼저, 핵심부터.')
        discussion = self.client.get(f'/reviews/{run.pk}/?page=discussion')
        self.assertContains(discussion, '문서에서 찾은 쟁점')
        self.assertContains(discussion, '입장 차이 내용')
        self.assertContains(discussion, '시행일은 자명해 제외했다.')
        self.assertContains(discussion, 'class="issue-card" id="s1-i1"')
        self.assertNotContains(discussion, 'id="s2-i1"')
        review = self.client.get(f'/reviews/{run.pk}/?page=review')
        self.assertContains(review, 'class="chat-message is-self" id="s2-i1"')
        self.assertContains(review, 'class="chat-message" id="s3-i1"')
        self.assertContains(review, 'id="s3-moderator"')
        self.assertContains(review, '<strong>지키려는 것</strong> 지원 대상에서 빠지지 않는 것')
        self.assertContains(review, 'id="s5-empty"')  # The moderator closing the issue.
        self.assertContains(review, 'id="s6-empty"')
        self.assertNotContains(review, 'id="s1-i1"')
        proposal = self.client.get(f'/reviews/{run.pk}/?page=proposal')
        self.assertContains(proposal, 'id="s7-i1"')
        self.assertContains(proposal, '내가 확인할 것')
        self.assertContains(proposal, '법률·세무 자문이 아니니')
        self.assertNotContains(proposal, '이렇게 바꿔보세요')
        self.assertNotContains(proposal, 'id="s2-i1"')

    def test_cautions_sort_by_priority_and_only_high_opens(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        self.run_steps(run, 6)
        low, high = [{**ITEMS['final'], 'issue': name, 'priority': level, 'citation': CITATION, 'target_ids': ['s2-i1']}
                     for name, level in [('낮은 조항', '낮음'), ('높은 조항', '높음')]]
        with patch('server.integrations.transport.call', return_value=response({'summary': 's', 'items': [low, high]})):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '6'})
        run.refresh_from_db()
        self.assertEqual([item['issue'] for item in run.steps[-1]['result']['items']], ['높은 조항', '낮은 조항'])
        page = self.client.get(f'/reviews/{run.pk}/?page=proposal')
        self.assertContains(page, '<details class="source" open>', count=1)

    def test_page_three_and_four_keep_their_layout(self):
        run = self.completed_run()
        markers = {'discussion': ('class="document-sidebar glass"', 'id="issue-cards"', 'class="run-controls"'),
                   'review': ('class="document-sidebar glass"', 'class="chat-room glass"', 'class="chat-header"', 'id="current-issue"', 'class="run-controls"')}
        for page, expected in markers.items():
            html = self.client.get(f'/reviews/{run.pk}/?page={page}')
            for marker in expected:
                self.assertContains(html, marker)

    def test_phase_boundaries_and_locked_next_page(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        early = self.client.get(f'/reviews/{run.pk}/?page=review&start=1')
        self.assertNotContains(early, 'id="review-runner"')
        self.assertContains(early, '앞선 검토로 돌아가기')
        self.run_steps(run, 1)
        discussion = self.client.get(f'/reviews/{run.pk}/?page=discussion')
        self.assertNotContains(discussion, 'id="review-runner"')
        self.assertContains(discussion, '쟁점 토론 보기')
        review = self.client.get(f'/reviews/{run.pk}/?page=review')
        self.assertContains(review, 'id="review-runner"')
        self.assertContains(review, 'data-phase="review"')

    def test_feedback_letters_for_each_role(self):
        run = self.completed_run()
        letters = feedback_letters(run)
        self.assertEqual([letter['name'] for letter in letters], ['임차인', '임대인', '지자체'])
        self.assertIn('요청: 기준 공개 요청', letters[1]['text'])
        self.assertIn('실제 당사자의 의견이 아닙니다', letters[1]['text'])
        self.assertContains(self.client.get(f'/reviews/{run.pk}/?page=proposal'), '임대인의 의견서')
        download = self.client.get(f'/reviews/{run.pk}/feedback/1/')
        self.assertEqual(download['Content-Type'], 'text/plain; charset=utf-8')
        self.assertIn('attachment', download['Content-Disposition'])
        self.assertIn('임대인', download.content.decode())
        self.assertEqual(self.client.get(f'/reviews/{run.pk}/feedback/3/').status_code, 404)

    def test_letters_wait_for_completion(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        self.run_steps(run, 2)
        run.refresh_from_db()
        self.assertEqual(feedback_letters(run), [])
        self.assertEqual(self.client.get(f'/reviews/{run.pk}/feedback/0/').status_code, 404)

    def plain(self, text='단일 답변'):
        return {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}

    def baseline_replies(self, text='단일 답변'):
        # The single prompt, then the call that moves its answer into the caution fields.
        return [self.plain(text), response({'items': [formatted(text)]})]

    def test_baseline_is_the_literal_single_prompt_and_runs_once(self):
        run = self.completed_run(selected='1')
        with patch('server.integrations.transport.call', side_effect=self.baseline_replies()) as model:
            self.client.post(f'/reviews/{run.pk}/compare/run/')
            self.client.post(f'/reviews/{run.pk}/compare/run/')
            self.assertEqual(model.call_count, 2)
        payload, copy = [call.args[0] for call in model.call_args_list]
        self.assertIn('나는 임대인인데, 나한테 불리한 조항 찾아줘.', payload['instructions'])
        self.assertNotIn('text', payload)
        self.assertEqual(data_of(payload)['pages'][0]['text'], TEXT)
        self.assertEqual(data_of(copy), {'baseline_answer': '단일 답변'})  # The copy never sees the document.
        run.refresh_from_db()
        self.assertEqual(run.baseline, '단일 답변')
        self.assertEqual(run.baseline_items, [formatted('단일 답변')])
        self.assertIn(run.evaluation['pipeline'], ('A', 'B'))
        self.assertEqual([call['purpose'] for call in run.calls[-2:]], ['model', 'format'])

    def test_both_sides_share_one_layout(self):
        run = self.completed_run()
        with patch('server.integrations.transport.call', side_effect=self.baseline_replies()):
            page = self.client.post(f'/reviews/{run.pk}/compare/run/', follow=True)
        texts = re.findall(r'<p class="compare-text" tabindex="0">(.*?)</p>', page.content.decode(), re.S)
        self.assertEqual(len(texts), 2)
        for text in texts:
            self.assertTrue(text.startswith('1. '))
            self.assertIn('영향: ', text)
        baseline = next(text for text in texts if '단일 답변' in text)
        self.assertIn('원문: 임차인은 월세를 지원받는다.', baseline)  # No page in the answer, so none is shown.
        self.assertNotIn('다른 입장:', baseline)  # A field the answer left empty is left out.

    def test_baseline_waits_for_completed_review(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        self.assertEqual(self.client.get(f'/reviews/{run.pk}/compare/').status_code, 302)
        with patch('server.integrations.transport.call') as model:
            self.client.post(f'/reviews/{run.pk}/compare/run/')
            model.assert_not_called()

    def test_baseline_failure_is_retryable(self):
        run = self.completed_run()
        with patch('server.integrations.transport.call', side_effect=TimeoutError('timeout')):
            page = self.client.post(f'/reviews/{run.pk}/compare/run/', follow=True)
        self.assertContains(page, 'timeout')
        self.assertContains(page, '비교 결과 만들기')
        with patch('server.integrations.transport.call', side_effect=self.baseline_replies()):
            page = self.client.post(f'/reviews/{run.pk}/compare/run/', follow=True)
        self.assertContains(page, '단일 답변')

    def test_sides_stay_blind_until_rated_and_rating_is_final(self):
        run = self.completed_run()
        self.assertContains(self.client.get(f'/reviews/{run.pk}/?page=proposal'), '두 결과 비교하기')
        for side in 'AB':
            with self.subTest(side=side):
                run.baseline, run.evaluation = '', {}
                run.save()
                with patch('server.integrations.transport.call', side_effect=self.baseline_replies()), \
                        patch('server.agents.runner.random.choice', return_value=side):
                    page = self.client.post(f'/reviews/{run.pk}/compare/run/', follow=True)
                self.assertNotContains(page, ' · PolicyLens')
                self.assertNotContains(page, ' · 단일 프롬프트')
                html = page.content.decode()
                self.assertEqual(html.index('단일 답변') < html.index('결정 전 확인 필요'), side == 'B')
        self.assertEqual(self.client.post(f'/reviews/{run.pk}/compare/rate/', {'preferred': 'C'}).status_code, 400)
        page = self.client.post(f'/reviews/{run.pk}/compare/rate/', {'preferred': 'A', 'note': '이유'}, follow=True)
        self.assertContains(page, ' · PolicyLens')
        self.client.post(f'/reviews/{run.pk}/compare/rate/', {'preferred': 'B'})
        run.refresh_from_db()
        self.assertEqual((run.evaluation['preferred'], run.evaluation['note']), ('A', '이유'))

    def test_compare_hides_markdown_marks_without_touching_the_stored_answer(self):
        self.assertEqual(plain_text('## 제목\n\n\n\n**굵게** `코드`\n---\n> 인용\n| 가 | 나 |\n|---|---|\n| 1 | 2 |\n- 항목 -5%'),
                         '제목\n\n굵게 코드\n인용\n가 / 나\n1 / 2\n- 항목 -5%')
        run = self.completed_run()
        run.baseline, run.evaluation = '## 단일 **답변**', {'pipeline': 'A'}
        run.save()
        page = self.client.get(f'/reviews/{run.pk}/compare/')
        self.assertContains(page, '단일 답변')
        self.assertNotContains(page, '## 단일')
        run.refresh_from_db()
        self.assertEqual(run.baseline, '## 단일 **답변**')

    def test_upload_is_named_after_its_file(self):
        def title_of(**form):
            with patch('server.integrations.transport.call', side_effect=report_response):
                self.client.post('/', form)
            return ReviewRun.objects.latest('pk').title
        upload = lambda: SimpleUploadedFile('대학_AI_가이드라인.txt', '본문 내용'.encode())
        self.assertEqual(title_of(document=upload()), '대학 AI 가이드라인')
        self.assertEqual(title_of(text='본문 내용'), '정책 검토')
        self.assertNotContains(self.client.get('/'), 'name="title"')

    def test_cautions_set_my_reading_against_another_roles(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '1'})
        model, _ = self.run_steps(run, 7)
        final = model.call_args_list[-1].args[0]
        self.assertEqual(final['text']['format']['schema']['properties']['items']['items']['properties']['other_role']['enum'], ['임차인', '지자체'])
        page = self.client.get(f'/reviews/{run.pk}/?page=proposal')
        self.assertContains(page, '갈리는 표현</span> “월세를 지원받는다”')
        self.assertContains(page, '내 해석')
        self.assertContains(page, '지자체의 해석')
        self.assertContains(page, '지자체는 재량으로 대상을 정할 수 있다고 읽는다')
        run.refresh_from_db()
        text = pipeline_text(run)
        self.assertIn('내 해석: 기준이 없으면 탈락할 수 있다고 읽는다', text)
        self.assertLess(text.index('갈리는 표현: "월세를 지원받는다"'), text.index('내 해석: '))
        self.assertLess(text.index('내 해석: '), text.index('지자체의 해석: '))

    def test_disputed_phrase_must_come_from_the_quoted_clause(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        self.run_steps(run, 6)
        result = lambda phrase: response({'summary': 's', 'items': [{**ITEMS['final'], 'phrase': phrase, 'citation': CITATION, 'target_ids': ['s2-i1']}]})
        with patch('server.integrations.transport.call', side_effect=[result('노동시장 취약계층'), result('월세를  지원받는다')]) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '6'})
        run.refresh_from_db()
        self.assertEqual(run.error, '')
        self.assertIn('phrase', data_of(model.call_args_list[1].args[0])['validation_error'])

    def test_nul_in_document_text_is_dropped_before_saving(self):
        with patch('server.integrations.transport.call', side_effect=report_response):
            self.client.post('/', {'text': '본문\x00 내용'})
        self.assertEqual(ReviewRun.objects.latest('pk').pages, ['본문 내용'])

    def test_caution_tags_carry_their_priority_for_styling(self):
        run = self.completed_run()
        priority = run.steps[-1]['result']['items'][0]['priority']
        page = self.client.get(f'/reviews/{run.pk}/?page=proposal')
        self.assertContains(page, f'class="tag" data-priority="{priority}"')

    def test_final_page_and_letters_explain_page_numbers(self):
        run = self.completed_run()
        page = self.client.get(f'/reviews/{run.pk}/?page=proposal')
        self.assertContains(page, '쪽 번호는 파일의 쪽 순서')
        self.assertNotContains(page, '문서만 보고')
        self.assertIn('쪽 번호는 파일의 쪽 순서', feedback_letters(run)[0]['text'])

    def test_compare_requires_owner_and_post(self):
        run = self.completed_run()
        with patch('server.integrations.transport.call', side_effect=self.baseline_replies()):
            self.client.post(f'/reviews/{run.pk}/compare/run/')
        other = Client()
        self.assertEqual(other.get(f'/reviews/{run.pk}/compare/').status_code, 404)
        self.assertEqual(other.post(f'/reviews/{run.pk}/compare/run/').status_code, 404)
        self.assertEqual(other.post(f'/reviews/{run.pk}/compare/rate/', {'preferred': 'A'}).status_code, 404)
        self.assertEqual(self.client.get(f'/reviews/{run.pk}/compare/rate/').status_code, 405)

    def test_chat_mode_omits_response_format_for_plain_text(self):
        class Body:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, *args): return b'{"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}'
        with patch('server.integrations.transport.provider', return_value=('https://x', 'chat_completions')), \
                patch('server.integrations.transport.urlopen', return_value=Body()) as opened:
            transport.call({'model': 'm', 'instructions': 'i', 'input': 'x', 'max_output_tokens': 1}, 'k')
        self.assertNotIn('response_format', json.loads(opened.call_args.args[0].data))

    def test_document_html_is_escaped(self):
        with patch('server.integrations.transport.call', return_value=response(ANALYSIS)):
            self.client.post('/', {'text': TEXT + '<script>alert(1)</script>'})
        run = ReviewRun.objects.latest('id')
        page = self.client.get(f'/reviews/{run.pk}/')
        self.assertContains(page, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(page, '<script>alert(1)</script>')

    # Server data: agents look things up beyond the uploaded document.

    def add_source(self, doc_id='seoul-rent', kind='policy', pages=('국토부 청년월세 수 혜 자 는 중복 지원을 받을 수 없다.',)):
        return Source.objects.create(doc_id=doc_id, kind=kind, title='국토부 청년월세 공고', issuer='국토교통부', version='2026년 1회차',
                                     source_url='https://example.go.kr/1', pages=list(pages))

    def tool_call(self, name='search_sources', arguments=None, call_id='c1'):
        arguments = {'query': '청년월세 중복', 'kind': 'all'} if arguments is None else arguments
        return {'status': 'completed', 'output': [{'type': 'function_call', 'call_id': call_id, 'name': name, 'arguments': json.dumps(arguments)}]}

    def selected_run(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        self.run_steps(run, 1)  # The issues step reads no server data.
        run.refresh_from_db()
        return run

    def role_result(self, **source):
        item = {**ITEMS['debate'], 'citation': CITATION, 'target_ids': ['s1-i1'], 'sources': [source] if source else []}
        return response({'summary': 's', 'items': [item]})

    GOOD_SOURCE = {'source_id': 'seoul-rent', 'page': 1, 'quote': '수혜자는 중복 지원을 받을 수 없다', 'finding': '중복 지원 불가'}

    def test_search_matches_across_broken_spacing_and_filters_kind(self):
        self.add_source()
        self.add_source('op-1', 'opinion', ['청년월세 중복 때문에 신청을 포기했다.'])
        research = new_research()
        found = search_sources([TEXT], research, '수혜자 청년월세', 'all')
        self.assertEqual(found['results'][0]['source_id'], 'seoul-rent')
        self.assertEqual({r['source_id'] for r in search_sources([TEXT], new_research(), '청년월세', 'opinion')['results']}, {'op-1'})
        self.assertEqual(search_sources([TEXT], new_research(), '존재하지않는말', 'all')['results'], [])
        self.assertIn(('seoul-rent', 1), research['opened'])

    def test_search_finds_variant_words_and_prefers_recent_sources(self):
        self.add_source('old-round', pages=['국토교통부 청년월세 특별지원 중복수혜 지원 종료 안내 2023년 공고'])
        Source.objects.filter(doc_id='old-round').update(published_on='2023-01-01', title='옛 공고', issuer='서울시')
        self.add_source('notice', pages=['국토부 청년월세 지원 사업 중복 선정자 지급중지 안내'])
        Source.objects.filter(doc_id='notice').update(published_on='2026-09-15', title='중복 선정자 지급중지 안내', issuer='서울시')
        research = new_research('2026-10-01')
        found = search_sources([TEXT], research, '국토교통부 청년월세 중복수혜', 'all')['results']
        self.assertEqual(found[0]['source_id'], 'notice')
        self.assertTrue(search_sources([TEXT], new_research(), '국토교통부', 'all')['results'][0]['excerpt'].startswith('국토부'))

    def test_search_never_returns_the_uploaded_document(self):
        self.add_source(pages=[TEXT])
        self.assertEqual(search_sources([TEXT], new_research(), '임차인', 'all')['results'], [])
        self.assertIn('error', read_source([TEXT], new_research(), 'seoul-rent', 1))

    def test_read_source_rejects_bad_page_and_unknown_id(self):
        self.add_source()
        self.assertIn('error', read_source([TEXT], new_research(), 'seoul-rent', 2))
        self.assertIn('error', read_source([TEXT], new_research(), 'nope', 1))

    def test_agent_searches_then_answers_with_a_verified_snapshot(self):
        self.add_source()
        run = self.selected_run()
        with patch('server.integrations.transport.call', side_effect=[self.tool_call(), self.role_result(**self.GOOD_SOURCE)]) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '1'})
        run.refresh_from_db()
        self.assertEqual(run.error, '')
        self.assertEqual(model.call_count, 2)
        self.assertEqual(model.call_args_list[0].args[0]['tools'][0]['name'], 'search_sources')
        self.assertEqual(model.call_args_list[0].args[0]['tool_choice'], 'required')
        self.assertNotIn('tool_choice', model.call_args_list[1].args[0])
        self.assertEqual(model.call_args_list[1].args[0]['input'][-1]['type'], 'function_call_output')
        step = run.steps[1]
        self.assertEqual([{k: v for k, v in log.items() if k != 'elapsed_ms'} for log in step['research']],
                         [{'tool': 'search_sources', 'input': '청년월세 중복', 'found': 1}])
        self.assertGreaterEqual(step['research'][0]['elapsed_ms'], 0)
        self.assertEqual(step['result']['items'][0]['sources'][0]['title'], '국토부 청년월세 공고')
        Source.objects.all().delete()
        self.assertContains(self.client.get(f'/reviews/{run.pk}/?page=review'), '지원 대상')

    def test_step_limit_forces_an_answer_without_more_tools(self):
        self.add_source()
        run = self.selected_run()
        replies = [self.tool_call(call_id=f'c{n}') for n in range(MAX_TOOL_ROUNDS)] + [self.role_result()]
        with patch('server.integrations.transport.call', side_effect=replies) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '1'})
        run.refresh_from_db()
        self.assertEqual(run.error, '')
        self.assertEqual(model.call_count, MAX_TOOL_ROUNDS + 1)
        self.assertEqual(model.call_args.args[0]['tool_choice'], 'none')

    def test_uncited_or_unread_source_goes_to_repair_with_what_was_read(self):
        self.add_source()
        run = self.selected_run()
        bad = {**self.GOOD_SOURCE, 'quote': '문서에 없는 인용문입니다'}
        with patch('server.integrations.transport.call', side_effect=[self.tool_call(), self.role_result(**bad), self.role_result(**self.GOOD_SOURCE)]) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '1'})
        run.refresh_from_db()
        self.assertEqual(run.error, '')
        repair = model.call_args.args[0]
        self.assertNotIn('tools', repair)
        self.assertEqual(data_of(repair)['server_sources'][0]['source_id'], 'seoul-rent')
        run = self.selected_run()
        with patch('server.integrations.transport.call', return_value=self.role_result(**self.GOOD_SOURCE)):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '1'})
        run.refresh_from_db()
        self.assertIn('도구로 읽지 않은', run.error)

    def unwrapped(self, payload, issues=1):
        if isinstance(payload['input'], list):
            payload = {**payload, 'input': payload['input'][0]['content']}
        return response(result_for(payload, issues))

    def test_moderator_does_not_search_and_each_roles_first_statement_must(self):
        self.add_source()
        run = self.selected_run()
        with patch('server.integrations.transport.call', side_effect=[self.tool_call(), self.role_result(**self.GOOD_SOURCE)]):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '1'})
        seen = []
        def reply(payload, key):
            seen.append(payload)
            return self.unwrapped(payload)
        with patch('server.integrations.transport.call', side_effect=reply):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '2'})
        self.assertEqual(stage_of(seen[0]), 'moderator')
        self.assertEqual([tool['name'] for tool in seen[0]['tools']], ['note_issue'])  # It may note issues but never search.
        self.assertIn('국토부', seen[0]['input'][0]['content'])  # What a role found is shared from the debate on.
        self.assertNotIn('"research"', seen[0]['input'][0]['content'])
        self.assertEqual(seen[1]['tool_choice'], 'required')

    def test_a_roles_later_statement_searches_only_when_the_model_asks(self):
        self.add_source()
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        with patch('server.integrations.transport.call', side_effect=lambda payload, key: self.unwrapped(payload, 2)):
            for _ in range(5):
                run.refresh_from_db()
                self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(len(run.steps))})
        seen = []
        def reply(payload, key):
            seen.append(payload)
            return self.unwrapped(payload, 2)
        with patch('server.integrations.transport.call', side_effect=reply):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '5'})  # The user's role opens the second issue.
        self.assertEqual(json.loads(seen[0]['input'][0]['content'])['acting_role']['name'], '임차인')
        self.assertIn('tools', seen[0])
        self.assertNotIn('tool_choice', seen[0])

    def test_empty_server_data_and_old_runs_stay_on_the_document(self):
        run = self.selected_run()
        with patch('server.integrations.transport.call', return_value=self.role_result()) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '1'})
        self.assertNotIn('tools', model.call_args.args[0])
        self.assertIsInstance(model.call_args.args[0]['input'], str)
        self.add_source()
        run = self.selected_run()
        run.prompts.pop('sources')
        run.save()
        with patch('server.integrations.transport.call', return_value=self.role_result()) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '1'})
        self.assertNotIn('tools', model.call_args.args[0])

    def test_final_card_and_letter_show_server_evidence(self):
        run = self.completed_run()
        source = {**self.GOOD_SOURCE, 'title': '국토부 청년월세 공고', 'version': '2026년 1회차', 'issuer': '국토교통부', 'kind': '정책', 'source_url': 'https://example.go.kr/1'}
        for stage in (-1, 3):
            run.steps[stage]['result']['items'][0]['sources'] = [source]
        run.steps[-1]['research'] = [{'tool': 'search_sources', 'input': '청년월세 중복', 'found': 1}]
        run.save()
        page = self.client.get(f'/reviews/{run.pk}/?page=proposal')
        self.assertContains(page, '다른 자료에서 확인한 내용')
        self.assertContains(page, '찾아본 기록 1건')
        self.assertContains(page, 'rel="noopener"')
        self.assertIn('참고 자료: 국토부 청년월세 공고', feedback_letters(run)[2]['text'])
        self.assertNotContains(self.client.get(f'/reviews/{run.pk}/?page=review'), '다른 자료에서 확인한 내용')

    def test_chat_transport_carries_tool_turns_both_ways(self):
        class Body:
            sent = None
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps({'choices': [{'finish_reason': 'tool_calls', 'message': {'content': None, 'tool_calls': [
                {'id': 'c2', 'type': 'function', 'function': {'name': 'read_source', 'arguments': '{}'}}]}}]}).encode()
        def opened(request, timeout):
            Body.sent = json.loads(request.data)
            return Body()
        payload = {'model': 'm', 'instructions': 'i', 'max_output_tokens': 10, 'tool_choice': 'none',
                   'tools': [{'type': 'function', 'name': 'search_sources', 'parameters': {}}],
                   'input': [{'role': 'user', 'content': 'u'}, {'type': 'function_call', 'call_id': 'c1', 'name': 'search_sources', 'arguments': '{}'},
                             {'type': 'function_call_output', 'call_id': 'c1', 'output': 'r'}]}
        with patch('server.integrations.transport.provider', return_value=('https://x', 'chat_completions')), \
                patch('server.integrations.transport.urlopen', side_effect=opened):
            result = transport.call(payload, 'k')
        self.assertEqual([m['role'] for m in Body.sent['messages']], ['system', 'user', 'assistant', 'tool'])
        self.assertEqual(Body.sent['tools'][0]['function']['name'], 'search_sources')
        self.assertEqual(Body.sent['tool_choice'], 'none')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['output'][0], {'type': 'function_call', 'call_id': 'c2', 'name': 'read_source', 'arguments': '{}'})

    def test_parallel_tool_calls_share_one_assistant_turn(self):
        call = lambda n: {'type': 'function_call', 'call_id': n, 'name': 'search_sources', 'arguments': '{}'}
        answer = lambda n: {'type': 'function_call_output', 'call_id': n, 'output': 'r'}
        messages = transport.chat_messages({'instructions': 'i', 'input': [{'role': 'user', 'content': 'u'}, call('a'), call('b'), answer('a'), answer('b'), call('c'), answer('c')]})
        self.assertEqual([m['role'] for m in messages], ['system', 'user', 'assistant', 'tool', 'tool', 'assistant', 'tool'])
        self.assertEqual([c['id'] for c in messages[2]['tool_calls']], ['a', 'b'])

    def test_load_sources_keeps_only_documents_that_passed_their_gates(self):
        with tempfile.TemporaryDirectory() as folder, self.settings(BASE_DIR=Path(folder)):
            base = Path(folder) / 'data'
            (base / 'reviewed').mkdir(parents=True)
            docs = [{'doc_id': name, 'kind': 'policy', 'title': name, 'issuer': '기관', 'version': '1회차', 'source_url': 'https://x.go.kr', 'published_on': '2026-04-30',
                     'external_send_ok': ok, 'gate': {'technical': 'pass', 'rights': rights}} for name, ok, rights in
                    [('good', True, 'pass'), ('no-send', False, 'pass'), ('no-rights', True, 'hold')]]
            (base / 'reviewed' / 'documents.jsonl').write_text('\n'.join(map(json.dumps, docs)))
            opinions = [{'opinion_id': f'op-{status}', 'doc_id': doc, 'source_type': '회의록', 'author_group': '청년', 'text': '의견 본문', 'submitted_on': '2026-08-10',
                         'source_url': 'https://x.go.kr', 'review_status': status} for doc, status in [('good', 'reviewed'), ('good', 'pending'), ('no-send', 'reviewed')]]
            (base / 'reviewed' / 'opinions.jsonl').write_text('\n'.join(map(json.dumps, opinions)))
            (base / 'processed' / 'good').mkdir(parents=True)
            (base / 'processed' / 'good' / 'pages.json').write_text(json.dumps([{'page': 1, 'text': '본문'}]))
            self.add_source('dropped-gate')
            call_command('load_sources', stdout=StringIO())
        self.assertEqual({s.doc_id: s.kind for s in Source.objects.all()}, {'good': 'policy', 'op-reviewed': 'opinion'})
        self.assertEqual(Source.objects.get(doc_id='good').pages, ['본문'])
        self.assertEqual(str(Source.objects.get(doc_id='good').published_on), '2026-04-30')
        self.assertEqual(str(Source.objects.get(doc_id='op-reviewed').published_on), '2026-08-10')

    def test_as_of_hides_what_was_published_after_the_document(self):
        self.add_source('before', pages=['청년월세 사전 자료'])
        Source.objects.filter(doc_id='before').update(published_on='2026-01-01')
        self.add_source('after', pages=['청년월세 사후 공지'])
        Source.objects.filter(doc_id='after').update(published_on='2026-09-15')
        self.add_source('undated', pages=['청년월세 날짜 없음'])
        self.add_source('opinion', 'opinion', ['청년월세 의회 발언'])
        Source.objects.filter(doc_id='opinion').update(published_on='2026-01-01')
        limited = new_research('2026-04-30')
        self.assertEqual({r['source_id'] for r in search_sources([TEXT], limited, '청년월세', 'all')['results']}, {'before'})
        self.assertIn('error', read_source([TEXT], limited, 'after', 1))
        self.assertEqual(len(search_sources([TEXT], new_research(), '청년월세', 'all')['results']), 4)

    def issues_result(self):
        return response({'summary': 's', 'items': [{**ITEMS['issues'], 'citation': CITATION}], 'excluded': []})

    def test_each_call_is_logged_even_when_it_fails(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        ok = dict(self.issues_result(), usage={'total_tokens': 123})
        with patch('server.integrations.transport.call', return_value=ok):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        with patch('server.integrations.transport.call', side_effect=TimeoutError('timeout')):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '1'})
        run.refresh_from_db()
        self.assertEqual(run.calls[-3]['tokens'], 123)
        self.assertEqual([(call['error'], call['role']) for call in run.calls[-2:]], [('TimeoutError', 0), ('TimeoutError', 0)])

    def test_one_stalled_call_is_retried_without_stopping_the_step(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        with patch('server.integrations.transport.call', side_effect=[TimeoutError('stall'), self.issues_result()]) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        run.refresh_from_db()
        self.assertEqual((model.call_count, run.error, len(run.steps)), (2, '', 1))
        with patch('server.integrations.transport.call', side_effect=ValueError('bad')) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '1'})
        self.assertEqual(model.call_count, 1)

    def test_score_counts_gold_issues_near_each_other_per_arm(self):
        with tempfile.TemporaryDirectory() as folder, self.settings(BASE_DIR=Path(folder)):
            reviewed = Path(folder) / 'data' / 'reviewed'
            (reviewed / 'runs').mkdir(parents=True)
            issue = lambda name, first, second: {'issue_id': name, 'match': [first, second]}
            (reviewed / 'annotations.jsonl').write_text(json.dumps({'doc_id': 'doc', 'stakeholders': [{'group': '임차인', 'match': '임차인'}],
                                                                    'issues': [issue('A', '환수', '국토'), issue('B', '보류', '변경')]}))
            run = {'arm': 'sources', 'analysis': ANALYSIS, 'calls': [{}], 'baseline': '국토부에 선정되면 ' + '가' * 400 + ' 환수될 수 있다',
                   'steps': [{'result': {'items': [{'issue': '국토부 선정 시 환수'}]}}]}
            (reviewed / 'runs' / 'doc-sources.json').write_text(json.dumps(run, ensure_ascii=False), encoding='utf-8')
            out = StringIO()
            call_command('score', stdout=out)
        self.assertIn('doc\tsources\t1/2\tA', out.getvalue())
        self.assertIn('doc\t단일 프롬프트\t0/2', out.getvalue())  # Too far apart to be one claim.
        self.assertIn('이해관계자\t1/1', out.getvalue())

    def test_evaluate_saves_a_time_limited_run_and_leaves_no_row(self):
        with tempfile.TemporaryDirectory() as folder, self.settings(BASE_DIR=Path(folder)):
            base = Path(folder) / 'data'
            (base / 'reviewed').mkdir(parents=True)
            (base / 'processed' / 'doc').mkdir(parents=True)
            (base / 'processed' / 'doc' / 'pages.json').write_text(json.dumps([{'page': 1, 'text': TEXT}]))
            (base / 'reviewed' / 'documents.jsonl').write_text(json.dumps({'doc_id': 'doc', 'title': '월세', 'published_on': '2026-04-30', 'gate': {'technical': 'pass', 'rights': 'pass'}, 'external_send_ok': True}))
            prompts = Path(__file__).resolve().parent.parent / 'prompts'
            (Path(folder) / 'prompts').symlink_to(prompts)
            before = ReviewRun.objects.count()
            def reply(payload, key):
                if 'text' not in payload:
                    return {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '기준선'}]}]}
                return response(ANALYSIS) if 'roles' in payload['text']['format']['schema']['properties'] else response(result_for(payload))
            with patch('server.integrations.transport.call', side_effect=reply):
                call_command('evaluate', 'doc', '--no-sources', stdout=StringIO())
            saved = json.loads((base / 'reviewed' / 'runs' / 'doc-document.json').read_text(encoding='utf-8'))
            with patch('server.integrations.transport.call', side_effect=reply):
                call_command('evaluate', 'doc', '--reference-run', str(base / 'reviewed' / 'runs' / 'doc-document.json'), stdout=StringIO())
            paired = json.loads((base / 'reviewed' / 'runs' / 'doc-sources.json').read_text(encoding='utf-8'))
            self.assertEqual(paired['analysis'], saved['analysis'])
            self.assertEqual(paired['baseline'], saved['baseline'])
            self.assertTrue(paired['reused_analysis_and_baseline'])
            self.assertFalse(any(c['stage'] in ('analysis', 'baseline') for c in paired['calls']))

        self.assertEqual(saved['as_of'], '2026-04-30')
        self.assertEqual(saved['baseline'], '기준선')
        self.assertEqual([step['stage'] for step in saved['steps']], ['issues', 'debate', 'debate', 'debate', 'close', 'final'])
        self.assertEqual(ReviewRun.objects.count(), before)


EN_ROLES = [role('Tenant'), role('Landlord', 'implied'), role('Local government')]
EN_ANALYSIS = dict(ANALYSIS, roles=EN_ROLES)


def strings(value):
    """Every model-written or user-supplied string, so what is left of a page is the interface itself."""
    if isinstance(value, str):
        return [value]
    values = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    return [text for item in values for text in strings(item)]


class LanguageTests(TestCase):
    setUp = ReviewFlowTests.setUp
    create_run = ReviewFlowTests.create_run
    run_steps = ReviewFlowTests.run_steps
    completed_run = ReviewFlowTests.completed_run
    plain = ReviewFlowTests.plain
    baseline_replies = ReviewFlowTests.baseline_replies
    run_to_end = ReviewFlowTests.run_to_end

    def english_run(self, **extra):
        self.client.get('/?lang=en')
        return self.completed_run(EN_ANALYSIS, **extra)

    def leftover_korean(self, html, run):
        for text in sorted(strings([run.title, run.pages, run.analysis, run.personas, run.steps, run.baseline, run.baseline_items, run.evaluation]), key=len, reverse=True):
            html = html.replace(text, '')
        return re.findall(r'[가-힣]+', html)

    def test_first_screen_switch_changes_the_whole_screen(self):
        home = self.client.get('/')
        self.assertContains(home, 'class="lang-switch" data-lang="ko"')
        self.assertContains(home, '<html lang="ko">')
        self.assertRedirects(self.client.get('/?lang=en'), '/')
        home = self.client.get('/')
        self.assertContains(home, 'class="lang-switch" data-lang="en"')
        self.assertContains(home, '<html lang="en">')
        self.assertEqual(self.leftover_korean(home.content.decode().replace('한국어', ''), ReviewRun()), [])

    def test_unknown_language_is_ignored(self):
        self.client.get('/?lang=fr')
        self.assertContains(self.client.get('/'), 'data-lang="ko"')

    def test_run_keeps_the_language_chosen_at_upload(self):
        run = self.english_run()
        self.assertEqual(run.language, 'en')
        self.client.get('/?lang=ko')
        self.assertContains(self.client.get(f'/reviews/{run.pk}/?page=summary'), 'Start with the essentials.')
        self.assertEqual(self.create_run().language, 'ko')

    def test_english_run_adds_the_english_instructions_last(self):
        self.client.get('/?lang=en')
        with patch('server.integrations.transport.call', return_value=response(EN_ANALYSIS)) as model:
            self.client.post('/', {'text': TEXT})
        english = (settings.BASE_DIR / 'prompts' / 'lang_en.md').read_text(encoding='utf-8').strip()
        self.assertTrue(model.call_args.args[0]['instructions'].rstrip().endswith(english))
        run = ReviewRun.objects.latest('id')
        self.assertEqual(run.title, 'Policy review')
        self.client.get('/?lang=ko')
        with patch('server.integrations.transport.call', return_value=response(ANALYSIS)) as model:
            self.client.post('/', {'text': TEXT})
        self.assertNotIn(english, model.call_args.args[0]['instructions'])

    def test_every_page_of_an_english_run_is_english(self):
        run = self.english_run()
        pages = [self.client.get(f'/reviews/{run.pk}/?page={page}') for page in ('summary', 'discussion', 'review', 'proposal')]
        pages.append(self.client.get('/'))
        for page in pages:
            self.assertEqual(self.leftover_korean(page.content.decode().replace('한국어', ''), run), [])
        proposal = pages[3].content.decode()
        self.assertIn('Caution: High', proposal)
        self.assertIn('Concentrated discretion', proposal)

    def test_english_progress_labels_and_letters(self):
        self.client.get('/?lang=en')
        run = self.create_run(EN_ANALYSIS)
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        state = self.client.get(f'/reviews/{run.pk}/status/', HTTP_ACCEPT='application/json').json()
        self.assertEqual(state['next_label'], 'Sorting the issues')
        self.run_to_end(run)
        run.refresh_from_db()
        with translation.override('en'):
            from .agents.progress import feedback_letters
            letter = feedback_letters(run)[1]['text']
        self.assertIn('Request: 기준 공개 요청', letter)
        self.assertIn('not the opinion of an actual party', letter)

    def test_english_run_compares_with_the_english_single_prompt(self):
        run = self.english_run(selected='1')
        with patch('server.integrations.transport.call', side_effect=self.baseline_replies('Single answer')) as model:
            page = self.client.post(f'/reviews/{run.pk}/compare/run/', follow=True)
        self.assertIn("I'm a Landlord", model.call_args_list[0].args[0]['instructions'])
        run.refresh_from_db()
        # The radio's value is the stored Korean answer; only its label is translated.
        self.assertEqual(self.leftover_korean(page.content.decode().replace('value="비슷함"', ''), run), [])
        rated = self.client.post(f'/reviews/{run.pk}/compare/rate/', {'preferred': '비슷함'}, follow=True)
        self.assertContains(rated, 'About the same')
        run.refresh_from_db()
        self.assertEqual(run.evaluation['preferred'], '비슷함')

    def test_english_turn_errors(self):
        self.client.get('/?lang=en')
        run = self.create_run(EN_ANALYSIS)
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        item = lambda stage, **extra: {**ITEMS[stage], 'citation': CITATION, **extra}
        four = {'summary': 's', 'items': [item('issues')] * 4, 'excluded': ['x']}
        with patch('server.integrations.transport.call', return_value=response(four)):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        run.refresh_from_db()
        self.assertIn('Choose at most 3 issues.', run.error)
        self.run_steps(run, 1)
        two = {'summary': 's', 'items': [item('debate', target_ids=['s1-i1'])] * 2}
        with patch('server.integrations.transport.call', return_value=response(two)):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '1'})
        run.refresh_from_db()
        self.assertIn('Write only one item per turn.', run.error)

    def test_english_error_messages(self):
        self.client.get('/?lang=en')
        self.assertContains(self.client.post('/', {'text': ' '}), 'Enter between 1 and 100,000 characters')


def news_item(news_id, title, approved, body='<p>본문&nbsp;내용</p><br><p>둘째 문단</p>', ministry='고용노동부'):
    from xml.etree.ElementTree import fromstring
    return fromstring(f'<NewsItem><NewsItemId>{news_id}</NewsItemId><ApproveDate>{approved}</ApproveDate>'
                      f'<Title><![CDATA[{title}]]></Title><SubTitle1><![CDATA[부제<br>둘째 부제]]></SubTitle1>'
                      f'<DataContents><![CDATA[{body}]]></DataContents><MinisterCode>{ministry}</MinisterCode></NewsItem>')


class LatestPolicyTests(TestCase):
    from datetime import datetime

    def setUp(self):
        ReviewFlowTests.setUp(self)
        cache.clear()

    POLICIES = [{'id': '2', 'title': '청년 월세 지원 확대', 'category': '국토교통부', 'hue': 10, 'text': TEXT,
                 'approved': datetime(2026, 11, 6, 16, 33)},
                {'id': '1', 'title': '청년 첫 취업지원제 신설', 'category': '고용노동부', 'hue': 200, 'text': '다른 본문',
                 'approved': datetime(2026, 11, 5, 9, 0)}]

    def test_walks_back_until_three_youth_titles_newest_first(self):
        from datetime import date
        from .integrations.policy_suggest import newest_youth_policies
        windows = [[news_item('1', '청년 일자리', '11/06/2026 10:00:00'), news_item('2', '단감 수출', '11/06/2026 11:00:00'),
                    news_item('3', '청년 주거', '11/07/2026 09:00:00', ministry='국토교통부')],
                   [], [news_item('4', '청년 연구', '10/30/2026 09:00:00'), news_item('5', '청년 금융', '10/31/2026 09:00:00')],
                   [news_item('6', '청년 마지막', '10/27/2026 09:00:00')]]
        with patch('server.integrations.policy_suggest.news_window', side_effect=windows) as fetch:
            policies = newest_youth_policies(today=date(2026, 11, 9))
        self.assertEqual(fetch.call_count, 3)  # Stops once three are found.
        self.assertEqual(fetch.call_args_list[1].args, (date(2026, 11, 4), date(2026, 11, 6)))
        self.assertEqual([p['id'] for p in policies], ['3', '1', '5'])
        self.assertEqual(policies[1]['category'], '고용노동부')
        self.assertEqual(policies[1]['text'], '청년 일자리\n\n부제\n둘째 부제\n\n본문\xa0내용\n\n둘째 문단')
        self.assertEqual(policies[1]['hue'], policies[2]['hue'])
        self.assertNotEqual(policies[0]['hue'], policies[1]['hue'])

    def test_home_loads_the_latest_policies_after_the_page(self):
        with patch('server.views.newest_youth_policies') as fetch:
            page = self.client.get('/')
        fetch.assert_not_called()  # A slow briefing API must not hold up the upload form.
        self.assertContains(page, 'data-latest data-url="/latest/"')
        self.assertContains(page, '<form id="latest-start" method="post" hidden')

    def test_latest_shows_sliding_cards_from_a_cached_list(self):
        with patch('server.views.newest_youth_policies', return_value=self.POLICIES) as fetch:
            page = self.client.get('/latest/')
            self.client.get('/latest/')
        self.assertEqual(fetch.call_count, 1)
        self.assertContains(page, '살펴볼 문서가 없으신가요?')
        self.assertContains(page, 'data-latest-slider')
        self.assertContains(page, '<span class="policy-meta"><span class="policy-category" style="--hue:10">국토교통부</span><small>2026.11.06</small></span>')
        self.assertContains(page, '<strong>청년 월세 지원 확대</strong>')
        # Picking a card only opens its full text; starting needs the confirm button.
        self.assertContains(page, '<div class="policy-text">다른 본문</div>')
        self.assertContains(page, '<button class="primary" form="latest-start" name="policy" value="2">')
        self.assertContains(page, 'data-dot', count=2)

    def test_picked_policy_becomes_the_reviewed_document(self):
        with patch('server.views.newest_youth_policies', return_value=self.POLICIES), \
                patch('server.integrations.transport.call', return_value=response(ANALYSIS)):
            result = self.client.post('/', {'policy': '2', 'text': '무시할 본문'})
        run = ReviewRun.objects.latest('pk')
        self.assertRedirects(result, f'/reviews/{run.pk}/', fetch_redirect_response=False)
        self.assertEqual((run.title, run.pages), ('청년 월세 지원 확대', [TEXT]))

    def test_unknown_policy_or_failed_fetch_shows_an_error(self):
        with patch('server.views.newest_youth_policies', return_value=self.POLICIES):
            page = self.client.post('/', {'policy': '99'})
        self.assertContains(page, '선택한 정책을 다시 찾지 못했습니다')
        self.assertFalse(ReviewRun.objects.exists())
        cache.clear()
        # The picker is optional: a failed or empty fetch leaves nothing on the home page, and a failure is not cached.
        with patch('server.views.newest_youth_policies', side_effect=OSError('down')):
            self.assertEqual(self.client.get('/latest/').content.strip(), b'')
        with patch('server.views.newest_youth_policies', return_value=[]):
            self.assertEqual(self.client.get('/latest/').content.strip(), b'')


class DummyModeTests(TestCase):
    def setUp(self):
        for patcher in (patch.dict('os.environ', {'POLICYLENS_DUMMY': '1'}), patch('server.integrations.dummy.DELAY', 0)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_every_screen_runs_on_dummy_data_without_a_provider(self):
        from django.core.cache import cache
        cache.clear()
        with patch('server.integrations.transport.urlopen') as network, patch('server.integrations.policy_suggest.urlopen') as briefing:
            self.assertIn('[더미]', self.client.get('/latest/').content.decode())
            self.client.post('/', {'text': TEXT + ' 지원 기한은 공고일부터 30일 이내로 한다. 세부 기준은 시행 지침으로 정한다.'})
            run = ReviewRun.objects.latest('pk')
            self.assertEqual((run.provider, run.model, len(run.analysis['roles'])), ('dummy', 'dummy-model', 3))
            self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
            for _ in range(40):
                run.refresh_from_db()
                if run.steps and run.steps[-1]['stage'] == 'final':
                    break
                self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(len(run.steps))})
            self.client.post(f'/reviews/{run.pk}/compare/run/')
            network.assert_not_called()
            briefing.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.error, '')
        self.assertEqual(run.steps[-1]['stage'], 'final')
        self.assertEqual([step['stage'] for step in run.steps].count('issue_close'), 3)
        self.assertEqual(run.notes.count(), 1)
        self.assertTrue(run.baseline_items)
        self.assertContains(self.client.get(f'/reviews/{run.pk}/?page=discussion'), '관련 낮음')
        self.assertContains(self.client.get(f'/reviews/{run.pk}/?page=review'), '더미 메모')

    def test_a_dummy_run_does_not_continue_on_a_real_provider(self):
        self.client.post('/', {'text': TEXT})
        run = ReviewRun.objects.latest('pk')
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        with patch('server.integrations.transport.dummy_mode', return_value=False), patch('server.integrations.transport.configuration', return_value=('key', 'model')):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        run.refresh_from_db()
        self.assertIn('모델 제공자 설정이 변경', run.error)
