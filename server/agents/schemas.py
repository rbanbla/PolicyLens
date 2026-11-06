from django.utils.translation import gettext_noop


def obj(fields):
    return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}
def array(item):
    return {'type': 'array', 'items': item}
def enum(*values):
    return {'type': 'string', 'enum': list(values)}
TEXT = {'type': 'string'}
CITATION = obj({'page': {'type': 'integer'}, 'quote': TEXT})
SOURCE = obj({'source_id': TEXT, 'page': {'type': 'integer'}, 'quote': TEXT, 'finding': TEXT})
SOURCE_STAGES = ('independent', 'debate', 'final')
# Stored and validated in Korean; the screen translates them (gettext_noop only tells makemessages to collect them).
SIGNAL = enum(gettext_noop('이해 충돌'), gettext_noop('모호성'), gettext_noop('재량 집중'), gettext_noop('경계·배제'), gettext_noop('부담 전가'), gettext_noop('누락'))
PRIORITY_ORDER = (gettext_noop('높음'), gettext_noop('중간'), gettext_noop('낮음'))
PRIORITY = enum(*PRIORITY_ORDER)
ANALYSIS = obj({
    'document_type': TEXT, 'policy_field': TEXT, 'purpose': TEXT, 'applies_to': TEXT, 'summary': TEXT,
    'status': enum('ok', 'insufficient'), 'selection_note': TEXT, 'other_stakeholders': array(TEXT),
    'roles': array(obj({'name': TEXT, 'basis': enum('explicit', 'implied'), 'doc_role': TEXT, 'gains': TEXT,
                        'burdens': TEXT, 'goal': TEXT, 'red_line': TEXT, 'impact': TEXT, 'why_distinct': TEXT, 'citation': CITATION})),
})
ITEM_FIELDS = {
    'independent': {'issue': TEXT, 'signal': SIGNAL, 'stance': enum(gettext_noop('유리'), gettext_noop('불리'), gettext_noop('불분명')), 'reason': TEXT, 'request': TEXT},
    'issues': {'issue': TEXT, 'signal': SIGNAL, 'priority': PRIORITY, 'reason': TEXT, 'contested': TEXT, 'question': TEXT},
    'debate': {'issue': TEXT, 'claim_summary': TEXT, 'response': enum(gettext_noop('수용'), gettext_noop('제한'), gettext_noop('반박')), 'reason': TEXT, 'request': TEXT, 'condition': TEXT},
    'final': {'issue': TEXT, 'signal': SIGNAL, 'priority': PRIORITY, 'reason': TEXT, 'impact': TEXT,
              'others_view': TEXT, 'check': TEXT, 'question': TEXT, 'uncertainty': TEXT},
}


def report(stage, targets):
    fields = {**ITEM_FIELDS[stage], 'citation': CITATION}
    if stage != 'independent':
        fields['target_ids'] = array(enum(*targets) if targets else TEXT)
    if stage in SOURCE_STAGES:
        fields['sources'] = array(SOURCE)
    top = {'summary': TEXT, 'items': array(obj(fields))}
    if stage == 'issues':
        top['excluded'] = array(TEXT)
    return obj(top)
