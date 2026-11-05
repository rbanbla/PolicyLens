"""Reconcile workbook quotations against saved pages and their direct attachments."""
import csv
import re
import unicodedata
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2] / 'data/b'
SOURCE_INDEX = ROOT / 'sources/collected/source_index.csv'
ADDITIONAL = ROOT / 'sources/collected/additional_manifest.csv'
OUT = ROOT / 'sources/collected/row_verification.csv'
WEB_ONLY = ROOT / 'sources/collected/web_only_sources.csv'

PARENTS = {
    'HEPI 2026 student survey': 'www.hepi.ac.uk/reports/student-generative-ai-survey-2026',
    'HEPI 2026 weighted tables': 'www.hepi.ac.uk/reports/student-generative-ai-survey-2026',
    'HEPI 2026 weighted data': 'www.hepi.ac.uk/reports/student-generative-ai-survey-2026',
    'MOE university AI ethics guideline': 'www.moe.go.kr/boardCnts/viewRenew.do',
    'UMD AI guidelines': 'ai.umd.edu/resources-guidelines/guidelines-for-use',
    'Dongseo instructor guide': 'ctl.dsu.ac.kr/ctl/index.php',
    'Ithaka instructional practice report': 'sr.ithaka.org/publications/generative-ai-and-postsecondary-instructional-practices',
    'LSE position on generative AI': 'info.lse.ac.uk/staff/divisions/Eden-Centre',
    'LSE guidelines for generative AI': 'info.lse.ac.uk/staff/divisions/Eden-Centre',
    'SJSU academic integrity policy': 'www.sjsu.edu/studentconduct/conduct-processes/academic-integrity',
    'UBC graduate discussion prompts': 'www.grad.ubc.ca/current-students/student-responsibilities/use-generative-ai',
    'UBC graduate program guide': 'www.grad.ubc.ca/current-students/student-responsibilities/use-generative-ai',
    'IJERE study full text': 'ijere.iaescore.com/index.php/IJERE/article/view/35461',
    'IJERE study PDF': 'ijere.iaescore.com/index.php/IJERE/article/view/35461',
}

# The five sites below were readable in browser search, but rejected local downloads.
# These six exact phrases were checked against their named official pages on 2026-11-04.
WEB_QUOTE_VERIFIED = {
    ('Student views', '17'), ('Faculty views', '16'),
    ('Faculty views', '17'), ('Faculty views', '18'), ('Faculty views', '19'),
    ('Staff views', '9'),
}


def normalized(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(value or '')).lower()).strip()


def main():
    page_rows = list(csv.DictReader(SOURCE_INDEX.open(encoding='utf-8-sig')))
    extras = list(csv.DictReader(ADDITIONAL.open(encoding='utf-8-sig')))
    workbook = load_workbook(ROOT / 'sources/PolicyLens_Sources.xlsx', read_only=True, data_only=True)
    quotes = {}
    for sheet in workbook:
        for number, cells in enumerate(sheet.values, 1):
            if number > 1 and any(cell is not None for cell in cells):
                quotes[(sheet.title, str(number))] = normalized((list(cells) + [None] * 7)[3])
    cache = {}

    def content(path):
        if path and path not in cache:
            cache[path] = normalized((ROOT / path).read_text(encoding='utf-8'))
        return cache.get(path, '')

    fields = ['sheet', 'row', 'topic', 'source_type', 'url', 'collection_status', 'page_path',
              'page_text_path', 'page_quote_match', 'attachment_paths', 'attachment_quote_match',
              'matching_attachment_paths', 'web_verified', 'web_quote_match',
              'any_exact_quote_match', 'review_note']
    with OUT.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in page_rows:
            quote = quotes[(row['sheet'], row['row'])]
            page_match = bool(quote and quote in content(row['text_path']))
            related = [x for x in extras if x['kind'] == 'attachment' and
                       x['status'] == 'downloaded' and PARENTS.get(x['parent_or_label'], '') in row['url']]
            attachment_paths = [x['raw_path'] for x in related]
            matching = [x['raw_path'] for x in related if quote and quote in content(x['text_path'])]
            available = row['status'] in ('downloaded', 'downloaded_alternate')
            web_checked = not available and row['url'].startswith((
                'https://www.hepi.ac.uk/', 'https://www.fastcompany.com/',
                'https://www.monash.edu/', 'https://www.ox.ac.uk/',
                'https://www.fas.harvard.edu/'))
            web_match = (row['sheet'], row['row']) in WEB_QUOTE_VERIFIED
            if not available:
                note = 'page viewed on the web, but original bytes could not be saved locally' if web_checked else 'source URL not saved; web access or alternate source review required'
            elif not page_match and not matching:
                note = 'exact quotation not found; wording, article PDF, or extraction needs review'
            else:
                note = ''
            writer.writerow(dict(sheet=row['sheet'], row=row['row'], topic=row['topic'],
                source_type=row['source_type'], url=row['url'], collection_status=row['status'],
                page_path=row['raw_path'], page_text_path=row['text_path'],
                page_quote_match='yes' if page_match else 'no' if available else 'not_checked',
                attachment_paths=' | '.join(attachment_paths),
                attachment_quote_match='yes' if matching else 'no' if related else 'not_checked',
                matching_attachment_paths=' | '.join(matching),
                web_verified='yes' if web_checked else 'no',
                web_quote_match='yes' if web_match else 'not_applicable' if not quote else 'not_checked',
                any_exact_quote_match='yes' if page_match or matching else 'yes_web_only' if web_match else 'no' if available else 'not_checked',
                review_note=note))
    verified = list(csv.DictReader(OUT.open(encoding='utf-8-sig')))
    web_urls = sorted({row['url'] for row in verified if row['web_verified'] == 'yes'})
    with WEB_ONLY.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(('url', 'workbook_rows', 'exact_quote_rows', 'local_download_status', 'note'))
        for url in web_urls:
            related = [row for row in verified if row['url'] == url]
            writer.writerow((url, ' | '.join(f"{row['sheet']}:{row['row']}" for row in related),
                             ' | '.join(f"{row['sheet']}:{row['row']}" for row in related if row['web_quote_match'] == 'yes'),
                             related[0]['collection_status'],
                             'Official page viewed on the web; local original bytes unavailable'))
    print(f'Wrote {len(page_rows)} row checks to {OUT}')


if __name__ == '__main__':
    main()
