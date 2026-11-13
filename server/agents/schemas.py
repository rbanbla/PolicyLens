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
SOURCE_STAGES = ('debate', 'final')
# Stored and validated in Korean; the screen translates them (gettext_noop only tells makemessages to collect them).
SIGNAL = enum(gettext_noop('이해 충돌'), gettext_noop('모호성'), gettext_noop('재량 집중'), gettext_noop('경계·배제'), gettext_noop('부담 전가'), gettext_noop('누락'))
PRIORITY_ORDER = (gettext_noop('높음'), gettext_noop('중간'), gettext_noop('낮음'))
PRIORITY = enum(*PRIORITY_ORDER)
ANALYSIS = obj({
    'document_type': TEXT, 'policy_field': TEXT, 'purpose': TEXT, 'applies_to': TEXT, 'summary': TEXT,
    'status': enum('ok', 'insufficient'), 'selection_note': TEXT, 'other_stakeholders': array(TEXT),
    'roles': array(obj({'name': TEXT, 'basis': enum('explicit', 'implied'), 'doc_role': TEXT, 'gains': TEXT,
                        'burdens': TEXT, 'goal': TEXT, 'red_line': TEXT, 'impact': TEXT, 'why_distinct': TEXT, 'citation': CITATION,
                        'persona_hint': obj({'age_min': {'type': 'integer'}, 'age_max': {'type': 'integer'}, 'keywords': array(TEXT)})})),
})
ITEM_FIELDS = {
    # low_relevance: role indices this clause barely touches; they get no turn on the issue.
    'issues': {'issue': TEXT, 'signal': SIGNAL, 'priority': PRIORITY, 'reason': TEXT, 'contested': TEXT, 'question': TEXT, 'low_relevance': array({'type': 'integer'})},
    # stake: the speaker's own goal or red_line this statement defends.
    'debate': {'issue': TEXT, 'claim_summary': TEXT, 'response': enum(gettext_noop('수용'), gettext_noop('제한'), gettext_noop('반박')), 'stake': TEXT, 'reason': TEXT, 'request': TEXT, 'condition': TEXT},
    'final': {'issue': TEXT, 'signal': SIGNAL, 'priority': PRIORITY, 'reason': TEXT, 'impact': TEXT,
              'phrase': TEXT, 'my_reading': TEXT, 'other_role': TEXT, 'other_reading': TEXT, 'check': TEXT, 'question': TEXT, 'uncertainty': TEXT},
}


# The single-prompt answer copied into the same fields as the final step. Empty strings mark what the answer did not say.
BASELINE_ITEMS = obj({'items': array(obj({'issue': TEXT, 'reason': TEXT, 'page': {'type': 'integer'}, 'quote': TEXT, 'impact': TEXT,
                                          'phrase': TEXT, 'my_reading': TEXT, 'other_role': TEXT, 'other_reading': TEXT, 'check': TEXT, 'question': TEXT,
                                          'uncertainty': TEXT}))})


def report(stage, targets, others=()):
    fields = {**ITEM_FIELDS[stage], 'citation': CITATION}
    if stage == 'final':
        fields['other_role'] = enum(*others)  # Another role's name, never the user's own.
    if stage == 'issues':
        fields['positions'] = array(obj({'role': {'type': 'integer'}, 'stance': TEXT}))  # Each role's one-line opening position.
    else:
        fields['target_ids'] = array(enum(*targets) if targets else TEXT)
    if stage in SOURCE_STAGES:
        fields['sources'] = array(SOURCE)
    top = {'summary': TEXT, 'items': array(obj(fields))}
    if stage == 'issues':
        top['excluded'] = array(TEXT)
    return obj(top)


def moderator(statements=()):
    # Within the issue the server picked, the moderator closes it or names the next speaker; new issues go to the note tool.
    # shifted_by: the statement on this issue that moves a cost onto a low-relevance role, which is the only way to call that role.
    return obj({'summary': TEXT, 'close': {'type': 'boolean'}, 'speaker': {'type': 'integer'}, 'question': TEXT,
                'shifted_by': enum('none', *statements)})
