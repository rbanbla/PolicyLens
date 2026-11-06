import re
from django.utils.translation import gettext as _
from .planning import TURNS
from .tools.documents import check_quote

HANZI = re.compile(r'[\u3400-\u9fff\uf900-\ufaff]')


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
        check_quote(pages, role['citation'])


def check_hanzi(pages, result):
    # The model sometimes slips Chinese into a Korean sentence. Only plain text fields count, so quotes stay verbatim.
    text = [result['summary']] + [value for item in result['items'] for value in item.values() if isinstance(value, str)]
    if set(HANZI.findall(' '.join(text))) - set(HANZI.findall(' '.join(pages))):
        raise ValueError(_('인용을 뺀 문장에는 한자를 쓰지 말고 한글로 다시 쓰세요.'))


def validate_report(pages, result, stage, targets, required=()):
    check_hanzi(pages, result)
    items = result['items']
    if stage != 'independent' and not items:
        raise ValueError(_('이 단계에는 항목이 하나 이상 필요합니다.'))
    if stage in ('independent', 'debate') and len(items) > 1:
        raise ValueError(_('한 차례에는 항목을 하나만 작성하세요.'))
    if stage == 'issues' and len(items) > TURNS:
        raise ValueError(_('쟁점은 최대 %(n)s개까지 고르세요.') % {'n': TURNS})
    for item in items:
        check_quote(pages, item['citation'])
        references = item.get('target_ids', [])
        validate_ids(references, targets, _('현재 단계에서 참조할 수 없는 발언 ID가 있습니다.'))
        if targets and stage != 'independent' and not references:
            raise ValueError(_('검토한 이전 발언 ID를 연결하세요.'))
    covered = {target for item in items for target in item.get('target_ids', [])}
    if not set(required) <= covered:
        raise ValueError(_('배정된 쟁점과 상대 주장 모두에 답해야 합니다: ') + ', '.join(sorted(set(required) - covered)))
