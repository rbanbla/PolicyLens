from pathlib import Path
from django.core.cache import cache
from django.db import transaction, OperationalError
from django.http import Http404, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _, gettext_noop
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_GET
from .models import ReviewRun
from .agents.runner import add_note, analyze, advance, baseline, create_run, skip_issue
from .agents.planning import ORDER, next_phase, role_count
from .agents.progress import progress, baseline_text, current_issue, display_steps, feedback_letters, is_complete, issue_cards, issue_notes, new_issues, pipeline_text, research_log
from .agents.tools.documents import read_pages
from .integrations.policy_suggest import newest_youth_policies
from .integrations.transport import dummy_mode

MODEL_ERRORS = (ValueError, KeyError, TypeError, OSError)
CONFLICT = gettext_noop('다른 요청에서 단계가 진행되었습니다. 저장된 상태에서 다시 시작하세요.')


def attempt(run, action):
    try:
        action(run)
    except MODEL_ERRORS as exc:
        run.error = str(exc)
        run.save(update_fields=['error', 'calls'])


def latest_policies():
    # Cached so a home visit does not call the briefing API each time; the start check reads the same list.
    key = 'latest_policies:dummy' if dummy_mode() else 'latest_policies'  # Toggling the dummy mode never serves the other list.
    policies = cache.get(key)
    if policies is None:
        policies = newest_youth_policies()
        cache.set(key, policies, 30 * 60)
    return policies


@require_GET
def latest(request):
    try:
        policies = latest_policies()
    except (ValueError, OSError):
        policies = []  # The picker is optional; the home page goes on without it.
    return render(request, 'latest_policies.html', {'policies': policies})


def home(request):
    if request.GET.get('lang') in ('ko', 'en'):
        request.session['language'] = request.GET['lang']
        return redirect('home')
    error = ''
    if request.method == 'POST':
        try:
            upload = request.FILES.get('document')
            # A picked policy is fetched again on the server, so the run stores the source text, not a client copy.
            picked = request.POST.get('policy')
            policy = next((p for p in latest_policies() if p['id'] == picked), None) if picked else None
            if picked and not policy:
                raise ValueError(_('선택한 정책을 다시 찾지 못했습니다. 목록을 새로 불러와 주세요.'))
            pages = read_pages(None if policy else upload, policy['text'] if policy else request.POST.get('text', ''))
            if not request.session.session_key:
                request.session.create()
            title = policy['title'] if policy else Path(upload.name).stem.replace('_', ' ') if upload else ''
            run = create_run(request.session.session_key, title, pages, request.session.get('language', 'ko'))
        except (ValueError, OSError) as exc:
            error = str(exc)
        else:
            attempt(run, analyze)
            return redirect('review', pk=run.pk)
    return render(request, 'home.html', {'error': error})

def owned(request, pk):
    run = get_object_or_404(ReviewRun, pk=pk, owner=request.session.session_key or '')
    translation.activate(run.language)
    return run

def review(request, pk):
    run = owned(request, pk)
    return review_page(request, run)

def review_page(request, run, error='', status=200):
    current = next_phase(run.steps)
    default_page = current or 'proposal'
    page = request.GET.get('page', default_page)
    if page not in ('summary',) + ORDER[:-1]:
        page = default_page
    if run.selected_role is None:
        page = 'summary'
    steps = display_steps(run)
    reached = ORDER.index(current)
    context = {
        'phase': page,
        'phase_done': page == 'summary' or ORDER.index(page) < reached, 'phase_ready': page == 'summary' or ORDER.index(page) <= reached,
        'display_steps': steps, 'issues': issue_cards(run, steps), 'current': current_issue(run), 'new_issues': new_issues(steps), 'notes': issue_notes(run), 'letters': feedback_letters(run), 'research': research_log(run),
        'form_error': error, 'run': run, 'complete': is_complete(run),
        'starting': request.GET.get('start') == '1',  # Just picked a role: the issue step starts at once, so its wait screen shows from the first paint.
        'selected': run.analysis['roles'][run.selected_role]['name'] if run.selected_role is not None else '',
    }
    return render(request, 'review.html', context, status=status)


@require_POST
def select(request, pk):
    run = owned(request, pk)
    if run.selected_role is not None:
        return redirect('review', pk=pk)
    role = request.POST.get('role')
    if role not in map(str, range(role_count(run))):
        return review_page(request, run, _('자신의 입장을 선택해 주세요.'), status=400)
    ReviewRun.objects.filter(pk=run.pk, selected_role=None).update(selected_role=int(role))
    return redirect(reverse('review', args=[pk]) + '?start=1')

def step_response(request, run, status=200, message=''):
    if request.get_preferred_type(['text/html', 'application/json']) == 'application/json':
        data = progress(run)
        data['message'] = message
        steps = display_steps(run)
        data['steps_html'] = render_to_string('review_steps.html', {'display_steps': steps, 'all_steps': True})
        data['issues_html'] = render_to_string('issue_cards.html', {'issues': issue_cards(run, steps)})
        current = current_issue(run)
        data['current_issue_html'] = render_to_string('current_issue.html', {'current': current})
        data['skip_html'] = render_to_string('skip_bar.html', {'current': current})
        data['new_issues_html'] = render_to_string('new_issues.html', {'new_issues': new_issues(steps), 'notes': issue_notes(run)})
        response = JsonResponse(data, status=status)
        response['Cache-Control'] = 'no-store'
        return response
    return redirect('review', pk=run.pk)


@require_GET
def status(request, pk):
    return step_response(request, owned(request, pk))


@require_POST
def step(request, pk):
    run = owned(request, pk)
    if run.selected_role is None:
        return step_response(request, run, 400, _('먼저 자신의 입장을 선택하세요.'))
    if is_complete(run):
        return step_response(request, run)
    if request.POST.get('cursor') != str(len(run.steps)):
        return step_response(request, run, 409, _(CONFLICT))
    try:
        with transaction.atomic():
            # Claim the observed snapshot with a write before calling the provider.
            claimed = ReviewRun.objects.filter(pk=run.pk, steps=run.steps).update(error='')
            if claimed:
                attempt(run, advance)
        if not claimed:
            run.refresh_from_db()
            return step_response(request, run, 409, _(CONFLICT))
    except OperationalError:
        return step_response(request, run, 503, _('서버가 다른 작업을 저장 중입니다. 잠시 후 다시 시작하세요.'))
    return step_response(request, run, 502 if run.error else 200)


@require_POST
def skip(request, pk):
    run = owned(request, pk)
    if request.POST.get('cursor') != str(len(run.steps)):
        return step_response(request, run, 409, _(CONFLICT))
    try:
        with transaction.atomic():
            # The same snapshot claim as a step, so a skip never lands between a step's read and its save.
            if not ReviewRun.objects.filter(pk=run.pk, steps=run.steps).update(error=''):
                run.refresh_from_db()
                return step_response(request, run, 409, _(CONFLICT))
            skip_issue(run)
    except ValueError as exc:
        return step_response(request, run, 400, str(exc))
    return step_response(request, run)


@require_POST
def debate_note(request, pk, note):
    run = owned(request, pk)
    if request.POST.get('cursor') != str(len(run.steps)):
        return step_response(request, run, 409, _(CONFLICT))
    try:
        with transaction.atomic():
            # The same snapshot claim as a skip, so a note never joins after the step that closes the debate has read the issues.
            if not ReviewRun.objects.filter(pk=run.pk, steps=run.steps).update(error=''):
                run.refresh_from_db()
                return step_response(request, run, 409, _(CONFLICT))
            add_note(run, note)
    except ValueError as exc:
        return step_response(request, run, 400, str(exc))
    return step_response(request, run)


@require_POST
def retry_analysis(request, pk):
    with transaction.atomic():
        run = owned(request, pk)
        if ReviewRun.objects.filter(pk=run.pk, analysis={}).update(error=''):
            attempt(run, analyze)
    return redirect('review', pk=pk)


@require_GET
def feedback(request, pk, role):
    letters = feedback_letters(owned(request, pk))
    if role >= len(letters):
        raise Http404
    response = HttpResponse(letters[role]['text'], content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="policylens-feedback-{pk}-{role + 1}.txt"'
    return response


def compare_page(request, run, error='', status=200):
    results = []
    if run.baseline:
        label = run.evaluation['pipeline']
        results = sorted([{'label': label, 'source': 'PolicyLens', 'text': pipeline_text(run)},
                          {'label': 'B' if label == 'A' else 'A', 'source': _('단일 프롬프트'), 'text': baseline_text(run)}],
                         key=lambda result: result['label'])
    return render(request, 'compare.html', {'run': run, 'results': results, 'form_error': error,
                  'rated': 'preferred' in run.evaluation}, status=status)


@require_GET
def compare(request, pk):
    run = owned(request, pk)
    if not is_complete(run):
        return redirect('review', pk=pk)
    return compare_page(request, run)


@require_POST
def compare_run(request, pk):
    with transaction.atomic():
        run = owned(request, pk)
        if is_complete(run) and ReviewRun.objects.filter(pk=run.pk, baseline='').update(error=''):
            attempt(run, baseline)
    return redirect('compare', pk=pk)


@require_POST
def compare_rate(request, pk):
    run = owned(request, pk)
    preferred = request.POST.get('preferred')
    if not run.baseline or preferred not in ('A', 'B', '비슷함'):
        return compare_page(request, run, _('더 도움이 된 결과를 선택해 주세요.'), status=400)
    if 'preferred' not in run.evaluation:
        run.evaluation = {**run.evaluation, 'preferred': preferred, 'note': request.POST.get('note', '').strip()[:2000]}
        run.save(update_fields=['evaluation'])
    return redirect('compare', pk=pk)
