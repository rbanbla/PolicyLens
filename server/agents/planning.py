# The server fixes the phases (issues, debate, close, final) and the order of issues; inside an issue the moderator picks who speaks next and when it ends.
MAX_ISSUES = 3  # Issues picked before the debate.
MAX_STATEMENTS = 10  # Not a target: only stops an issue the moderator never closes.
MIN_BEFORE_SKIP = 3  # Statements an issue needs before the user may move on to the next one.

NEXT = {None: 'issues', 'independent': None, 'issues': 'debate', 'debate': 'debate', 'issue_close': 'debate', 'close': 'final', 'final': None}  # independent: older runs cannot continue.
PHASES = {'independent': 'discussion', 'issues': 'discussion', 'debate': 'review', 'issue_close': 'review', 'close': 'review', 'final': 'proposal'}  # independent: runs made before the moderator.
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
