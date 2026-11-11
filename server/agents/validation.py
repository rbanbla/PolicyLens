import re
from django.utils.translation import gettext as _
from .planning import MAX_ISSUES, MAX_NEW_ISSUES
from .tools.documents import check_quote, clean

HANZI = re.compile(r'[\u3400-\u9fff\uf900-\ufaff]')
PERSON = re.compile(r'[가-힣]{2,4} 씨')  # "서준수 씨": a person's name, which the user must never see.


def validate_shape(value, schema):
    kind = schema['type']
    types = {'object': dict, 'array': list, 'string': str, 'integer': int}
    if type(value) is not types[kind]:
        raise ValueError(_('응답 필드의 자료형이 잘못되었습니다.'))
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(_('응답의 상태 값이 허용된 범위를 벗어났습니다.'))
    if kind == 'object':
        if set(value) != set(schema['properties']):
            raise ValueError(_('응답의 필수 필드 또는 허용 필드를 확인하세요.'))
        for key, field in schema['properties'].items():
            validate_shape(value[key], field)
    elif kind == 'array':
        for item in value:
            validate_shape(item, schema['items'])
    elif kind == 'string' and not value.strip():
        raise ValueError(_('응답에 빈 필드가 있습니다. 해당 사항이 없으면 그 이유를 적어 주세요.'))


def validate_ids(ids, allowed, message):
    if len(ids) != len(set(ids)) or not set(ids) <= set(allowed):
        raise ValueError(message)


def validate_roles(pages, analysis):
    if analysis['status'] == 'insufficient':
        return
    roles = analysis['roles']
    names = {role['name'].strip().casefold() for role in roles}
    if not 2 <= len(roles) <= 3 or len(names) != len(roles):
        raise ValueError(_('이해가 서로 다른 역할을 2~3명 반환해야 합니다.'))
    for role in roles:
        if len(role['name']) > 100 or len(role['impact']) > 2000:
            raise ValueError(_('역할 이름은 100자, 설명은 2000자 이내로 작성하세요.'))
        if not 0 <= role['persona_hint']['age_min'] <= role['persona_hint']['age_max'] <= 120:
            raise ValueError(_('persona_hint의 나이 범위가 잘못되었습니다.'))
        check_quote(pages, role['citation'])


def check_text(pages, result):
    # Only plain text fields count, so quotes stay verbatim, and what the document itself says is allowed.
    text = ' '.join([result['summary']] + [value for item in result['items'] for value in item.values() if isinstance(value, str)]
                    + [position['stance'] for item in result['items'] for position in item.get('positions', [])])
    source = ' '.join(pages)
    if set(HANZI.findall(text)) - set(HANZI.findall(source)):
        raise ValueError(_('인용을 뺀 문장에는 한자를 쓰지 말고 한글로 다시 쓰세요.'))
    if set(PERSON.findall(text)) - set(PERSON.findall(source)):
        raise ValueError(_('사람 이름(○○ 씨)이나 특정 인물을 예로 들지 말고 역할 이름으로 다시 쓰세요.'))


def validate_report(pages, result, stage, targets):
    check_text(pages, result)
    items = result['items']
    if not items:
        raise ValueError(_('이 단계에는 항목이 하나 이상 필요합니다.'))
    if stage == 'debate' and len(items) > 1:
        raise ValueError(_('한 차례에는 항목을 하나만 작성하세요.'))
    if stage == 'issues' and len(items) > MAX_ISSUES:
        raise ValueError(_('쟁점은 최대 %(n)s개까지 고르세요.') % {'n': MAX_ISSUES})
    for item in items:
        check_quote(pages, item['citation'])
        references = item.get('target_ids', [])
        validate_ids(references, targets, _('현재 단계에서 참조할 수 없는 발언 ID가 있습니다.'))
        if targets and not references:
            raise ValueError(_('검토한 이전 발언 ID를 연결하세요.'))


def validate_moderator(pages, output, count, last, issue_total):
    check_text(pages, {'summary': output['summary'], 'items': [{'question': output['question']}] + output['new_issues']})
    speaker = output['speaker']
    if not 0 <= speaker < count or speaker == last:
        raise ValueError(_('다음 발언자는 직전 발언자가 아닌 역할 번호(0부터 %(n)s)여야 합니다.') % {'n': count - 1})
    if issue_total + len(output['new_issues']) > MAX_ISSUES + MAX_NEW_ISSUES:
        raise ValueError(_('쟁점은 모두 %(n)s개까지만 둘 수 있습니다.') % {'n': MAX_ISSUES + MAX_NEW_ISSUES})
    for item in output['new_issues']:
        check_quote(pages, item['citation'])


def validate_positions(result, count):
    for item in result['items']:
        if sorted(position['role'] for position in item['positions']) != list(range(count)):
            raise ValueError(_('쟁점마다 모든 역할(0부터 %(n)s)의 입장을 한 줄씩, 역할마다 하나만 쓰세요.') % {'n': count - 1})


def validate_phrases(result):
    # The disputed words must be the clause's own words, so both readings are about the same text.
    for item in result['items']:
        if clean(item['phrase']) not in clean(item['citation']['quote']):
            raise ValueError(_('phrase는 citation.quote 안에 있는 표현을 그대로 옮기세요: "%(phrase)s"') % {'phrase': item['phrase'][:40]})
