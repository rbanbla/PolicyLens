# One turn is one model call that makes one item. A role speaks in rounds, so the chat takes turns instead of flooding.
TURNS = 3


def steps_for(count, first=None):
    roles = range(count)
    speakers = sorted(roles, key=lambda role: role != first)  # The chosen role opens every issue and the others answer it.
    return ([('independent', role) for _ in range(TURNS) for role in roles] + [('issues', None)]
            + [('debate', role) for _ in range(TURNS) for role in speakers] + [('final', None)])


def phases_for(count):
    turns = TURNS * count
    return {'discussion': (0, turns + 1), 'review': (turns + 1, 2 * turns + 1), 'proposal': (2 * turns + 1, 2 * turns + 2)}


def phase_of(index, count):
    return next(name for name, (start, end) in phases_for(count).items() if start <= index < end)


def turn_of(index, count):
    # The round of an independent turn, or the number of the issue a debate turn answers.
    return index // count if index < TURNS * count else (index - TURNS * count - 1) // count


def is_skipped(steps, index, count):
    # A turn with nothing left to do is recorded without a model call. Only earlier steps decide.
    stage, role = steps_for(count)[index]
    if stage == 'independent':
        return any(step['stage'] == 'independent' and step['role'] == role and not step['result']['items'] for step in steps[:index])
    if stage == 'debate':
        issues = next(step for step in steps[:index] if step['stage'] == 'issues')
        return turn_of(index, count) >= len(issues['result']['items'])
    return False


def role_count(run):
    return len(run.analysis.get('roles', []))
