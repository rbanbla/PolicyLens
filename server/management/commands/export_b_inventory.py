"""Publish a reproducible map of the data B can actually retrieve."""
import csv
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from server.models import Evidence, ResearchAsset, SyntheticProfile


BASE = settings.BASE_DIR
CORPUS = BASE / 'research/2026-11-02'
OUT = BASE / 'data/b'


def write_csv(path, headers, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def link_source(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        if destination.resolve() != source.resolve():
            raise ValueError(f'Conflicting B source link: {destination}')
        return
    if destination.exists():
        raise ValueError(f'Existing file blocks B source link: {destination}')
    destination.symlink_to(os.path.relpath(source, destination.parent))


class Command(BaseCommand):
    help = 'Export active B source and archive indexes without deleting research originals.'

    def handle(self, *args, **options):
        active = Evidence.objects.filter(active=True, present=True, asset__available=True)
        counts = defaultdict(Counter)
        extraction_paths = set()
        for path, role, kind, locator in active.values_list('asset__path', 'role', 'kind', 'locator').iterator():
            if role not in ('student', 'faculty', 'administration'):
                raise ValueError(f'Unsupported B evidence role: {role}')
            counts[path][(role, kind)] += 1
            match = re.match(r'^(policy_text/\S+) paragraph \d+$', locator)
            if match:
                extraction_paths.add(str(Path('policylens/research/2026-11-02') / match.group(1)))

        profile_counts = Counter(SyntheticProfile.objects.values_list('asset__path', flat=True))
        source_rows = []
        inventory_rows = []
        for asset in ResearchAsset.objects.all().order_by('path').iterator():
            source = settings.BASE_DIR.parent / asset.path
            if asset.path in counts:
                bucket = 'b_evidence_source'
                for (role, kind), n in sorted(counts[asset.path].items()):
                    source_rows.append((role, kind, n, asset.path, asset.sha256, asset.source_url))
                    if source.is_relative_to(CORPUS):
                        link_source(source, OUT / 'roles' / role / 'evidence' / source.relative_to(CORPUS))
            elif asset.path in profile_counts:
                bucket = 'b_profile_source'
                link_source(source, OUT / 'shared/profiles' / source.name)
            elif asset.path in extraction_paths:
                bucket = 'b_extracted_policy_text'
                relative = source.relative_to(CORPUS)
                link_source(source, OUT / 'roles/administration/context/extracted_text' / relative)
            elif asset.path in {
                'policylens/research/2026-11-02/university_sources.json',
                'policylens/research/2026-11-02/DATA/faculty_2.pdf',
            }:
                bucket = 'b_source_metadata'
                role = 'faculty' if source.name == 'faculty_2.pdf' else 'administration'
                link_source(source, OUT / 'roles' / role / 'context' / source.name)
            else:
                bucket = 'research_reference_only'
            inventory_rows.append((asset.path, bucket, asset.size, asset.category, asset.available))

        write_csv(OUT / 'roles/evidence_sources.csv',
                  ('role', 'kind', 'evidence_count', 'asset_path', 'sha256', 'source_url'), source_rows)
        write_csv(OUT / 'archive/file_inventory.csv',
                  ('path', 'bucket', 'bytes', 'catalogue_category', 'available'), inventory_rows)
        self.stdout.write(f'B evidence source assets: {len(counts)}; profile assets: {len(profile_counts)}; '
                          f'file inventory: {len(inventory_rows)}')
