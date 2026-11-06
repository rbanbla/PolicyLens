from copy import deepcopy


def numbered_steps(steps):
    result = deepcopy(steps)
    for index, step in enumerate(result, 1):
        for number, item in enumerate(step['result']['items'], 1):
            item['id'] = f's{index}-i{number}'
    return result


def history(run, stage, role=None):
    # An independent turn sees only what its own role said before; everyone else's words wait for the issues step.
    allowed = {'independent': ['independent'], 'issues': ['independent'], 'debate': ['independent', 'issues', 'debate'], 'final': ['issues', 'debate']}[stage]
    roles = run.analysis['roles']
    return [{'stage': step['stage'], 'role': step['role'], 'result': step['result'], 'speaker': 'PolicyLens' if step['role'] is None else roles[step['role']]['name']}
            for step in numbered_steps(run.steps) if step['stage'] in allowed and not step.get('skipped') and (stage != 'independent' or step['role'] == role)]


def reference_ids(context, stage, role):
    sources = {'issues': ['independent'], 'debate': ['independent', 'issues', 'debate'], 'final': ['debate']}.get(stage, [])
    return [item['id'] for step in context if step['stage'] in sources
            and not (stage == 'debate' and step['role'] == role)
            for item in step['result']['items']]


def assigned_claim(context, turn, count):
    # Each issue takes one debate step per role, so its opening statement sits at turn * count. The opener answers no one.
    issues = next(step for step in context if step['stage'] == 'issues')['result']['items']
    spoken = [step['result']['items'][0]['id'] for step in context if step['stage'] == 'debate']
    said = spoken[turn * count:]
    return {'issue_id': issues[turn]['id'], 'claim_id': said[0] if said else None, 'reply_id': said[-1] if len(said) > 1 else None}
