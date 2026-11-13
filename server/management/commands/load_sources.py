import json
from django.conf import settings
from django.core.management.base import BaseCommand
from server.models import Source


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] if path.exists() else []


class Command(BaseCommand):
    help = 'data/reviewed의 검수 통과 자료를 서버 자료로 적재한다.'

    def handle(self, *args, **options):
        data = settings.BASE_DIR / 'data'
        loaded = {}
        for doc in rows(data / 'reviewed' / 'documents.jsonl'):
            if doc['gate']['technical'] == 'pass' and doc['gate']['rights'] == 'pass' and doc['external_send_ok']:
                # PostgreSQL cannot store NUL, which PDF text sometimes carries.
                pages = [page['text'].replace('\x00', '') for page in json.loads((data / 'processed' / doc['doc_id'] / 'pages.json').read_text(encoding='utf-8'))]
                loaded[doc['doc_id']] = {'kind': doc['kind'], 'title': doc['title'], 'issuer': doc['issuer'], 'version': doc['version'],
                                         'source_url': doc['source_url'], 'published_on': doc['published_on'] or None, 'pages': pages}
        for opinion in rows(data / 'reviewed' / 'opinions.jsonl'):
            parent = loaded.get(opinion['doc_id'])
            if parent and opinion['review_status'] == 'reviewed':
                loaded[opinion['opinion_id']] = {'kind': 'opinion', 'title': f'{parent["title"]} 관련 {opinion["source_type"]}',
                                                 'issuer': opinion['author_group'], 'version': opinion['submitted_on'],
                                                 'source_url': opinion['source_url'], 'published_on': opinion['submitted_on'] or None,
                                                 'pages': [opinion['text']]}
        for doc_id, fields in loaded.items():
            Source.objects.update_or_create(doc_id=doc_id, defaults=fields)
        # A document that lost its gate must stop reaching the model.
        Source.objects.exclude(doc_id__in=loaded).delete()
        self.stdout.write(f'서버 자료 {len(loaded)}건 적재')
