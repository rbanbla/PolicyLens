import json
import re
import tempfile
from copy import deepcopy
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, Client
from django.utils import translation
from .models import ReviewRun, Source
from .agents.planning import is_skipped, phases_for, steps_for, turn_of
from .agents.progress import feedback_letters, plain_text
from .agents.schemas import report
from .agents.runner import MAX_TOOL_ROUNDS
from .agents.tools.documents import align_citations, check_quote
from .agents.tools.sources import new_research, read_source, search_sources
from .agents.validation import validate_report
from .integrations import transport

TEXT = '임차인은 월세를 지원받는다. 임대인은 임대차 신고에 협조한다. 지자체는 지원 대상을 따로 정할 수 있다.'
CITATION = {'page': 1, 'quote': '임차인은 월세를 지원받는다.'}


def role(name, basis='explicit'):
    return {'name': name, 'basis': basis, 'doc_role': '문서상 위치', 'gains': '얻는 것', 'burdens': '지는 부담',
            'goal': '지키려는 것', 'red_line': '양보하기 어려운 것',
            'impact': '정책의 의미', 'why_distinct': '이해가 다름', 'citation': CITATION}


ANALYSIS = {'document_type': '지원 공고', 'policy_field': '청년 주거', 'purpose': '월세 지원', 'applies_to': '청년',
            'summary': '월세 지원 정책', 'status': 'ok', 'selection_note': '수혜자·부담자·집행자',
            'other_stakeholders': [], 'roles': [role('임차인'), role('임대인', 'implied'), role('지자체')]}
TWO_ROLES = dict(ANALYSIS, roles=ANALYSIS['roles'][:2])
ITEMS = {
    'independent': {'issue': '지원 대상', 'signal': '재량 집중', 'stance': '불리', 'reason': '기준이 없다', 'request': '기준 공개', 'sources': []},
    'issues': {'issue': '지원 대상 기준', 'signal': '재량 집중', 'priority': '높음', 'reason': '결정권 집중', 'contested': '입장 차이 내용', 'question': '기준은 무엇인가?'},
    'debate': {'issue': '지원 대상 기준', 'claim_summary': '상대 주장 요약', 'response': '반박', 'reason': '상대 주장 요약과 사정', 'request': '기준 공개 요청', 'condition': '기준 공개 시 수용', 'sources': []},
    'final': {'issue': '지원 대상 기준', 'signal': '재량 집중', 'priority': '높음', 'reason': '결정 전 확인 필요', 'impact': '지원에서 빠질 수 있다', 'others_view': '지자체는 재량이 필요하다고 본다', 'check': '공고문 확인', 'question': '기준은 언제 공개되나?', 'uncertainty': '세부 기준이 문서에 없다', 'sources': []},
}


def response(data):
    return {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(data)}]}]}


def stage_of(payload):
    top = payload['text']['format']['schema']['properties']
    fields = top['items']['items']['properties']
    return 'issues' if 'excluded' in top else next(stage for stage, marker in [('independent', 'stance'), ('debate', 'response'), ('final', 'impact')] if marker in fields)


def result_for(payload):
    stage = stage_of(payload)
    item = {**ITEMS[stage], 'citation': CITATION}
    if stage != 'independent':
        item['target_ids'] = json.loads(payload['input'])['allowed_target_ids']
    result = {'summary': '검토 완료', 'items': [item]}
    if stage == 'issues':
        result['excluded'] = ['시행일은 자명해 제외했다.']
    return result


def report_response(payload, key):
    return response(result_for(payload))


class PlanTests(SimpleTestCase):
    def test_plan_is_turn_based(self):
        self.assertEqual([stage for stage, _ in steps_for(3)], ['independent'] * 9 + ['issues'] + ['debate'] * 9 + ['final'])
        self.assertEqual([role for _, role in steps_for(3)[:6]], [0, 1, 2, 0, 1, 2])
        self.assertEqual(len(steps_for(2)), 14)
        self.assertEqual(phases_for(2), {'discussion': (0, 7), 'review': (7, 13), 'proposal': (13, 14)})
        self.assertEqual(phases_for(3), {'discussion': (0, 10), 'review': (10, 19), 'proposal': (19, 20)})
        self.assertEqual([turn_of(i, 3) for i in range(9)], [0, 0, 0, 1, 1, 1, 2, 2, 2])
        self.assertEqual([turn_of(i, 3) for i in range(10, 19)], [0, 0, 0, 1, 1, 1, 2, 2, 2])

    def test_chosen_role_opens_every_debate_round(self):
        plan = steps_for(3, 1)
        self.assertEqual([role for _, role in plan[:3]], [0, 1, 2])
        self.assertEqual([role for _, role in plan[10:19]], [1, 0, 2] * 3)
        self.assertEqual([role for _, role in steps_for(2, None)[7:9]], [0, 1])

    def test_is_skipped_follows_the_steps_so_far(self):
        step = lambda stage, role, n: {'stage': stage, 'role': role, 'result': {'summary': 's', 'items': [{}] * n}}
        steps = [step('independent', 0, 1), step('independent', 1, 0), step('independent', 2, 1)]
        self.assertFalse(is_skipped(steps, 3, 3))
        self.assertTrue(is_skipped(steps, 4, 3))
        self.assertFalse(is_skipped(steps, 5, 3))
        steps = [step('independent', r, 1) for _ in range(3) for r in range(3)] + [step('issues', None, 2)]
        self.assertEqual([is_skipped(steps, 10 + i, 3) for i in range(9)], [False] * 6 + [True] * 3)
        self.assertFalse(is_skipped(steps, 9, 3))


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

    def run_steps(self, run, count, **extra):
        # `count` model calls. Skipped turns ride along, so the next cursor is whatever the server saved.
        results = []
        with patch('server.integrations.transport.call', side_effect=report_response) as model:
            for _ in range(count):
                run.refresh_from_db()
                results.append(self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(len(run.steps))}, **extra))
        return model, results

    def run_to_end(self, run, reply=report_response):
        with patch('server.integrations.transport.call', side_effect=reply) as model:
            for _ in range(50):
                run.refresh_from_db()
                if len(run.steps) == len(steps_for(len(run.analysis['roles']))):
                    break
                self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(len(run.steps))})
        return model

    def completed_run(self, analysis=ANALYSIS, selected='0'):
        run = self.create_run(analysis)
        self.client.post(f'/reviews/{run.pk}/select/', {'role': selected})
        self.run_to_end(run)
        run.refresh_from_db()
        return run

    def test_step_plan_follows_role_count(self):
        self.assertEqual([stage for stage, _ in steps_for(2)], ['independent'] * 6 + ['issues'] + ['debate'] * 6 + ['final'])
        self.assertEqual(len(steps_for(3)), 20)
        self.assertEqual(phases_for(2), {'discussion': (0, 7), 'review': (7, 13), 'proposal': (13, 14)})

    def test_roles_with_nothing_to_add_are_skipped_and_the_run_completes(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        def reply(payload, key):
            if stage_of(payload) == 'independent':
                return response({'summary': '쟁점 없음', 'items': []})
            return report_response(payload, key)
        model = self.run_to_end(run, reply)
        run.refresh_from_db()
        self.assertEqual([step.get('skipped', False) for step in run.steps[3:9]], [True] * 6)
        self.assertEqual(len(run.steps), 20)
        self.assertEqual(run.steps[-1]['stage'], 'final')
        self.assertEqual(model.call_count, 8)

    def test_skipped_turns_have_no_bubble_but_nothing_to_add_does(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        def reply(payload, key):
            if stage_of(payload) == 'independent':
                return response({'summary': '쟁점 없음', 'items': []})
            return report_response(payload, key)
        self.run_to_end(run, reply)
        page = self.client.get(f'/reviews/{run.pk}/?page=discussion')
        for number in (1, 2, 3):
            self.assertContains(page, f'id="s{number}-empty"')
        for number in range(4, 10):
            self.assertNotContains(page, f'id="s{number}-empty"')

    def test_cursor_jumps_past_skipped_turns(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        headers = {'HTTP_ACCEPT': 'application/json'}
        _, results = self.run_steps(run, 13, **headers)
        self.assertEqual(results[12].json()['cursor'], 19)
        _, last = self.run_steps(run, 1, **headers)
        self.assertTrue(last[0].json()['complete'])

    def test_failed_turn_adds_no_skipped_steps(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        self.run_steps(run, 12)
        with patch('server.integrations.transport.call', side_effect=TimeoutError('timeout')):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '12'})
        run.refresh_from_db()
        self.assertEqual(len(run.steps), 12)
        self.assertFalse(any(step.get('skipped') for step in run.steps))
        self.run_steps(run, 1)
        run.refresh_from_db()
        self.assertEqual(len(run.steps), 19)

    def test_three_roles_full_flow_and_duplicate_cursor(self):
        run = self.create_run()
        self.assertContains(self.client.get(f'/reviews/{run.pk}/'), '임차인')
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        with patch('server.integrations.transport.call', side_effect=report_response) as model:
            for _ in range(14):
                run.refresh_from_db()
                self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(len(run.steps))})
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '19'})
            self.assertEqual(model.call_count, 14)
        run.refresh_from_db()
        self.assertEqual(len(run.steps), 20)
        self.assertContains(self.client.get(f'/reviews/{run.pk}/?page=proposal'), '주의 조항 정리')

    def test_two_roles_run_fourteen_steps(self):
        run = self.completed_run(TWO_ROLES, '1')
        self.assertEqual(len(run.steps), 14)
        self.assertEqual(run.steps[-1]['stage'], 'final')
        review = self.client.get(f'/reviews/{run.pk}/?page=review')
        self.assertContains(review, 'id="s8-i1"')
        self.assertContains(review, 'id="s9-i1"')
        self.assertContains(review, 'AI · 2개의 관점')
        self.assertEqual(len(feedback_letters(run)), 2)
        self.assertEqual(self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '14'}).status_code, 302)

    def test_role_count_limits_are_enforced(self):
        for roles in (ANALYSIS['roles'][:1], ANALYSIS['roles'] + [role('시민')]):
            with self.subTest(count=len(roles)), patch('server.integrations.transport.call', return_value=response(dict(ANALYSIS, roles=roles))) as model:
                page = self.client.post('/', {'text': TEXT}, follow=True)
                self.assertEqual(model.call_count, 2)
                self.assertContains(page, '2~3명')
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

    def test_role_agents_do_not_learn_user_choice(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '2'})
        model, _ = self.run_steps(run, 14)
        run.refresh_from_db()
        sent = [json.loads(call.args[0]['input']) for call in model.call_args_list]
        plan = [entry for entry, step in zip(steps_for(3, 2), run.steps) if not step.get('skipped')]
        for (stage, acting), data in zip(plan, sent):
            with self.subTest(stage=stage, role=acting):
                self.assertNotIn('selected_role', data)
                self.assertEqual('user_role' in data, stage == 'final')
                self.assertEqual('roles' in data, acting is None)
                if acting is not None:
                    self.assertEqual(data['acting_role']['name'], ANALYSIS['roles'][acting]['name'])
        self.assertEqual(sent[-1]['user_role']['name'], '지자체')
        self.assertEqual(sent[0]['history'], [])
        self.assertEqual(sent[9]['history'][0]['speaker'], '임차인')
        self.assertEqual({step['stage'] for step in sent[-1]['history']}, {'issues', 'debate'})

    def test_independent_turn_sees_only_its_own_earlier_opinions(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        model, _ = self.run_steps(run, 5)
        sent = [json.loads(call.args[0]['input']) for call in model.call_args_list]
        self.assertEqual(sent[0]['history'], [])
        self.assertEqual([h['speaker'] for h in sent[3]['history']], ['임차인'])
        self.assertEqual([h['speaker'] for h in sent[4]['history']], ['임대인'])
        for index, data in enumerate(sent):
            self.assertLessEqual({h['role'] for h in data['history']}, {index % 3})

    def test_debate_turn_gets_one_issue_and_rounds_follow_issue_count(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        def reply(payload, key):
            if stage_of(payload) != 'issues':
                return report_response(payload, key)
            ids = json.loads(payload['input'])['allowed_target_ids']
            item = lambda number: {**ITEMS['issues'], 'issue': f'쟁점 {number}', 'citation': CITATION, 'target_ids': ids}
            return response({'summary': 's', 'items': [item(1), item(2)], 'excluded': ['x']})
        model = self.run_to_end(run, reply)
        run.refresh_from_db()
        debate = [json.loads(call.args[0]['input']) for call in model.call_args_list if stage_of(call.args[0]) == 'debate']
        self.assertEqual([len(data['assigned_claims']) for data in debate], [1] * 6)
        self.assertEqual([data['assigned_claims'][0]['issue_id'] for data in debate], ['s10-i1'] * 3 + ['s10-i2'] * 3)
        self.assertEqual([data['assigned_claims'][0]['claim_id'] for data in debate], [None, 's11-i1', 's11-i1', None, 's14-i1', 's14-i1'])
        self.assertEqual(model.call_count, 17)
        self.assertEqual(len(run.steps), 20)
        self.assertEqual([step.get('skipped', False) for step in run.steps[16:19]], [True] * 3)

    def test_one_item_per_turn_and_at_most_three_issues(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        item = lambda stage, **extra: {**ITEMS[stage], 'citation': CITATION, **extra}
        with patch('server.integrations.transport.call', return_value=response({'summary': 's', 'items': [item('independent')] * 2})) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
            self.assertEqual(model.call_count, 2)
        run.refresh_from_db()
        self.assertIn('하나만', run.error)
        self.assertEqual(len(run.steps), 0)
        self.run_steps(run, 9)
        four = {'summary': 's', 'items': [item('issues', target_ids=['s1-i1'])] * 4, 'excluded': ['x']}
        with patch('server.integrations.transport.call', return_value=response(four)):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '9'})
        run.refresh_from_db()
        self.assertIn('최대 3개', run.error)
        self.assertEqual(len(run.steps), 9)
        self.run_steps(run, 1)
        two = {'summary': 's', 'items': [item('debate', target_ids=['s10-i1', 's2-i1'])] * 2}
        with patch('server.integrations.transport.call', return_value=response(two)):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '10'})
        run.refresh_from_db()
        self.assertIn('하나만', run.error)
        self.assertEqual(len(run.steps), 10)

    def test_prompts_ask_for_one_item_at_a_time(self):
        prompts = settings.BASE_DIR / 'prompts'
        independent = (prompts / 'independent.md').read_text()
        self.assertIn('더 다룰 쟁점이 없으면', independent)
        self.assertNotIn('최대 5개', independent)
        self.assertIn('최대 3개', (prompts / 'issues.md').read_text())
        self.assertIn('쟁점 하나만', (prompts / 'debate.md').read_text())

    def test_debate_targets_exclude_own_statement_and_are_schema_enums(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        model, _ = self.run_steps(run, 11)
        payload = model.call_args_list[10].args[0]
        others = ['s2-i1', 's3-i1', 's5-i1', 's6-i1', 's8-i1', 's9-i1', 's10-i1']
        self.assertEqual(json.loads(payload['input'])['allowed_target_ids'], others)
        schema = payload['text']['format']['schema']['properties']['items']['items']['properties']['target_ids']
        self.assertEqual(schema['items']['enum'], others)
        self.assertEqual(report('issues', [])['properties']['items']['items']['properties']['target_ids']['items'], {'type': 'string'})

    def test_validation_failure_is_repaired_once_with_feedback(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        wrong = {'summary': 's', 'items': [{**ITEMS['independent'], 'citation': {'page': 1, 'quote': '문서에 없는 인용입니다'}}]}
        right = {'summary': 's', 'items': [{**ITEMS['independent'], 'citation': CITATION}]}
        with patch('server.integrations.transport.call', side_effect=[response(wrong), response(right)]) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        run.refresh_from_db()
        self.assertEqual(len(run.steps), 1)
        self.assertEqual(run.error, '')
        repair = json.loads(model.call_args_list[1].args[0]['input'])
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

    def test_independent_may_be_empty_but_later_stages_may_not(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        with patch('server.integrations.transport.call', return_value=response({'summary': '쟁점 없음', 'items': []})):
            for cursor in range(3):
                self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(cursor)})
        run.refresh_from_db()
        self.assertEqual(len(run.steps), 9)
        with patch('server.integrations.transport.call', return_value=response({'summary': '없음', 'items': [], 'excluded': []})):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '9'})
        run.refresh_from_db()
        self.assertEqual(len(run.steps), 9)
        self.assertIn('하나 이상', run.error)

    def test_debate_is_a_conversation_opened_by_the_chosen_role(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '1'})
        model, _ = self.run_steps(run, 13)
        debate = [json.loads(call.args[0]['input']) for call in model.call_args_list if stage_of(call.args[0]) == 'debate']
        self.assertEqual([data['acting_role']['name'] for data in debate], ['임대인', '임차인', '지자체'])
        self.assertEqual([data['assigned_claims'] for data in debate], [
            [{'issue_id': 's10-i1', 'claim_id': None, 'reply_id': None}],
            [{'issue_id': 's10-i1', 'claim_id': 's11-i1', 'reply_id': None}],
            [{'issue_id': 's10-i1', 'claim_id': 's11-i1', 'reply_id': 's12-i1'}]])
        self.assertEqual([[h['speaker'] for h in data['history'] if h['stage'] == 'debate'] for data in debate],
                         [[], ['임대인'], ['임대인', '임차인']])
        self.assertIn('s11-i1', debate[1]['allowed_target_ids'])
        self.assertIn('s12-i1', debate[2]['allowed_target_ids'])
        self.assertEqual(debate[0]['acting_role']['red_line'], '양보하기 어려운 것')

    def test_opening_statement_is_labelled_apart_from_replies(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '1'})
        self.run_steps(run, 13)
        page = self.client.get(f'/reviews/{run.pk}/?page=review')
        self.assertContains(page, '<strong>상대 주장</strong>', count=2)
        self.assertContains(page, '<strong>쟁점</strong>', count=1)

    def test_debate_reply_must_answer_the_opening_statement(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        self.run_steps(run, 11)
        run.refresh_from_db()
        item = {**ITEMS['debate'], 'citation': CITATION, 'target_ids': ['s10-i1']}
        with patch('server.integrations.transport.call', return_value=response({'summary': 's', 'items': [item]})):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '11'})
        run.refresh_from_db()
        self.assertEqual(len(run.steps), 11)
        self.assertIn('s11-i1', run.error)

    def test_third_speaker_must_answer_the_earlier_reply_too(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        self.run_steps(run, 12)
        item = {**ITEMS['debate'], 'citation': CITATION, 'target_ids': ['s10-i1', 's11-i1']}
        with patch('server.integrations.transport.call', return_value=response({'summary': 's', 'items': [item]})):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '12'})
        run.refresh_from_db()
        self.assertEqual(len(run.steps), 12)
        self.assertIn('s12-i1', run.error)

    def test_hanzi_slip_goes_back_for_repair(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        slip = {**ITEMS['independent'], 'citation': CITATION, 'reason': '비용을 누가承担할지 없다'}
        fixed = {**slip, 'reason': '비용을 누가 부담할지 없다'}
        with patch('server.integrations.transport.call', side_effect=[response({'summary': 's', 'items': [item]}) for item in (slip, fixed)]) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        run.refresh_from_db()
        self.assertEqual(model.call_count, 2)
        self.assertEqual(run.steps[0]['result']['items'][0]['reason'], '비용을 누가 부담할지 없다')

    def test_hanzi_from_the_document_is_allowed(self):
        pages = ['임차인은 月貰를 지원받는다.']
        item = {**ITEMS['independent'], 'reason': '月貰 기준이 없다', 'citation': {'page': 1, 'quote': '임차인은 月貰를 지원받는다.'}}
        validate_report(pages, {'summary': 's', 'items': [item]}, 'independent', [])

    def test_chat_bubble_shows_the_whole_reason_once(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        reason = '근거가 부족합니다 ' * 30
        item = {**ITEMS['independent'], 'citation': CITATION, 'reason': reason}
        with patch('server.integrations.transport.call', return_value=response({'summary': 's', 'items': [item]})):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        page = self.client.get(f'/reviews/{run.pk}/?page=discussion')
        self.assertContains(page, reason.strip(), count=1)
        self.assertIn(reason.strip(), page.content.decode().split('class="bubble"')[1].split('<details')[0])  # Readable without opening anything.

    def test_debate_must_answer_every_issue(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        self.run_steps(run, 10)
        run.refresh_from_db()
        item = {**ITEMS['debate'], 'citation': CITATION, 'target_ids': ['s2-i1']}
        with patch('server.integrations.transport.call', return_value=response({'summary': 's', 'items': [item]})):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '10'})
        run.refresh_from_db()
        self.assertEqual(len(run.steps), 10)
        self.assertIn('s10-i1', run.error)

    def test_malformed_output_is_rejected(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        good = {'summary': 's', 'items': [{**ITEMS['independent'], 'citation': CITATION}]}
        bad = [dict(good, items='invalid'), dict(good, extra='unexpected')]
        for field, value in [('signal', '기타'), ('stance', '중립')]:
            bad.append({'summary': 's', 'items': [{**good['items'][0], field: value}]})
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
        self.assertEqual(initial.json()['next_label'], '입장 살펴보기 · 임차인')
        with patch('server.integrations.transport.call', side_effect=report_response) as model:
            cursor = 0
            for _ in range(13):
                result = self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(cursor)}, **headers)
                self.assertEqual(result.status_code, 200)
                self.assertGreater(result.json()['cursor'], cursor)
                stale = self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(cursor)}, **headers)
                self.assertEqual(stale.status_code, 409)
                cursor = result.json()['cursor']
            finished = self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(cursor)}, **headers)
            self.assertTrue(finished.json()['complete'])
            self.assertEqual(model.call_count, 14)
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
        self.assertIn('지원 대상', failed.json()['steps_html'])
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
        self.assertContains(discussion, '대화에서 찾은 쟁점')
        self.assertContains(discussion, '입장 차이 내용')
        self.assertContains(discussion, '시행일은 자명해 제외했다.')
        self.assertContains(discussion, 'class="chat-message is-self" id="s2-i1"')
        self.assertContains(discussion, 'class="chat-message" id="s1-i1"')
        self.assertContains(discussion, 'id="s10-i1"')
        self.assertNotContains(discussion, 'id="s11-i1"')
        review = self.client.get(f'/reviews/{run.pk}/?page=review')
        self.assertContains(review, 'id="s11-i1"')
        self.assertNotContains(review, 'id="s1-i1"')
        proposal = self.client.get(f'/reviews/{run.pk}/?page=proposal')
        self.assertContains(proposal, 'id="s20-i1"')
        self.assertContains(proposal, '내가 확인할 것')
        self.assertContains(proposal, '법률·세무 자문이 아니니')
        self.assertNotContains(proposal, '이렇게 바꿔보세요')
        self.assertNotContains(proposal, 'id="s11-i1"')

    def test_cautions_sort_by_priority_and_only_high_opens(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        self.run_steps(run, 13)
        low, high = [{**ITEMS['final'], 'issue': name, 'priority': level, 'citation': CITATION, 'target_ids': ['s11-i1']}
                     for name, level in [('낮은 조항', '낮음'), ('높은 조항', '높음')]]
        with patch('server.integrations.transport.call', return_value=response({'summary': 's', 'items': [low, high]})):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '19'})
        run.refresh_from_db()
        self.assertEqual([item['issue'] for item in run.steps[-1]['result']['items']], ['높은 조항', '낮은 조항'])
        page = self.client.get(f'/reviews/{run.pk}/?page=proposal')
        self.assertContains(page, '<details class="source" open>', count=1)

    def test_page_three_and_four_keep_their_layout(self):
        run = self.completed_run()
        for page in ('discussion', 'review'):
            html = self.client.get(f'/reviews/{run.pk}/?page={page}')
            for marker in ('class="document-sidebar glass"', 'class="chat-room glass"', 'class="chat-header"', 'class="run-controls"'):
                self.assertContains(html, marker)

    def test_phase_boundaries_and_locked_next_page(self):
        run = self.create_run()
        self.client.post(f'/reviews/{run.pk}/select/', {'role': '0'})
        early = self.client.get(f'/reviews/{run.pk}/?page=review&start=1')
        self.assertNotContains(early, 'id="review-runner"')
        self.assertContains(early, '앞선 검토로 돌아가기')
        self.run_steps(run, 10)
        discussion = self.client.get(f'/reviews/{run.pk}/?page=discussion')
        self.assertNotContains(discussion, 'id="review-runner"')
        self.assertContains(discussion, '쟁점 토론 보기')
        self.assertContains(self.client.get(f'/reviews/{run.pk}/?page=review'), 'data-phase="review" data-end="19"')

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
        self.run_steps(run, 5)
        run.refresh_from_db()
        self.assertEqual(feedback_letters(run), [])
        self.assertEqual(self.client.get(f'/reviews/{run.pk}/feedback/0/').status_code, 404)

    def plain(self, text='단일 답변'):
        return {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}

    def test_baseline_is_the_literal_single_prompt_and_runs_once(self):
        run = self.completed_run(selected='1')
        with patch('server.integrations.transport.call', return_value=self.plain()) as model:
            self.client.post(f'/reviews/{run.pk}/compare/run/')
            self.client.post(f'/reviews/{run.pk}/compare/run/')
            self.assertEqual(model.call_count, 1)
        payload = model.call_args.args[0]
        self.assertIn('나는 임대인인데, 나한테 불리한 조항 찾아줘.', payload['instructions'])
        self.assertNotIn('text', payload)
        self.assertEqual(json.loads(payload['input'])['pages'][0]['text'], TEXT)
        run.refresh_from_db()
        self.assertEqual(run.baseline, '단일 답변')
        self.assertIn(run.evaluation['pipeline'], ('A', 'B'))

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
        with patch('server.integrations.transport.call', return_value=self.plain()):
            page = self.client.post(f'/reviews/{run.pk}/compare/run/', follow=True)
        self.assertContains(page, '단일 답변')

    def test_sides_stay_blind_until_rated_and_rating_is_final(self):
        run = self.completed_run()
        self.assertContains(self.client.get(f'/reviews/{run.pk}/?page=proposal'), '두 결과 비교하기')
        for side in 'AB':
            with self.subTest(side=side):
                run.baseline, run.evaluation = '', {}
                run.save()
                with patch('server.integrations.transport.call', return_value=self.plain()), \
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
        with patch('server.integrations.transport.call', return_value=self.plain()):
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
        run.refresh_from_db()
        return run

    def role_result(self, **source):
        item = {**ITEMS['independent'], 'citation': CITATION, 'sources': [source] if source else []}
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
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        run.refresh_from_db()
        self.assertEqual(run.error, '')
        self.assertEqual(model.call_count, 2)
        self.assertEqual(model.call_args_list[0].args[0]['tools'][0]['name'], 'search_sources')
        self.assertEqual(model.call_args_list[0].args[0]['tool_choice'], 'required')
        self.assertNotIn('tool_choice', model.call_args_list[1].args[0])
        self.assertEqual(model.call_args_list[1].args[0]['input'][-1]['type'], 'function_call_output')
        step = run.steps[0]
        self.assertEqual(step['research'], [{'tool': 'search_sources', 'input': '청년월세 중복', 'found': 1}])
        self.assertEqual(step['result']['items'][0]['sources'][0]['title'], '국토부 청년월세 공고')
        Source.objects.all().delete()
        self.assertContains(self.client.get(f'/reviews/{run.pk}/?page=discussion'), '지원 대상')

    def test_step_limit_forces_an_answer_without_more_tools(self):
        self.add_source()
        run = self.selected_run()
        replies = [self.tool_call(call_id=f'c{n}') for n in range(MAX_TOOL_ROUNDS)] + [self.role_result()]
        with patch('server.integrations.transport.call', side_effect=replies) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        run.refresh_from_db()
        self.assertEqual(run.error, '')
        self.assertEqual(model.call_count, MAX_TOOL_ROUNDS + 1)
        self.assertEqual(model.call_args.args[0]['tool_choice'], 'none')

    def test_uncited_or_unread_source_goes_to_repair_with_what_was_read(self):
        self.add_source()
        run = self.selected_run()
        bad = {**self.GOOD_SOURCE, 'quote': '문서에 없는 인용문입니다'}
        with patch('server.integrations.transport.call', side_effect=[self.tool_call(), self.role_result(**bad), self.role_result(**self.GOOD_SOURCE)]) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        run.refresh_from_db()
        self.assertEqual(run.error, '')
        repair = model.call_args.args[0]
        self.assertNotIn('tools', repair)
        self.assertEqual(json.loads(repair['input'])['server_sources'][0]['source_id'], 'seoul-rent')
        run = self.selected_run()
        with patch('server.integrations.transport.call', return_value=self.role_result(**self.GOOD_SOURCE)):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        run.refresh_from_db()
        self.assertIn('도구로 읽지 않은', run.error)

    def test_role_research_stays_private_until_issues(self):
        self.add_source()
        run = self.selected_run()
        with patch('server.integrations.transport.call', side_effect=[self.tool_call(), self.role_result(**self.GOOD_SOURCE)]):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        seen = []
        def reply(payload, key):
            seen.append(payload)
            return response(result_for({**payload, 'input': payload['input'][0]['content'] if isinstance(payload['input'], list) else payload['input']}))
        with patch('server.integrations.transport.call', side_effect=reply):
            for cursor in range(1, 10):
                self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(cursor)})
        self.assertNotIn('국토부', seen[0]['input'][0]['content'])
        self.assertNotIn('tools', seen[8])  # The moderator only weighs what the roles brought.
        self.assertIn('국토부', seen[8]['input'])
        self.assertNotIn('"research"', seen[8]['input'])

    def test_debate_searches_only_when_the_model_asks(self):
        self.add_source()
        run = self.selected_run()
        self.run_steps_with_tools(run, 10)
        seen = []
        def reply(payload, key):
            seen.append(payload)
            return response(result_for({**payload, 'input': payload['input'][0]['content']}))
        with patch('server.integrations.transport.call', side_effect=reply):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '10'})
        self.assertIn('tools', seen[0])
        self.assertNotIn('tool_choice', seen[0])

    def test_only_a_roles_first_turn_must_search(self):
        self.add_source()
        run = self.selected_run()
        self.run_steps_with_tools(run, 3)
        seen = []
        def reply(payload, key):
            seen.append(payload)
            return response(result_for({**payload, 'input': payload['input'][0]['content']}))
        with patch('server.integrations.transport.call', side_effect=reply):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '3'})
        self.assertIn('tools', seen[0])
        self.assertNotIn('tool_choice', seen[0])

    def run_steps_with_tools(self, run, count):
        def reply(payload, key):
            if isinstance(payload['input'], list):
                payload = {**payload, 'input': payload['input'][0]['content']}
            return response(result_for(payload))
        with patch('server.integrations.transport.call', side_effect=reply):
            for _ in range(count):
                run.refresh_from_db()
                self.client.post(f'/reviews/{run.pk}/step/', {'cursor': str(len(run.steps))})

    def test_empty_server_data_and_old_runs_stay_on_the_document(self):
        run = self.selected_run()
        with patch('server.integrations.transport.call', return_value=self.role_result()) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        self.assertNotIn('tools', model.call_args.args[0])
        self.assertIsInstance(model.call_args.args[0]['input'], str)
        self.add_source()
        run = self.selected_run()
        run.prompts.pop('sources')
        run.save()
        with patch('server.integrations.transport.call', return_value=self.role_result()) as model:
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        self.assertNotIn('tools', model.call_args.args[0])

    def test_final_card_and_letter_show_server_evidence(self):
        run = self.completed_run()
        source = {**self.GOOD_SOURCE, 'title': '국토부 청년월세 공고', 'version': '2026년 1회차', 'issuer': '국토교통부', 'kind': '정책', 'source_url': 'https://example.go.kr/1'}
        for stage in (-1, 12):
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

    def test_each_call_is_logged_even_when_it_fails(self):
        run = self.selected_run()
        ok = dict(self.role_result(), usage={'total_tokens': 123})
        with patch('server.integrations.transport.call', return_value=ok):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        with patch('server.integrations.transport.call', side_effect=TimeoutError('timeout')):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '1'})
        run.refresh_from_db()
        self.assertEqual(run.calls[-3]['tokens'], 123)
        self.assertEqual([call['error'] for call in run.calls[-2:]], ['TimeoutError', 'TimeoutError'])

    def test_one_stalled_call_is_retried_without_stopping_the_step(self):
        run = self.selected_run()
        with patch('server.integrations.transport.call', side_effect=[TimeoutError('stall'), self.role_result()]) as model:
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
            (reviewed / 'runs' / 'doc-sources.json').write_text(json.dumps(run, ensure_ascii=False))
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
            (base / 'reviewed' / 'documents.jsonl').write_text(json.dumps({'doc_id': 'doc', 'title': '월세', 'published_on': '2026-04-30'}))
            prompts = Path(__file__).resolve().parent.parent / 'prompts'
            (Path(folder) / 'prompts').symlink_to(prompts)
            before = ReviewRun.objects.count()
            def reply(payload, key):
                if 'text' not in payload:
                    return {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '기준선'}]}]}
                return response(ANALYSIS) if 'roles' in payload['text']['format']['schema']['properties'] else response(result_for(payload))
            with patch('server.integrations.transport.call', side_effect=reply):
                call_command('evaluate', 'doc', '--no-sources', stdout=StringIO())
            saved = json.loads((base / 'reviewed' / 'runs' / 'doc-document.json').read_text())
        self.assertEqual(saved['as_of'], '2026-04-30')
        self.assertEqual(saved['baseline'], '기준선')
        self.assertEqual(len(saved['steps']), 20)
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
    run_to_end = ReviewFlowTests.run_to_end

    def english_run(self, **extra):
        self.client.get('/?lang=en')
        return self.completed_run(EN_ANALYSIS, **extra)

    def leftover_korean(self, html, run):
        for text in sorted(strings([run.title, run.pages, run.analysis, run.steps, run.baseline, run.evaluation]), key=len, reverse=True):
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
        english = (settings.BASE_DIR / 'prompts' / 'lang_en.md').read_text().strip()
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
        self.assertEqual(state['next_label'], 'Reading each position · Tenant')
        self.run_to_end(run)
        run.refresh_from_db()
        with translation.override('en'):
            from .agents.progress import feedback_letters
            letter = feedback_letters(run)[1]['text']
        self.assertIn('Request: 기준 공개 요청', letter)
        self.assertIn('not the opinion of an actual party', letter)

    def test_english_run_compares_with_the_english_single_prompt(self):
        run = self.english_run(selected='1')
        with patch('server.integrations.transport.call', return_value=self.plain('Single answer')) as model:
            page = self.client.post(f'/reviews/{run.pk}/compare/run/', follow=True)
        self.assertIn("I'm a Landlord", model.call_args.args[0]['instructions'])
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
        with patch('server.integrations.transport.call', return_value=response({'summary': 's', 'items': [item('independent')] * 2})):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '0'})
        run.refresh_from_db()
        self.assertIn('Write only one item per turn.', run.error)
        self.run_steps(run, 9)
        four = {'summary': 's', 'items': [item('issues', target_ids=['s1-i1'])] * 4, 'excluded': ['x']}
        with patch('server.integrations.transport.call', return_value=response(four)):
            self.client.post(f'/reviews/{run.pk}/step/', {'cursor': '9'})
        run.refresh_from_db()
        self.assertIn('Choose at most 3 issues.', run.error)

    def test_english_error_messages(self):
        self.client.get('/?lang=en')
        self.assertContains(self.client.post('/', {'text': ' '}), 'Enter between 1 and 100,000 characters')
