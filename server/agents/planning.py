# The server fixes the phases (issues, debate, close, final) and the order of issues; inside an issue the moderator picks who speaks next.
MAX_ISSUES = 3  # Issues picked before the debate.
MAX_NEW_ISSUES = 2  # Issues the moderator may add from the debate.
PER_ISSUE = 3  # Statements on each issue; the user's role always makes the first.

NEXT = {None: 'issues', 'independent': None, 'issues': 'debate', 'debate': 'debate', 'close': 'final', 'final': None}  # independent: older runs cannot continue.
PHASES = {'independent': 'discussion', 'issues': 'discussion', 'debate': 'review', 'close': 'review', 'final': 'proposal'}  # independent: runs made before the moderator.
ORDER = ('discussion', 'review', 'proposal', None)


def next_stage(steps):
    return NEXT[steps[-1]['stage'] if steps else None]


def next_phase(steps):
    stage = next_stage(steps)
    return PHASES[stage] if stage else None


def phase_of(stage):
    return PHASES[stage]


def last_speaker(steps):
    return next((step['role'] for step in reversed(steps) if step['stage'] == 'debate'), None)


def role_count(run):
    return len(run.analysis.get('roles', []))
