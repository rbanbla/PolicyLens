import re

from django.utils.translation import gettext as _, gettext_noop

from .memory.context import numbered_steps
from .planning import phase_of, role_count, steps_for

LABELS = {'independent': gettext_noop('입장 살펴보기'), 'issues': gettext_noop('쟁점 정리'), 'debate': gettext_noop('쟁점 토론'), 'final': gettext_noop('주의 조항 정리')}


def step_label(run, stage, role):
    label = _(LABELS[stage])
    if role is not None:
        label += ' · ' + run.analysis['roles'][role]['name']
    return label


def speaker_name(run, role):
    return run.analysis['roles'][role]['name'] if role is not None else 'PolicyLens'


def issue_result(steps):
    return next((step['result'] for step in steps if step['stage'] == 'issues'), {})


def is_complete(run):
    return len(run.steps) == len(steps_for(role_count(run)))


def display_steps(run):
    count = role_count(run)
    steps = numbered_steps(run.steps)
    for index, step in enumerate(steps):
        role, stage = step['role'], step['stage']
        step.update(label=step_label(run, stage, role), number=index + 1,
                    speaker=speaker_name(run, role),
                    is_self=role is not None and role == run.selected_role,
                    phase=phase_of(index, count))
        for item in step['result']['items']:
            item['references'] = [{'id': target, 'page': phase_of(int(target.split('-')[0][1:]) - 1, count)}
                                  for target in item.get('target_ids', [])]
    return steps


def progress(run):
    plan = steps_for(role_count(run), run.selected_role)
    cursor = len(run.steps)
    complete = cursor == len(plan)
    next_label, next_name, next_role = '', '', None
    if not complete and run.selected_role is not None:
        next_stage, next_role = plan[cursor]
        next_label = step_label(run, next_stage, next_role)
        next_name = speaker_name(run, next_role)
    return {'cursor': cursor, 'complete': complete,
            'next_label': next_label, 'next_name': next_name,
            'next_is_self': next_role is not None and next_role == run.selected_role,
            'error': run.error}


def source_lines(item):
    return [_('참고 자료: %(title)s (%(version)s, %(page)s쪽) %(finding)s "%(quote)s"') % source
            for source in item.get('sources', [])]


def research_log(run):
    return [{'label': step_label(run, step['stage'], step['role']), **entry}
            for step in run.steps for entry in step.get('research', [])]


def feedback_letters(run):
    # Assembled from stored debate fields so each letter costs no extra model call.
    if not is_complete(run):
        return []
    letters = []
    for index, role in enumerate(run.analysis['roles']):
        lines = [_('정책 의견서: %(title)s') % {'title': run.title}, _('작성 입장: %(name)s') % {'name': role['name']},
                 _('AI가 문서를 바탕으로 작성한 역할 검토 초안이며 실제 당사자의 의견이 아닙니다. 제출 전 확인하고 수정하세요. 쪽 번호는 파일의 쪽 순서입니다.'), '']
        items = [item for step in run.steps if step['stage'] == 'debate' and step['role'] == index
                 for item in step['result']['items']]
        for number, item in enumerate(items, 1):
            lines += [f'{number}. {item["issue"]}', _('입장: %(text)s') % {'text': _(item['response'])}, _('의견: %(text)s') % {'text': item['reason']},
                      _('요청: %(text)s') % {'text': item['request']}, _('근거(%(page)s쪽): %(quote)s') % item['citation']]
            lines += source_lines(item) + ['']
        letters.append({'index': index, 'name': role['name'], 'text': '\n'.join(lines)})
    return letters


def plain_text(text):
    # Raw markdown marks would reveal which side of the blind comparison is the single prompt.
    text = re.sub(r'(?m)^\s*\|?[\s:|-]*-{3,}[\s:|-]*\n?', '', text)
    text = re.sub(r'(?m)^(#+|>)\s*', '', text).replace('**', '').replace('`', '')
    text = re.sub(r'(?m)^\|\s*|\s*\|\s*$', '', text).replace(' | ', ' / ')
    return re.sub(r'\n{3,}', '\n\n', text)


def pipeline_text(run):
    # Plain text, like the baseline, so card styling does not reveal which result is which.
    lines = []
    for number, item in enumerate(run.steps[-1]['result']['items'], 1):
        lines += [f'{number}. {item["issue"]}', item['reason'], _('원문(%(page)s쪽): %(quote)s') % item['citation'],
                  _('영향: %(text)s') % {'text': item['impact']}, _('다른 입장: %(text)s') % {'text': item['others_view']},
                  _('확인할 것: %(text)s') % {'text': item['check']}, _('물어볼 질문: %(text)s') % {'text': item['question']},
                  _('불확실한 부분: %(text)s') % {'text': item['uncertainty']}]
        lines += source_lines(item) + ['']
    return '\n'.join(lines)
