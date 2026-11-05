"""Register the user's source workbook as review candidates, not agent opinions."""
import csv
import hashlib
from pathlib import Path
from openpyxl import load_workbook
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from server.models import BSourceCandidate


class Command(BaseCommand):
    help = 'Import and reconcile the 91 workbook entries without activating them as B evidence.'

    @transaction.atomic
    def handle(self, *args, **options):
        source = settings.BASE_DIR / 'data/b/sources/PolicyLens_Sources.xlsx'
        crosswalk = settings.BASE_DIR / 'data/b/review/source_crosswalk.csv'
        verification = settings.BASE_DIR / 'data/b/sources/collected/row_verification.csv'
        checksum = hashlib.sha256(source.read_bytes()).hexdigest()
        with crosswalk.open(encoding='utf-8-sig') as handle:
            audit = {(row['시트'], int(row['엑셀 행'])): row for row in csv.DictReader(handle)}
        collected = {}
        if verification.exists():
            with verification.open(encoding='utf-8-sig') as handle:
                collected = {(row['sheet'], int(row['row'])): row for row in csv.DictReader(handle)}
        workbook = load_workbook(source, read_only=True, data_only=True)
        count = 0
        roles = {'Student views': 'student', 'Faculty views': 'faculty', 'Staff views': 'administration'}
        for sheet in workbook:
            if sheet.title not in roles:
                continue
            for number, row in enumerate(sheet.values, 1):
                if number == 1 or not any(cell is not None for cell in row):
                    continue
                question, topic, source_type, excerpt, reported, location, url = (list(row) + [None] * 7)[:7]
                review = audit[(sheet.title, number)]
                saved = collected.get((sheet.title, number), {})
                source_ids = [value.strip() for value in review['일치 수집 원문'].split(',') if value.strip()]
                defaults = dict(role=roles[sheet.title], topic=str(topic or ''), source_type=str(source_type or ''),
                    question=str(question or ''), original_excerpt=str(excerpt or ''),
                    reported_view=str(reported or ''), source_location=str(location or ''), source_url=str(url or ''),
                    audit_status=review['판정'], matched_source_ids=source_ids,
                    collection_status=saved.get('collection_status', 'not_checked'),
                    local_source_path=saved.get('page_path', ''), local_text_path=saved.get('page_text_path', ''),
                    quote_match=saved.get('any_exact_quote_match', 'not_checked'),
                    attachment_paths=[p for p in saved.get('attachment_paths', '').split(' | ') if p],
                    matching_attachment_paths=[p for p in saved.get('matching_attachment_paths', '').split(' | ') if p])
                BSourceCandidate.objects.update_or_create(workbook_sha256=checksum, sheet=sheet.title, row_number=number, defaults=defaults)
                count += 1
        self.stdout.write(f'B source candidates indexed: {count}; all remain review candidates')
