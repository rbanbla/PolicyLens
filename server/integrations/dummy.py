"""Canned model replies for UI work. With POLICYLENS_DUMMY=1 every screen runs without a provider or its cost.

Replies quote the uploaded document so they pass the same server checks as real ones, and they show each
piece of the debate screens once: a low-relevance mark, a moderator note, an issue the moderator closes.
"""
import datetime
import json
import re
import time
import zlib

DELAY = 0.8  # Seconds per call, so typing indicators and message animations show as they would.
ROLES = [('정책 수혜자', 'explicit', ['서울', '혼자 거주']), ('집행 기관', 'explicit', ['행정 사무원']), ('비용 부담자', 'implied', ['경영자'])]
SIGNALS = ['모호성', '재량 집중', '부담 전가']
PRIORITIES = ['높음', '중간', '낮음']
RESPONSES = ['반박', '제한', '수용']
BASELINE = """## 더미 답변

이 답변은 UI 확인용 더미 데이터예요.

1. **지원 대상 기준** 문서에 세부 기준이 없어 신청 전에 확인이 필요해요.
2. **신청 기한** 기한을 놓치면 다음 회차까지 기다려야 할 수 있어요."""


def quotes(pages, count):
    # Sentences cut straight from the pages, so citations match the document the checks compare against.
    found = []
    for number, text in enumerate(pages, 1):
        for match in re.finditer(r'[^.!?\n]{12,120}[.!?]?', text):
            sentence = match.group().strip()
            if len(sentence.replace(' ', '')) >= 8:
                found.append({'page': number, 'quote': sentence})
    found = found or [{'page': 1, 'quote': pages[0].strip()[:40]}]
    return [dict(found[index % len(found)]) for index in range(count)]


def pages_of(data):
    return [page['text'] for page in data['pages']]


def message(output):
    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
    return {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}],
            'usage': {'total_tokens': 0, 'input_tokens': 0, 'output_tokens': 0}}


def analysis(data):
    cites = quotes(pages_of(data), len(ROLES))
    roles = [{'name': name, 'basis': basis, 'doc_role': f'문서에서 {name}의 자리예요.',
              'gains': f'{name} 쪽이 이 정책으로 얻는 혜택이에요.', 'burdens': f'{name} 쪽이 새로 지는 부담이에요.',
              'goal': f'{name} 쪽이 지원 금액과 기한을 예측할 수 있게 하는 것이에요.',
              'red_line': f'{name}에게 알리지 않고 기준을 바꾸는 것은 받아들이기 어려워요.',
              'impact': f'{"추론: " if basis == "implied" else ""}{name}의 일정과 비용이 이 조항에 따라 달라져요.',
              'why_distinct': f'{name} 쪽은 같은 조항에서 다른 것을 얻고 잃어요.', 'citation': cites[index],
              'persona_hint': {'age_min': 19, 'age_max': 39, 'keywords': keywords}}
             for index, (name, basis, keywords) in enumerate(ROLES)]
    return {'document_type': '정책 안내문', 'policy_field': '청년', 'purpose': '더미 데이터: 정책의 목적 요약이에요.',
            'applies_to': '청년과 관련 기관', 'summary': '더미 데이터예요. 실제 모델이 아니라 화면 확인용으로 만든 요약이에요.',
            'status': 'ok', 'selection_note': '더미 데이터: 수혜자, 집행자, 부담자를 골랐어요.', 'other_stakeholders': ['지역 주민'], 'roles': roles}


def issues(data):
    roles = data['roles']
    cites = quotes(pages_of(data), 3)
    items = []
    for number in range(3):
        low = [roles[-1]['index']] if number == 2 and len(roles) == 3 else []  # One mark so the tag shows.
        items.append({'issue': f'더미 쟁점 {number + 1}: 기준이 문서에 비어 있어요', 'signal': SIGNALS[number], 'priority': PRIORITIES[number],
                      'reason': '조항이 기준을 정하지 않아요. 누가 정하느냐에 따라 결과가 달라져요.',
                      'contested': '수혜자는 넓게 읽고, 집행 기관은 좁게 읽어요. 좁게 읽으면 수혜자가 빠질 수 있어요.',
                      'question': '세부 기준은 언제 누가 정하나요?', 'low_relevance': low, 'citation': cites[number],
                      'positions': [{'role': role['index'], 'stance': f'이 조항은 {role["name"]}의 목표에 직접 닿지 않아요.' if role['index'] in low
                                     else f'{role["name"]} 입장에서 이 문구를 제게 맞게 읽어 주길 요구해요.'} for role in roles]})
    return {'summary': '더미 데이터: 쟁점 세 개를 골랐어요.', 'items': items, 'excluded': ['시행일 조항은 자명해서 제외했어요.']}


def moderator(payload, data):
    body = payload['input']
    followup = isinstance(body, list) and any(item.get('type') == 'function_call_output' for item in body)
    if payload.get('tools') and not followup and not data['noted_issues']:
        # The first moderator call notes one clause, so the notes section has something to show.
        cite = quotes(pages_of(data), 4)[3]
        arguments = {'issue': '더미 메모: 토론 중 새로 부딪힌 조항', 'reason': '앞선 발언이 이 조항과 함께 읽혀요.', **cite}
        return {'status': 'completed', 'output': [{'type': 'function_call', 'call_id': 'dummy-note', 'name': 'note_issue', 'arguments': json.dumps(arguments, ensure_ascii=False)}]}
    issue = next(item for item in data['issues'] if item['id'] == data['current_issue_id'])
    relevant = [role['index'] for role in data['roles'] if role['index'] not in issue.get('low_relevance', [])]
    said = sum(1 for step in data['history'] if step['stage'] == 'debate' and step['moderator']['next'][0]['issue_id'] == issue['id'])
    if said >= 3 and set(relevant) <= set(data['spoken_roles']):
        return message({'summary': '더미 데이터: 새 의견이 더 나오지 않아 이 쟁점을 닫아요.', 'close': True, 'speaker': -1,
                        'question': '같은 주장이 되풀이돼 닫아요.', 'shifted_by': 'none'})
    others = [role for role in relevant if role != data['last_speaker']]
    speaker = next((role for role in others if role not in data['spoken_roles']), others[0])
    name = next(role['name'] for role in data['roles'] if role['index'] == speaker)
    return message({'summary': '더미 데이터: 입장 차이를 좁히는 중이에요.', 'close': False, 'speaker': speaker,
                    'question': f'{name} 쪽은 앞 발언을 받아들이면 무엇을 잃나요?', 'shifted_by': 'none'})


def debate(data):
    name = data['acting_role']['name']
    claim = data['assigned_claims'][0]
    item = {'issue': f'{name}에게 불리한 읽기가 남아 있습니다', 'claim_summary': '앞 발언은 기준을 좁게 정하자는 주장입니다.',
            'response': RESPONSES[len(data['history']) % 3], 'stake': f'{name} 쪽이 지원 기한을 예측하는 것',
            'reason': f'더미 데이터입니다. 이 문구를 좁게 읽으면 {name} 쪽이 일정과 비용을 다시 짜야 합니다.',
            'request': f'{name}에게 적용될 기준을 시행 전에 알려 주십시오.',
            'condition': '기준이 미리 알려지면 받아들일 수 있고, 바뀐 뒤에 알리면 받아들일 수 없습니다.',
            'citation': quotes(pages_of(data), 1)[0], 'target_ids': [target for target in claim.values() if target], 'sources': []}
    return {'summary': '더미 발언', 'items': [item]}


def final(data, schema):
    others = schema['items']['items']['properties']['other_role']['enum']
    targets = data['allowed_target_ids'][:1]
    items = []
    for number, cite in enumerate(quotes(pages_of(data), 3)):
        items.append({'issue': f'더미 주의 조항 {number + 1}: 기준이 비어 있어요', 'signal': SIGNALS[number], 'priority': PRIORITIES[number],
                      'reason': '더미 데이터예요. 문서가 세부 기준을 정하지 않아 담당 기관의 판단에 따라 결과가 달라질 수 있어요.',
                      'impact': '기준이 좁게 정해지면 지원에서 빠질 수 있어요.', 'phrase': cite['quote'][:12].strip(),
                      'my_reading': '이 표현은 넓은 범위를 뜻해요. 그러면 지원 대상이 돼요.', 'other_role': others[number % len(others)],
                      'other_reading': '이 표현은 좁은 범위를 뜻해요. 그러면 지원에서 빠질 수 있어요.',
                      'check': '공고문에서 세부 기준과 기한을 확인하세요.', 'question': '세부 기준은 언제 공개되나요?',
                      'uncertainty': '세부 기준이 문서에 없어요.', 'citation': cite, 'target_ids': targets, 'sources': []})
    return {'summary': '더미 데이터: 주의 조항을 정리했어요.', 'items': items}


def formatted():
    blank = {'phrase': '', 'my_reading': '', 'other_role': '', 'other_reading': '', 'check': '', 'question': '', 'uncertainty': ''}
    return {'items': [{'issue': '지원 대상 기준', 'reason': '문서에 세부 기준이 없어요.', 'page': 0, 'quote': '', 'impact': '신청 전에 확인이 필요해요.', **blank},
                      {'issue': '신청 기한', 'reason': '기한을 놓치면 다음 회차를 기다려야 해요.', 'page': 0, 'quote': '', 'impact': '지원이 늦어질 수 있어요.', **blank}]}


def respond(payload):
    time.sleep(DELAY)
    if 'text' not in payload:
        return message(BASELINE)  # The single-prompt comparison arm asks for plain text.
    schema = payload['text']['format']['schema']['properties']
    body = payload['input']
    data = json.loads(body[0]['content'] if isinstance(body, list) else body)
    if 'roles' in schema:
        return message(analysis(data))
    if 'speaker' in schema:
        return moderator(payload, data)
    if payload['text']['format']['name'] == 'baseline_items':
        return message(formatted())
    if 'excluded' in schema:
        return message(issues(data))
    if 'response' in schema['items']['items']['properties']:
        return message(debate(data))
    return message(final(data, schema))


def latest_policies():
    now = datetime.datetime.now().replace(microsecond=0)
    policies = [('청년 월세 지원 대상 확대', '국토교통부'), ('청년 일자리 첫걸음 지원', '고용노동부'), ('청년 마음건강 바우처', '보건복지부')]
    return [{'id': f'dummy-{number}', 'title': f'[더미] {title}', 'category': ministry, 'hue': zlib.crc32(ministry.encode()) % 360,
             'approved': now - datetime.timedelta(days=number),
             'text': f'[더미] {title}\n\n화면 확인용 더미 정책이에요. 지원 대상은 만 19세에서 34세 청년이며, 신청은 온라인으로 받아요. 세부 기준은 공고문에서 확인하세요.'}
            for number, (title, ministry) in enumerate(policies)]
