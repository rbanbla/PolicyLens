"""Create role-specific, duplicate-free views over B evidence and workbook sources."""
import csv
import os
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'data/b'
ROLES = {
    'Student views': ('student', '학생'),
    'Faculty views': ('faculty', '교수'),
    'Staff views': ('administration', '학사행정'),
}
FIELDS = ['sheet', 'row', 'topic', 'source_type', 'url', 'collection_status',
          'any_exact_quote_match', 'page_path', 'page_text_path', 'attachment_paths',
          'matching_attachment_paths', 'review_note']


def link_file(relative_path, destination):
    source = (ROOT / relative_path).resolve()
    if not source.is_relative_to(ROOT.resolve()) or not source.is_file():
        raise ValueError(f'Invalid collected source path: {relative_path}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        if destination.resolve() != source:
            raise ValueError(f'Conflicting role link: {destination}')
    elif destination.exists():
        raise ValueError(f'File blocks role link: {destination}')
    else:
        destination.symlink_to(os.path.relpath(source, destination.parent))
    return destination


def main():
    rows = list(csv.DictReader((ROOT / 'sources/collected/row_verification.csv').open(encoding='utf-8-sig')))
    evidence = list(csv.DictReader((ROOT / 'roles/evidence_sources.csv').open(encoding='utf-8-sig')))
    for sheet, (role, label) in ROLES.items():
        home = ROOT / 'roles' / role
        selected = [row for row in rows if row['sheet'] == sheet]
        expected = set()
        for row in selected:
            for field, folder in [('page_path', 'raw'), ('page_text_path', 'text')]:
                if row[field]:
                    expected.add(link_file(row[field], home / 'candidates' / folder / Path(row[field]).name))
            for attachment in row['attachment_paths'].split(' | '):
                if attachment:
                    expected.add(link_file(attachment, home / 'candidates/attachments' / Path(attachment).name))

        # These directories contain only generated symlinks. Leave real user files untouched.
        for folder in ('raw', 'text', 'attachments'):
            directory = home / 'candidates' / folder
            if directory.exists():
                for item in directory.iterdir():
                    if item.is_symlink() and item not in expected:
                        item.unlink()

        home.mkdir(parents=True, exist_ok=True)
        with (home / 'candidate_rows.csv').open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows({field: row[field] for field in FIELDS} for row in selected)
        evidence_count = sum(int(item['evidence_count']) for item in evidence if item['role'] == role)
        local = sum(row['collection_status'] in ('downloaded', 'downloaded_alternate') for row in selected)
        exact = Counter(row['any_exact_quote_match'] for row in selected)
        (home / 'README.md').write_text(
            f'# {label} 자료\n\n'
            f'- 현재 B Evidence: {evidence_count}개. `evidence/`의 링크는 이 근거를 생성한 원본이다.\n'
            f'- 엑셀 후보: {len(selected)}행. 로컬 원문 연결 {local}행, 정확 문구 확인 {exact.get("yes", 0)}행, 웹에서만 문구 확인 {exact.get("yes_web_only", 0)}행.\n'
            '- `candidates/`는 아직 B 모델 입력이 아니다. `candidate_rows.csv`에서 엑셀 행, 원문 URL, 수집 상태와 인용 검증 결과를 확인한다.\n'
            '- 동일한 문서가 다른 역할에도 필요한 경우 링크만 중복된다. 실제 파일은 `../../sources/collected/`에 한 번 저장한다.\n',
            encoding='utf-8')
        print(f'{role}: {len(selected)} candidate rows, {evidence_count} active evidence, {len(expected)} source links')


if __name__ == '__main__':
    main()
