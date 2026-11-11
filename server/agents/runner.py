import json
import random
import time
from django.conf import settings
from django.utils.translation import gettext
from .schemas import ANALYSIS, BASELINE_ITEMS, PRIORITY_ORDER, SOURCE_STAGES, moderator, report
from .planning import PER_ISSUE, last_speaker, next_stage, role_count
from .memory.context import all_issues, assigned_claim, history, numbered_steps, pending_issue, reference_ids
from .tools.documents import align_citations, numbered_pages
from .tools.personas import anonymized, match_personas
from .tools.sources import TOOLS, check_sources, new_research, run_tool
from .validation import validate_moderator, validate_phrases, validate_positions, validate_shape, validate_roles, validate_report
from ..integrations import transport
from ..models import ReviewRun, Source

MAX_TOOL_ROUNDS = 3

def create_run(owner, title, pages, language='ko'):
    _, model = transport.configuration()
    return ReviewRun.objects.create(
        owner=owner, title=title.strip()[:200] or gettext('정책 검토'), pages=pages, language=language,
        model=model, provider=transport.identity(), structured_facts=True,
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

def call_model(run, stage, payload, key, purpose='model', role=None):
    index = len(run.steps) if stage not in ('analysis', 'baseline') else None
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

def agent_loop(run, stage, payload, key, research, search_first, role=None):
    # The model picks what to look up and when to stop; the server runs the tools and caps the rounds.
    conversation = [{'role': 'user', 'content': payload['input']}]
    for round_number in range(MAX_TOOL_ROUNDS):
        choice = {'tool_choice': 'required'} if search_first and round_number == 0 else {}
        response = call_model(run, stage, {**payload, 'input': conversation, 'tools': TOOLS, **choice}, key, 'model' if round_number == 0 else 'tool_followup', role)
        calls = [item for item in response.get('output', []) if item.get('type') == 'function_call']
        if not calls:
            return output_text(response)
        conversation += calls + [{'type': 'function_call_output', 'call_id': call['call_id'], 'output': run_tool(run.pages, research, call)}
                                 for call in calls]
    return output_text(call_model(run, stage, {**payload, 'input': conversation, 'tools': TOOLS, 'tool_choice': 'none'}, key, 'tool_followup', role))

def generate(run, stage, data, schema, check, research=None, search_first=False, role=None):
    key = ready_key(run)
    body = json.dumps(data, ensure_ascii=False)
    instructions = [run.prompts['common'], run.prompts[stage]] + ([run.prompts['references']] if stage not in ('analysis', 'moderator') else []) + ([run.prompts['sources']] if research else []) + ([run.prompts['lang_en']] if run.language == 'en' else [])
    payload = {'model': run.model, 'store': False, 'instructions': '\n'.join(instructions), 'input': body, 'max_output_tokens': 6000, 'text': {'format': {'type': 'json_schema', 'name': 'review', 'strict': True, 'schema': schema}}}
    search = research is not None
    for retry in (True, False):
        text = agent_loop(run, stage, payload, key, research, search_first, role) if search else output_text(call_model(run, stage, payload, key, 'model' if retry else 'repair', role))
        try:
            output = json.loads(text)
            validate_shape(output, schema)
            align_citations(run.pages, [entry['citation'] for entry in output.get('roles', output.get('items', output.get('new_issues', [])))])
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
    run.personas = match_personas(result['roles'])
    run.save(update_fields=['analysis', 'personas', 'calls'])

def uses_sources(run, stage):
    # A run keeps the prompts it started with, so older runs stay on the document alone.
    return stage in SOURCE_STAGES and 'sources' in run.prompts and Source.objects.exists()

def role_card(run, role):
    # The persona is a synthetic person who stands in for the role; the role itself still comes from the document.
    persona = run.personas[role] if role < len(run.personas) else None
    return {**run.analysis['roles'][role], 'persona': persona and anonymized(dict(persona))}  # Runs made before names were deleted still never send one.

def stage_input(run, stage, role, context, targets):
    # The speaking role gets only its own card; the user's choice sets who opens the debate and otherwise reaches the final step alone.
    data = {'pages': numbered_pages(run.pages), 'history': context, 'allowed_target_ids': targets}
    if role is None:
        data['roles'] = [{'index': index, **role_card(run, index)} for index in range(role_count(run))]
    else:
        data['acting_role'] = role_card(run, role)
    if stage == 'final':
        data['user_role'] = role_card(run, run.selected_role)
    return data

def research_fields(research):
    return {'research': research['log'], 'policy_facts': research['facts']} if research else {}

def save_step(run, step):
    run.steps = numbered_steps(run.steps + [step])
    run.error = ''
    run.save(update_fields=['steps', 'error', 'calls'])

def advance(run):
    stage = next_stage(run.steps)
    if stage == 'debate':
        return debate(run)
    context = history(run, stage)
    targets = reference_ids(context, stage, None)
    data = stage_input(run, stage, None, context, targets)
    research = new_research(run.as_of, structured_facts=run.structured_facts) if uses_sources(run, stage) else None
    def check(output):
        validate_report(run.pages, output, stage, targets)
        if stage == 'issues':
            validate_positions(output, role_count(run))
        if stage == 'final':
            validate_phrases(output)
        check_sources(output, research['opened'] if research else {})
    # With the document already in hand the model skips optional lookups, so the final step must search first.
    others = [role['name'] for index, role in enumerate(run.analysis['roles']) if index != run.selected_role]
    result = generate(run, stage, data, report(stage, targets, others), check, research, stage == 'final')
    result['items'].sort(key=lambda item: PRIORITY_ORDER.index(item['priority']))
    save_step(run, {'stage': stage, 'role': None, 'result': result, **research_fields(research)})

def moderate(run, context, issue, said):
    count = role_count(run)
    last = last_speaker(run.steps)
    issues = all_issues(context)
    data = {'pages': numbered_pages(run.pages), 'roles': [{'index': index, **role_card(run, index)} for index in range(count)],
            'history': context, 'issues': issues, 'current_issue_id': issue['id'], 'statements_left': PER_ISSUE - said, 'last_speaker': last}
    output = generate(run, 'moderator', data, moderator(), lambda output: validate_moderator(run.pages, output, count, last, len(issues)))
    return {'summary': output['summary'], 'next': [{'speaker': output['speaker'], 'issue_id': issue['id'], 'question': output['question']}],
            'new_issues': output['new_issues']}

def debate(run):
    context = history(run, 'debate')
    issue, said = pending_issue(context)
    if issue is None:
        return save_step(run, {'stage': 'close', 'role': None, 'result': {'summary': gettext('쟁점마다 정해진 발언을 마쳐 토론을 끝내요.'), 'items': []}})
    if said:
        decision = moderate(run, context, issue, said)
    else:
        # The user's role opens every issue; the moderator picks who speaks after it.
        decision = {'summary': '', 'next': [{'speaker': run.selected_role, 'issue_id': issue['id'], 'question': ''}], 'new_issues': []}
    turn = decision['next'][0]
    role = turn['speaker']
    targets = reference_ids(context, 'debate', role)
    data = stage_input(run, 'debate', role, context, targets)
    data['assigned_claims'] = [assigned_claim(context, turn['issue_id'], role)]
    data['moderator_question'] = turn['question']
    required = [target for target in data['assigned_claims'][0].values() if target]
    research = new_research(run.as_of, structured_facts=run.structured_facts) if uses_sources(run, 'debate') else None
    def check(output):
        # The server assigned the issue and the claims to answer, so it links any the model left out instead of failing the turn.
        for item in output['items']:
            item['target_ids'] = list(dict.fromkeys(required + item['target_ids']))
        validate_report(run.pages, output, 'debate', targets)
        check_sources(output, research['opened'] if research else {})
    # A role's first statement must search first; later ones search only when they need to.
    search_first = not any(step['stage'] == 'debate' and step['role'] == role for step in run.steps)
    result = generate(run, 'debate', data, report('debate', targets), check, research, search_first, role)
    save_step(run, {'stage': 'debate', 'role': role, 'result': result, 'moderator': decision, **research_fields(research)})

def baseline(run):
    # The comparison arm: same model and document, the question a user would type, no pipeline or checks.
    role = run.analysis['roles'][run.selected_role]['name']
    text = output_text(call_model(run, 'baseline', {'model': run.model, 'store': False, 'instructions': run.prompts['baseline_en' if run.language == 'en' else 'baseline'].replace('{role}', role), 'input': json.dumps({'pages': numbered_pages(run.pages)}, ensure_ascii=False), 'max_output_tokens': 6000}, ready_key(run))).strip()
    if not text:
        raise ValueError(gettext('모델 응답이 비어 있습니다. 다시 시도하세요.'))
    run.baseline = text
    run.baseline_items = baseline_items(run, text) if 'baseline_format' in run.prompts else []
    run.evaluation = {'pipeline': random.choice('AB')}
    run.error = ''
    run.save(update_fields=['baseline', 'baseline_items', 'evaluation', 'error', 'calls'])

def baseline_items(run, text):
    # Only the answer goes in, not the document, so the copy cannot add what the single prompt did not find. Nothing checks it on purpose.
    payload = {'model': run.model, 'store': False, 'instructions': run.prompts['baseline_format'], 'input': json.dumps({'baseline_answer': text}, ensure_ascii=False),
               'max_output_tokens': 6000, 'text': {'format': {'type': 'json_schema', 'name': 'baseline_items', 'strict': True, 'schema': BASELINE_ITEMS}}}
    items = json.loads(output_text(call_model(run, 'baseline', payload, ready_key(run), 'format')))['items']
    if not items:
        raise ValueError(gettext('모델 응답이 비어 있습니다. 다시 시도하세요.'))
    return items
