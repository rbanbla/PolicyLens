"""Collect the public URLs listed in the user workbook without activating B evidence."""
import argparse
import csv
import hashlib
import html
import logging
import re
import threading
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from openpyxl import load_workbook
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2] / 'data/b'
WORKBOOK = ROOT / 'sources/PolicyLens_Sources.xlsx'
RAW = ROOT / 'sources/collected/raw'
TEXT = ROOT / 'sources/collected/text'
INDEX = ROOT / 'sources/collected/source_index.csv'
URL_INDEX = ROOT / 'sources/collected/url_manifest.csv'
MAX_BYTES = 30 * 1024 * 1024
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.8,ko;q=0.6',
}
host_locks = defaultdict(threading.Lock)
logging.getLogger('pypdf').setLevel(logging.ERROR)


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ignored = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.ignored += 1
        elif tag in ('p', 'div', 'li', 'h1', 'h2', 'h3', 'h4', 'br', 'tr'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.ignored = max(0, self.ignored - 1)
        elif tag in ('p', 'div', 'li', 'h1', 'h2', 'h3', 'h4', 'tr'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)

    def text(self):
        return '\n'.join(line.strip() for line in html.unescape(''.join(self.parts)).splitlines() if line.strip())


def normalized(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(value or '')).lower()).strip()


def filename(url, mime):
    parsed = urlparse(url)
    stem = re.sub(r'[^a-z0-9]+', '_', (parsed.netloc + parsed.path).lower()).strip('_')[:95]
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    path_suffix = Path(parsed.path).suffix.lower()
    if mime.startswith('application/pdf') or path_suffix == '.pdf':
        ext = '.pdf'
    elif 'spreadsheet' in mime or path_suffix == '.xlsx':
        ext = '.xlsx'
    elif 'wordprocessingml' in mime or path_suffix == '.docx':
        ext = '.docx'
    else:
        ext = '.html'
    return f'{stem}_{digest}{ext}'


def decode_page(data, content_type):
    match = re.search(r'charset=([\w-]+)', content_type, re.I)
    charset = match.group(1) if match else 'utf-8'
    try:
        return data.decode(charset)
    except (LookupError, UnicodeError):
        return data.decode('utf-8', errors='replace')


def collect(url, headers=HEADERS):
    result = dict(url=url, status='', http_status='', final_url='', content_type='', bytes=0,
                  sha256='', raw_path='', text_path='', text_chars=0, error='')
    host = urlparse(url).netloc
    try:
        # Serialise requests to each host while allowing independent sites to proceed.
        with host_locks[host]:
            request_url = quote(url, safe=':/?&=%#')
            with urlopen(Request(request_url, headers=headers), timeout=25) as response:
                result['http_status'] = response.status
                result['final_url'] = response.url
                result['content_type'] = response.headers.get('Content-Type', '')
                data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            result['status'] = 'too_large'
            result['error'] = f'exceeds {MAX_BYTES} bytes'
            return result
        mime = result['content_type'].split(';')[0].lower().strip()
        if data.startswith(b'%PDF-'):
            kind = 'pdf'
        elif data.startswith(b'PK\x03\x04'):
            kind = 'xlsx' if 'spreadsheet' in mime or urlparse(url).path.lower().endswith('.xlsx') else 'zip'
        elif mime in ('text/html', 'application/xhtml+xml') or data.lstrip().lower().startswith((b'<!doctype html', b'<html')):
            kind = 'html'
        elif mime.startswith('text/'):
            kind = 'text'
        else:
            result['status'] = 'unsupported_content'
            result['error'] = f'unrecognised content: {mime}; first bytes {data[:12]!r}'
            return result

        page = decode_page(data, result['content_type']) if kind in ('html', 'text') else ''
        title_match = re.search(r'<title[^>]*>(.*?)</title>', page, re.I | re.S) if kind == 'html' else None
        page_title = normalized(html.unescape(title_match.group(1))) if title_match else ''
        if kind == 'html' and (
            any(marker in page_title for marker in ('just a moment', 'access denied', 'security check'))
            or (len(data) < 10_000 and 'enable javascript and cookies' in page.lower())
        ):
            result['status'] = 'access_gate'
            result['error'] = 'Downloaded response is an access-check page'
            return result

        name = filename(url, result['content_type'])
        if kind == 'zip':
            name = Path(name).with_suffix('.zip').name
        elif kind == 'text':
            name = Path(name).with_suffix('.txt').name
        raw_path = RAW / name
        RAW.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(data)
        result.update(status='downloaded', bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                      raw_path=str(raw_path.relative_to(ROOT)))

        extracted = ''
        if kind == 'html':
            parser = PageText()
            parser.feed(page)
            extracted = parser.text()
        elif kind == 'text':
            extracted = page
        elif kind == 'pdf':
            try:
                extracted = '\n'.join(p.extract_text() or '' for p in PdfReader(raw_path).pages)
            except Exception as exc:
                result['error'] = f'PDF text extraction failed: {type(exc).__name__}: {exc}'[:250]
        if extracted:
            TEXT.mkdir(parents=True, exist_ok=True)
            text_path = TEXT / (Path(name).stem + '.txt')
            text_path.write_text(extracted, encoding='utf-8')
            result['text_path'] = str(text_path.relative_to(ROOT))
            result['text_chars'] = len(extracted)
        return result
    except HTTPError as exc:
        result.update(status='http_error', http_status=exc.code, error=str(exc)[:250])
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        result.update(status='network_error', error=f'{type(exc).__name__}: {exc}'[:250])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--safari', action='store_true')
    parser.add_argument('--index-only', action='store_true')
    args = parser.parse_args()
    workbook = load_workbook(WORKBOOK, read_only=True, data_only=True)
    rows = []
    for sheet in workbook:
        for number, cells in enumerate(sheet.values, 1):
            if number == 1 or not any(cell is not None for cell in cells):
                continue
            values = (list(cells) + [None] * 7)[:7]
            rows.append(dict(sheet=sheet.title, row=number, topic=values[1] or '',
                             source_type=values[2] or '', quote=values[3] or '', url=str(values[6] or '').strip()))
    urls = sorted({row['url'] for row in rows if row['url']})
    results = {}
    if (args.retry_failed or args.index_only) and URL_INDEX.exists():
        with URL_INDEX.open(encoding='utf-8-sig') as handle:
            results = {row['url']: row for row in csv.DictReader(handle)}
        urls_to_fetch = [] if args.index_only else [url for url in urls if results.get(url, {}).get('status') not in ('downloaded', 'downloaded_alternate')]
    else:
        urls_to_fetch = urls
    headers = dict(HEADERS)
    if args.safari:
        headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Version/17.4 Safari/605.1.15'
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(collect, url, headers): url for url in urls_to_fetch}
        for future in as_completed(futures):
            result = future.result()
            results[result['url']] = result
            print(f"{len(results):2}/{len(urls)} {result['status']:19} {urlparse(result['url']).netloc}", flush=True)

    URL_INDEX.parent.mkdir(parents=True, exist_ok=True)
    url_fields = ['url', 'status', 'http_status', 'final_url', 'content_type', 'bytes', 'sha256',
                  'raw_path', 'text_path', 'text_chars', 'error']
    with URL_INDEX.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=url_fields)
        writer.writeheader()
        writer.writerows(results[url] for url in urls)

    row_fields = ['sheet', 'row', 'topic', 'source_type', 'url', 'status', 'raw_path',
                  'text_path', 'quote_in_downloaded_text', 'http_status', 'error']
    text_cache = {}
    with INDEX.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=row_fields)
        writer.writeheader()
        for row in rows:
            result = results[row['url']]
            text_path = result['text_path']
            if text_path and text_path not in text_cache:
                text_cache[text_path] = normalized((ROOT / text_path).read_text(encoding='utf-8'))
            quote = normalized(row['quote'])
            match = 'yes' if quote and quote in text_cache.get(text_path, '') else 'no' if text_path else 'not_checked'
            writer.writerow({key: (match if key == 'quote_in_downloaded_text' else
                                   result[key] if key in result else row[key]) for key in row_fields})
    print('URL statuses:', dict(Counter(result['status'] for result in results.values())))
    print('Row quote checks:', dict(Counter(row['quote_in_downloaded_text'] for row in csv.DictReader(INDEX.open(encoding='utf-8-sig')))))


if __name__ == '__main__':
    main()
