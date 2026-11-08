import json
from datetime import date
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from server.agents.planning import role_count
from server.agents.progress import is_complete
from server.agents.runner import advance, analyze, baseline, create_run
from server.models import ReviewRun
from server.agents.tools.policy_facts import digest
from server.agents.schemas import ANALYSIS
from server.agents.validation import validate_shape, validate_roles


class Command(BaseCommand):
    help = '평가 문서를 서비스와 같은 파이프라인으로 실행하고 data/reviewed/runs에 저장한다.'

    def add_arguments(self, parser):
        parser.add_argument('doc_id')
        parser.add_argument('--role', type=int, default=0, help='입장을 맡을 역할 번호')
        parser.add_argument('--reference-run', help='같은 문서·모델·프롬프트 실행의 역할 분석과 기준선을 재사용')
        parser.add_argument('--structured-facts', action='store_true', help='검수된 구조화 정책 사실을 함께 조회')
        parser.add_argument('--no-sources', action='store_true', help='서버 자료 없이 문서만 읽는 조건')

    def handle(self, doc_id, role, no_sources, structured_facts=False, reference_run=None, **options):
        if no_sources and structured_facts:
            raise CommandError('--no-sources와 --structured-facts는 함께 사용할 수 없습니다.')
        data = settings.BASE_DIR / 'data'
        docs = [json.loads(line) for line in (data / 'reviewed' / 'documents.jsonl').read_text().splitlines()]
        doc = next((doc for doc in docs if doc['doc_id'] == doc_id), None)
        if doc is None or not doc['published_on']:
            raise CommandError(f'{doc_id}: documents.jsonl에 발행일이 있는 문서가 아닙니다.')
        if any(doc.get('gate', {}).get(k) != 'pass' for k in ('technical', 'rights')) or doc.get('external_send_ok') is not True:
            raise CommandError('기술·권리·외부 전송 게이트를 통과한 문서만 평가할 수 있습니다.')
        pages = [page['text'] for page in json.loads((data / 'processed' / doc_id / 'pages.json').read_text())]
        reference = None
        if reference_run:
            try:
                reference = json.loads(Path(reference_run).read_text())
                if any(reference.get(k) != v for k, v in {'doc_id': doc_id, 'as_of': doc['published_on'], 'document_hash': digest(pages)}.items()):
                    raise ValueError('참조 실행의 문서·시점·해시가 다릅니다.')
                validate_shape(reference['analysis'], ANALYSIS)
                validate_roles(pages, reference['analysis'])
                if reference['analysis']['status'] != 'ok' or reference['selected_role'] != role or not isinstance(reference['baseline'], str) or not reference['baseline'].strip():
                    raise ValueError('참조 실행의 역할 또는 기준선이 잘못되었습니다.')
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise CommandError(str(exc)) from exc
        run = create_run('evaluate', doc['title'], pages)
        prompt_hash = digest(run.prompts)
        provider_hash = digest(run.provider)
        run.as_of = date.fromisoformat(doc['published_on'])
        run.structured_facts = structured_facts
        if no_sources:
            run.prompts.pop('sources')
        run.save()
        try:
            if reference:
                if any(reference.get(k) != v for k, v in {'model': run.model, 'prompt_hash': prompt_hash, 'provider_hash': provider_hash}.items()):
                    raise CommandError('참조 실행의 모델·제공자·프롬프트가 다릅니다.')
                run.analysis = reference['analysis']
                run.save(update_fields=['analysis'])
            else:
                analyze(run)
            if not 0 <= role < role_count(run):
                raise CommandError('선택한 역할 번호가 범위를 벗어납니다.')
            run.selected_role = role
            run.save(update_fields=['selected_role'])
            while not is_complete(run):
                advance(run)
            if reference:
                run.baseline = reference['baseline']
            else:
                baseline(run)
            arm = 'document' if no_sources else 'structured' if structured_facts else 'sources'
            folder = data / 'reviewed' / 'runs'
            folder.mkdir(exist_ok=True)
            path = folder / f'{doc_id}-{arm}.json'
            path.write_text(json.dumps({'doc_id': doc_id, 'arm': arm, 'as_of': doc['published_on'], 'model': run.model,
                                        'structured_facts': structured_facts, 'document_hash': digest(pages), 'prompt_hash': prompt_hash,
                                        'provider_hash': provider_hash, 'reused_analysis_and_baseline': bool(reference), 'analysis': run.analysis, 'selected_role': run.selected_role, 'steps': run.steps,
                                        'baseline': run.baseline, 'calls': run.calls}, ensure_ascii=False, indent=1))
        finally:
            ReviewRun.objects.filter(pk=run.pk).delete()  # Results live in the file; the service database stays user data only.
        self.stdout.write(f'{path} 저장, 호출 {len(run.calls)}회')
