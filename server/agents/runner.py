import json
import random
import time
from django.conf import settings
from django.utils.translation import gettext
from .schemas import ANALYSIS, PRIORITY_ORDER, SOURCE_STAGES, report
from .planning import is_skipped, role_count, steps_for, turn_of
from .memory.context import assigned_claim, history, numbered_steps, reference_ids
from .tools.documents import align_citations, numbered_pages
from .tools.sources import TOOLS, check_sources, new_research, run_tool
from .validation import validate_shape, validate_roles, validate_report
from ..integrations import transport
from ..models import ReviewRun, Source

MAX_TOOL_ROUNDS = 3

def create_run(owner, title, pages, language='ko'):
    _, model = transport.configuration()
    return ReviewRun.objects.create(
        # PostgreSQL cannot store NUL, which PDF text sometimes carries; clean() already ignores it in quotes.
        owner=owner, title=title.strip()[:200] or gettext('정책 검토'), pages=[page.replace('\x00', '') for page in pages], language=language,
        model=model, provider=transport.identity(),
        prompts={p.stem: p.read_text(encoding='utf-8') for p in (settings.BASE_DIR / 'prompts').glob('*.md')})

def ready_key(run):
    key, _ = transport.configuration()
    if not key or not run.model:
        raise ValueError(gettext('모델 API 키와 모델 이름을 .env에 설정하세요.'))
    if run.provider != transport.identity():
        raise ValueError(gettext('모델 제공자 설정이 변경되었습니다. 새 검토를 시작하세요.'))
    return key

def output_text(response):
    if response.get('status') != 'completed':
        raise ValueError(gettext('모델 응답이 완료되지 않았습니다. 다시 시도하세요.'))
    return ''.join(p['text'] for item in response['output'] if item.get('type') == 'message' for p in item.get('content', []) if p.get('type') == 'output_text')

def call_model(run, stage, payload, key, purpose='model'):
    index = len(run.steps) if stage not in ('analysis', 'baseline') else None
    role = steps_for(role_count(run), run.selected_role)[index][1] if index is not None else None
    for attempt in (1, 2):
        started = time.monotonic()
        entry = {'stage': stage, 'step_index': index, 'role': role, 'purpose': purpose, 'attempt': attempt}
        try:
            response = transport.call(payload, key)
        except Exception as exc:
            entry['error'] = type(exc).__name__
            if attempt == 2 or not isinstance(exc, TimeoutError):
                raise
        else:
            usage = response.get('usage') or {}
            entry.update(tokens=usage.get('total_tokens'),
                         input_tokens=usage.get('input_tokens', usage.get('prompt_tokens')),
                         output_tokens=usage.get('output_tokens', usage.get('completion_tokens')))
            return response
        finally:
            elapsed = time.monotonic() - started
            entry.update(seconds=round(elapsed, 1), elapsed_ms=round(elapsed * 1000, 2))
            run.calls.append(entry)

def agent_loop(run, stage, payload, key, research, search_first):
    # The model picks what to look up and when to stop; the server runs the tools and caps the rounds.
    conversation = [{'role': 'user', 'content': payload['input']}]
    for round_number in range(MAX_TOOL_ROUNDS):
        choice = {'tool_choice': 'required'} if search_first and round_number == 0 else {}
        response = call_model(run, stage, {**payload, 'input': conversation, 'tools': TOOLS, **choice}, key, 'model' if round_number == 0 else 'tool_followup')
        calls = [item for item in response.get('output', []) if item.get('type') == 'function_call']
        if not calls:
            return output_text(response)
        conversation += calls + [{'type': 'function_call_output', 'call_id': call['call_id'], 'output': run_tool(run.pages, research, call)}
                                 for call in calls]
    return output_text(call_model(run, stage, {**payload, 'input': conversation, 'tools': TOOLS, 'tool_choice': 'none'}, key, 'tool_followup'))

def generate(run, stage, data, schema, check, research=None, search_first=False):
    key = ready_key(run)
    body = json.dumps(data, ensure_ascii=False)
    instructions = [run.prompts['common'], run.prompts[stage]] + ([run.prompts['references']] if stage != 'analysis' else []) + ([run.prompts['sources']] if research else []) + ([run.prompts['lang_en']] if run.language == 'en' else [])
    payload = {'model': run.model, 'store': False, 'instructions': '\n'.join(instructions), 'input': body, 'max_output_tokens': 6000, 'text': {'format': {'type': 'json_schema', 'name': 'review', 'strict': True, 'schema': schema}}}
    search = research is not None
    for retry in (True, False):
        text = agent_loop(run, stage, payload, key, research, search_first) if search else output_text(call_model(run, stage, payload, key, 'model' if retry else 'repair'))
        try:
            output = json.loads(text)
            validate_shape(output, schema)
            align_citations(run.pages, [entry['citation'] for entry in output.get('roles', output.get('items', []))])
            check(output)
            return output
        except ValueError as exc:
            if not retry:
                raise
            # One repair round: the server's validation result goes back to the model as data.
            found = {'server_sources': list(research['opened'].values())} if research else {}
            payload = {**payload, 'input': json.dumps({**data, **found, 'rejected_output': text, 'validation_error': str(exc)}, ensure_ascii=False)}
            search = False

def analyze(run):
    result = generate(run, 'analysis', {'pages': numbered_pages(run.pages)}, ANALYSIS, lambda output: validate_roles(run.pages, output))
    if result['status'] == 'insufficient':
        raise ValueError(gettext('이해가 다른 역할을 둘 이상 찾지 못했습니다. ') + result['selection_note'])
    run.analysis = result
    run.save(update_fields=['analysis', 'calls'])

def uses_sources(run, stage):
    # A run keeps the prompts it started with, so older runs stay on the document alone.
    return stage in SOURCE_STAGES and 'sources' in run.prompts and Source.objects.exists()

def stage_input(run, stage, role, context, targets, turn=0):
    # Role agents get only their own card; the user's choice sets who speaks first and otherwise reaches the final step alone.
    roles = run.analysis['roles']
    data = {'pages': numbered_pages(run.pages), 'history': context, 'allowed_target_ids': targets}
    if role is None:
        data['roles'] = roles
    else:
        data['acting_role'] = roles[role]
    if stage == 'debate':
        data['assigned_claims'] = [assigned_claim(context, turn, len(roles))]  # One issue per turn.
    if stage == 'final':
        data['user_role'] = roles[run.selected_role]
    return data

def advance(run):
    count = role_count(run)
    plan = steps_for(count, run.selected_role)
    stage, role = plan[len(run.steps)]
    context = history(run, stage, role)
    targets = reference_ids(context, stage, role)
    data = stage_input(run, stage, role, context, targets, turn_of(len(run.steps), count))
    required = [target for claim in data.get('assigned_claims', []) for target in claim.values() if target]
    research = new_research(run.as_of) if uses_sources(run, stage) else None
    def check(output):
        validate_report(run.pages, output, stage, targets, required)
        check_sources(output, research['opened'] if research else {})
    # With the document already in hand the model skips optional lookups, so a role's first turn and the final step must search first.
    search_first = stage == 'final' or (stage == 'independent' and not context)
    result = generate(run, stage, data, report(stage, targets), check, research, search_first)
    if stage in ('issues', 'final'):
        result['items'].sort(key=lambda item: PRIORITY_ORDER.index(item['priority']))
    steps = run.steps + [{'stage': stage, 'role': role, 'result': result, **({'research': research['log']} if research else {})}]
    # Turns with nothing left to do are recorded now, so the cursor always rests on a turn that needs a model call.
    while len(steps) < len(plan) and is_skipped(steps, len(steps), count):
        steps.append({'stage': plan[len(steps)][0], 'role': plan[len(steps)][1], 'result': {'summary': '', 'items': []}, 'skipped': True})
    run.steps = numbered_steps(steps)
    run.error = ''
    run.save(update_fields=['steps', 'error', 'calls'])

def baseline(run):
    # The comparison arm: same model and document, the question a user would type, no pipeline or checks.
    role = run.analysis['roles'][run.selected_role]['name']
    text = output_text(call_model(run, 'baseline', {'model': run.model, 'store': False, 'instructions': run.prompts['baseline_en' if run.language == 'en' else 'baseline'].replace('{role}', role), 'input': json.dumps({'pages': numbered_pages(run.pages)}, ensure_ascii=False), 'max_output_tokens': 6000}, ready_key(run))).strip()
    if not text:
        raise ValueError(gettext('모델 응답이 비어 있습니다. 다시 시도하세요.'))
    run.baseline = text
    run.evaluation = {'pipeline': random.choice('AB')}
    run.error = ''
    run.save(update_fields=['baseline', 'evaluation', 'error', 'calls'])
