import json
from datetime import date
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from server.agents.planning import role_count
from server.agents.progress import is_complete
from server.agents.runner import advance, analyze, baseline, create_run
from server.models import ReviewRun


class Command(BaseCommand):
    help = '평가 문서를 서비스와 같은 파이프라인으로 실행하고 data/reviewed/runs에 저장한다.'

    def add_arguments(self, parser):
        parser.add_argument('doc_id')
        parser.add_argument('--role', type=int, default=0, help='입장을 맡을 역할 번호')
        parser.add_argument('--no-sources', action='store_true', help='서버 자료 없이 문서만 읽는 조건')

    def handle(self, doc_id, role, no_sources, **options):
        data = settings.BASE_DIR / 'data'
        docs = [json.loads(line) for line in (data / 'reviewed' / 'documents.jsonl').read_text().splitlines()]
        doc = next((doc for doc in docs if doc['doc_id'] == doc_id), None)
        if doc is None or not doc['published_on']:
            raise CommandError(f'{doc_id}: documents.jsonl에 발행일이 있는 문서가 아닙니다.')
        pages = [page['text'] for page in json.loads((data / 'processed' / doc_id / 'pages.json').read_text())]
        run = create_run('evaluate', doc['title'], pages)
        run.as_of = date.fromisoformat(doc['published_on'])
        if no_sources:
            run.prompts.pop('sources')
        run.save()
        try:
            analyze(run)
            run.selected_role = min(role, role_count(run) - 1)
            run.save(update_fields=['selected_role'])
            while not is_complete(run):
                advance(run)
            baseline(run)
            arm = 'document' if no_sources else 'sources'
            folder = data / 'reviewed' / 'runs'
            folder.mkdir(exist_ok=True)
            path = folder / f'{doc_id}-{arm}.json'
            path.write_text(json.dumps({'doc_id': doc_id, 'arm': arm, 'as_of': doc['published_on'], 'model': run.model,
                                        'analysis': run.analysis, 'selected_role': run.selected_role, 'steps': run.steps,
                                        'baseline': run.baseline, 'calls': run.calls}, ensure_ascii=False, indent=1))
        finally:
            ReviewRun.objects.filter(pk=run.pk).delete()  # Results live in the file; the service database stays user data only.
        self.stdout.write(f'{path} 저장, 호출 {len(run.calls)}회')
