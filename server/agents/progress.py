import re

from django.utils.translation import gettext as _, gettext_noop

from .memory.context import all_issues, issue_of, numbered_steps, pending_issue
from .planning import next_phase, next_stage, phase_of

LABELS = {'independent': gettext_noop('입장 살펴보기'), 'issues': gettext_noop('쟁점 정리'), 'debate': gettext_noop('쟁점 토론'), 'close': gettext_noop('토론 마무리'), 'final': gettext_noop('주의 조항 정리')}


def step_label(run, stage, role):
    label = _(LABELS[stage])
    if role is not None:
        label += ' · ' + run.analysis['roles'][role]['name']
    return label


def speaker_name(run, role):
    return run.analysis['roles'][role]['name'] if role is not None else 'PolicyLens'


def issue_result(steps):
    return next((step['result'] for step in steps if step['stage'] == 'issues'), {})


def issue_cards(run, steps):
    # Page 3: each issue with every role's one-line opening position under it.
    result = issue_result(steps)
    roles = run.analysis.get('roles', [])
    for item in result.get('items', []):
        for position in item.get('positions', []):
            position.update(name=roles[position['role']]['name'], is_self=position['role'] == run.selected_role)
    return result


def numbered_issues(steps):
    # Issues picked up front come first, then the moderator's additions, numbered in that order.
    return {issue['id']: {**issue, 'number': number} for number, issue in enumerate(all_issues(steps), 1)}


def new_issues(steps):
    issues = numbered_issues(steps)
    return [issues[issue['id']] for step in steps for issue in step.get('moderator', {}).get('new_issues', [])]


def current_issue(run):
    steps = numbered_steps(run.steps)
    issues = numbered_issues(steps)
    if not issues:
        return None
    if steps[-1]['stage'] in ('close', 'final'):
        return {'ended': True}
    pending, _ = pending_issue(steps)
    if pending:
        return issues[pending['id']]
    debate = [step for step in steps if step['stage'] == 'debate' and 'moderator' in step]
    return issues[issue_of(debate[-1])] if debate else None


def is_complete(run):
    return bool(run.steps) and run.steps[-1]['stage'] == 'final'


def display_steps(run):
    steps = numbered_steps(run.steps)
    issues = numbered_issues(steps)
    opened, previous = set(), None
    for index, step in enumerate(steps):
        role, stage = step['role'], step['stage']
        issue = issue_of(step) if stage == 'debate' and 'moderator' in step else None
        step.update(label=step_label(run, stage, role), number=index + 1,
                    speaker=speaker_name(run, role),
                    is_self=role is not None and role == run.selected_role,
                    opens=issue is not None and issue not in opened,  # The first statement on an issue states it; later ones answer.
                    issue=issues.get(issue), issue_changed=issue is not None and issue != previous,
                    phase=phase_of(stage))
        opened.add(issue)
        previous = issue or previous
        for item in step['result']['items']:
            item['references'] = [{'id': target, 'page': phase_of(steps[int(target.split('-')[0][1:]) - 1]['stage'])}
                                  for target in item.get('target_ids', [])]
    return steps


def progress(run):
    stage = next_stage(run.steps)
    next_label, next_name, next_role = '', '', None
    if stage and run.selected_role is not None:
        # Only an issue's opening speaker is known ahead; after that the moderator decides inside the step.
        issue, said = pending_issue(numbered_steps(run.steps))
        if stage == 'debate' and issue and not said:
            next_role = run.selected_role
        next_label = step_label(run, stage, next_role)
        next_name = speaker_name(run, next_role)
    return {'cursor': len(run.steps), 'complete': is_complete(run), 'next_phase': next_phase(run.steps),
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


def caution_text(items):
    # Both sides of the comparison use these lines, so the layout does not reveal which result is which. Empty fields are left out.
    fields = [(_('영향: %(text)s'), 'impact'), (_('내 해석: %(text)s'), 'my_reading'), (None, 'other_reading'), (_('확인할 것: %(text)s'), 'check'),
              (_('물어볼 질문: %(text)s'), 'question'), (_('불확실한 부분: %(text)s'), 'uncertainty')]
    lines = []
    for number, item in enumerate(items, 1):
        page, quote = item['citation']['page'], item['citation']['quote']
        lines.append(f'{number}. {item["issue"]}')
        if item['reason'].strip():
            lines.append(item['reason'])
        if quote.strip():
            lines.append((_('원문(%(page)s쪽): %(quote)s') if page else _('원문: %(quote)s')) % {'page': page, 'quote': quote})
        for label, key in fields:
            if key == 'my_reading' and item.get('phrase', '').strip():  # The disputed words come right before the readings.
                lines.append(_('갈리는 표현: "%(text)s"') % {'text': item['phrase']})
            if item.get(key, '').strip():
                # The other reading carries the name of the role who reads it that way.
                values = {'text': item[key], 'name': item.get('other_role', '').strip() or _('상대')}
                lines.append((label or _('%(name)s의 해석: %(text)s')) % values)
        lines += source_lines(item) + ['']
    return '\n'.join(lines)


def pipeline_text(run):
    return caution_text(run.steps[-1]['result']['items'])


def baseline_text(run):
    # Runs compared before the answer was copied into fields still show the answer itself.
    if not run.baseline_items:
        return plain_text(run.baseline)
    return plain_text(caution_text([{**item, 'citation': {'page': item['page'], 'quote': item['quote']}} for item in run.baseline_items]))
