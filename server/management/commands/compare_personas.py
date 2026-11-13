import json
import math
import re
from collections import Counter
from datetime import date
from itertools import combinations
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from server.agents.memory.context import issue_of
from server.agents.planning import role_count
from server.agents.progress import is_complete
from server.agents.runner import advance, analyze, create_run
from server.models import ReviewRun
from .evaluate import evaluation_document

ARMS = ('persona', 'none')
RESPONSES = ('수용', '제한', '반박')
GENERIC = re.compile(r'공개|투명|이의\s?제기|절차를?\s?마련|기준을?\s?(?:명확|마련|정해)')  # The shared demands earlier runs converged on.


def trigrams(text):
    text = re.sub(r'\s', '', text)
    return {text[i:i + 3] for i in range(len(text) - 2)}


def similarity(a, b):
    a, b = trigrams(a), trigrams(b)
    return len(a & b) / len(a | b) if a | b else 0.0


def details(persona):
    # Specifics the prompts tell agents never to show: where they live, their job, their age.
    if not persona:
        return []
    return [term for term in (persona['district'].split('-')[-1], persona['occupation'], f"{persona['age']}세") if len(term) >= 2]


def measure(steps, personas, calls):
    statements = [(step['role'], issue_of(step), step['result']['items'][0]) for step in steps
                  if step['stage'] == 'debate' and 'moderator' in step and step['result']['items']]
    count = len(statements) or 1
    responses = Counter(item['response'] for _, _, item in statements)
    shares = [responses[name] / count for name in RESPONSES]
    pairs = [similarity(a['request'], b['request']) for (role_a, issue_a, a), (role_b, issue_b, b) in combinations(statements, 2)
             if issue_a == issue_b and role_a != role_b]
    text = lambda item: ' '.join(value for value in item.values() if isinstance(value, str))
    return {
        'statements': len(statements),
        'responses': {name: responses[name] for name in RESPONSES},
        'limit_share': round(shares[1], 3),
        'response_entropy': round(-sum(share * math.log2(share) for share in shares if share), 3),  # 0 when every reply is the same type; at most log2(3).
        'generic_request_share': round(sum(bool(GENERIC.search(item['request'])) for _, _, item in statements) / count, 3),
        'cross_role_request_similarity': round(sum(pairs) / len(pairs), 3) if pairs else None,  # Lower means roles ask for different things.
        'persona_detail_leaks': sum(any(term in text(item) for term in details(personas[role] if role < len(personas) else None))
                                    for role, _, item in statements),
        'calls': len(calls),
        'tokens': sum(call.get('tokens') or 0 for call in calls),
    }


def mean(values):
    values = [value for value in values if value is not None]
    return round(sum(values) / len(values), 3) if values else None


class Command(BaseCommand):
    help = '같은 문서·역할로 페르소나를 붙인 토론과 뺀 토론을 번갈아 실행해 발언 지표를 비교한다(오프라인 평가).'

    def add_arguments(self, parser):
        parser.add_argument('doc_id')
        parser.add_argument('--role', type=int, default=0, help='입장을 맡을 역할 번호')
        parser.add_argument('--repeats', type=int, default=1, help='조건마다 반복할 실행 수')
        parser.add_argument('--output', help='결과 JSON 경로(기본: data/reviewed/runs/<doc_id>-personas.json)')

    def run_arm(self, title, pages, as_of, analysis, personas, role):
        run = create_run('evaluate', title, pages)
        run.as_of, run.analysis, run.personas, run.selected_role = as_of, analysis, personas, role
        run.save()
        try:
            while not is_complete(run):
                advance(run)
            return {'steps': run.steps, 'calls': run.calls}
        except ValueError as exc:
            return {'steps': run.steps, 'calls': run.calls, 'error': str(exc)}
        finally:
            ReviewRun.objects.filter(pk=run.pk).delete()  # Results live in the file; the service database stays user data only.

    def handle(self, doc_id, role, repeats, output=None, **options):
        doc, pages = evaluation_document(doc_id)
        as_of = date.fromisoformat(doc['published_on'])
        base = create_run('evaluate', doc['title'], pages)
        base.as_of = as_of
        base.save()
        try:
            analyze(base)  # Roles and personas are drawn once; the arms differ only in whether the personas are attached.
        finally:
            ReviewRun.objects.filter(pk=base.pk).delete()
        if not 0 <= role < role_count(base):
            raise CommandError('선택한 역할 번호가 범위를 벗어납니다.')
        arms = {'persona': base.personas, 'none': [None] * role_count(base)}
        runs = []
        for repeat in range(repeats):
            for arm in ARMS:  # Alternating, so a provider slowdown or change mid-way hits both arms alike.
                result = self.run_arm(doc['title'], pages, as_of, base.analysis, arms[arm], role)
                result.update(arm=arm, repeat=repeat, metrics=measure(result['steps'], base.personas, result['calls']))
                runs.append(result)
                self.stdout.write(f"{arm} {repeat + 1}/{repeats}: 발언 {result['metrics']['statements']}개{' 오류: ' + result['error'] if 'error' in result else ''}")
        summary = {arm: {key: mean([run['metrics'][key] for run in runs if run['arm'] == arm and 'error' not in run])
                         for key in ('statements', 'limit_share', 'response_entropy', 'generic_request_share', 'cross_role_request_similarity', 'persona_detail_leaks', 'calls', 'tokens')}
                   for arm in ARMS}
        path = Path(output) if output else settings.BASE_DIR / 'data' / 'reviewed' / 'runs' / f'{doc_id}-personas.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'doc_id': doc_id, 'as_of': doc['published_on'], 'model': base.model, 'selected_role': role,
                                    'analysis': base.analysis, 'personas': base.personas, 'summary': summary, 'runs': runs},
                                   ensure_ascii=False, indent=1), encoding='utf-8')
        for key in summary['persona']:
            self.stdout.write(f"{key:32} 페르소나 {summary['persona'][key]!s:>10}   없음 {summary['none'][key]!s:>10}")
        self.stdout.write(f'{path} 저장')
