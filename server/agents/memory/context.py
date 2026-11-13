from collections import Counter
from copy import deepcopy
from ..planning import MAX_STATEMENTS


def numbered_steps(steps):
    result = deepcopy(steps)
    for index, step in enumerate(result, 1):
        for number, item in enumerate(step['result']['items'], 1):
            item['id'] = f's{index}-i{number}'
        for number, item in enumerate(step.get('moderator', {}).get('new_issues', []), 1):
            item['id'] = f's{index}-n{number}'
    return result


def history(run, stage):
    # The issues step reads only the document and the role cards; the debate and the final step see everything said so far.
    allowed = {'issues': [], 'moderator': ['issues', 'debate', 'issue_close'], 'debate': ['issues', 'debate', 'issue_close'], 'final': ['issues', 'debate', 'issue_close']}[stage]
    roles = run.analysis['roles']
    return [{'stage': step['stage'], 'role': step['role'], 'result': step['result'],
             'speaker': 'PolicyLens' if step['role'] is None else roles[step['role']]['name'],
             **({'moderator': step['moderator']} if 'moderator' in step else {})}
            for step in numbered_steps(run.steps) if step['stage'] in allowed]


def all_issues(context):
    # Issues picked up front, then the ones the moderator added during the debate.
    return ([item for step in context if step['stage'] == 'issues' for item in step['result']['items']]
            + [item for step in context for item in step.get('moderator', {}).get('new_issues', [])])


def issue_of(step):
    return step['moderator']['next'][0]['issue_id']


def pending_issue(context):
    # Issues are debated in order until the moderator closes them (or the safety limit); None once every issue is done.
    said = Counter(issue_of(step) for step in context if step['stage'] == 'debate' and 'moderator' in step)
    closed = {step['moderator']['closed'] for step in context if step['stage'] == 'issue_close'}
    return next(((issue, said[issue['id']]) for issue in all_issues(context)
                 if issue['id'] not in closed and said[issue['id']] < MAX_STATEMENTS), (None, 0))


def spoken_roles(context, issue_id):
    return sorted({step['role'] for step in context if step['stage'] == 'debate' and 'moderator' in step and issue_of(step) == issue_id})


def opener(issue, selected, count):
    # The user's role opens an issue unless the clause barely touches it; then the first role it does touch opens. Older issues have no marks.
    low = issue.get('low_relevance', [])
    return selected if selected not in low else next(role for role in range(count) if role not in low)


def reference_ids(context, stage, role):
    if stage == 'debate':
        return [item['id'] for item in all_issues(context)] + [
            item['id'] for step in context if step['stage'] == 'debate' and step['role'] != role for item in step['result']['items']]
    if stage == 'final':
        return [item['id'] for step in context if step['stage'] == 'debate' for item in step['result']['items']]
    return []


def assigned_claim(context, issue_id, role):
    # The first statement by someone else on this issue is the claim to answer, and the latest other one the reply. None means this role opens it.
    said = [step['result']['items'][0]['id'] for step in context
            if step['stage'] == 'debate' and issue_of(step) == issue_id and step['role'] != role]
    return {'issue_id': issue_id, 'claim_id': said[0] if said else None, 'reply_id': said[-1] if len(said) > 1 else None}
