"""Collect official alternate pages and directly linked source documents."""
import csv
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from collect_sources import ROOT, URL_INDEX, collect

SAFARI = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Version/17.4 Safari/605.1.15',
    'Accept': 'text/html,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*;q=0.8',
}

ALTERNATES = {
    'https://enroll.slu.edu/provost/ai-guidelines/complete-ai-guidelines.php':
        'https://www.slu.edu/provost/ai-guidelines/complete-ai-guidelines.php',
    'https://www.ipr.sc.edu/about/offices_and_divisions/student_conduct_and_academic_integrity/academic_integrity/artificial_intelligence/index.php':
        'https://www.sc.edu/about/offices_and_divisions/student_conduct_and_academic_integrity/academic_integrity/artificial_intelligence/index.php',
    'https://www.jisc.ac.uk/reports/student-perceptions-of-ai-2025':
        'https://www.jisc.ac.uk/reports/student-perceptions-of-ai-2025/',
}

ATTACHMENTS = [
    ('HEPI 2026 student survey', 'https://www.hepi.ac.uk/wp-content/uploads/2026/03/HEPI-Report-199-Gen-AI-Survey-2026.pdf'),
    ('HEPI 2026 weighted tables', 'https://www.hepi.ac.uk/wp-content/uploads/2026/03/Third-version-of-2026-data-weighted-WOW-tables.xlsx'),
    ('HEPI 2026 weighted data', 'https://www.hepi.ac.uk/wp-content/uploads/2026/03/Third-version-of-2026-weighted-data.xlsx'),
    ('MOE university AI ethics guideline', 'https://www.moe.go.kr/boardCnts/fileDown.do?m=020501&s=moe&fileSeq=d68cc77373b94f02dd9dc2ecb5b5e9ed'),
    ('UMD AI guidelines', 'https://omc-system.files.svdcdn.com/production/files/ai/Academic-Guidelines-AI-Tools-at-UMD-Jan2025.pdf?dm=1756325611'),
    ('Dongseo instructor guide', 'https://ctl.dsu.ac.kr/ctl/_Data/생성형 A.I를 통한 부정행위 대응 방안_교강사 가이드.pdf'),
    ('Ithaka instructional practice report', 'https://sr.ithaka.org/wp-content/uploads/2024/06/SR-Report-Generative-AI-and-Postsecondary-Instructional-Practices-06202024-1.pdf'),
    ('LSE position on generative AI', 'https://info.lse.ac.uk/staff/divisions/Eden-Centre/Assets-EC/Documents/LSE-Position-on-Generative-AI-in-Education-2026-27-update.pdf'),
    ('LSE guidelines for generative AI', 'https://info.lse.ac.uk/staff/divisions/Eden-Centre/Assets-EC/Documents/AI-Sept-2026-docs/Guidelines-Generative-AI-2026-2027-CG-1.pdf'),
    ('SJSU academic integrity policy', 'https://www.sjsu.edu/studentconduct/docs/S26-10-Academic-Integrity-Policy.pdf'),
    ('UBC graduate discussion prompts', 'https://www.grad.ubc.ca/sites/default/files/doc/page/discussion_prompts_genai.pdf'),
    ('UBC graduate program guide', 'https://www.grad.ubc.ca/sites/default/files/doc/page/genai_gradstudies.pdf'),
    ('IJERE study full text', 'https://ijere.iaescore.com/index.php/IJERE/article/view/35461/14928'),
    ('IJERE study PDF', 'https://ijere.iaescore.com/index.php/IJERE/article/download/35461/14928'),
]


def main():
    with URL_INDEX.open(encoding='utf-8-sig') as handle:
        existing = list(csv.DictReader(handle))
    fields = list(existing[0])
    by_url = {row['url']: row for row in existing}
    tasks = [('alternate', original, url) for original, url in ALTERNATES.items()]
    tasks += [('attachment', label, url) for label, url in ATTACHMENTS]
    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(collect, url, SAFARI): (kind, label, url) for kind, label, url in tasks}
        for future in as_completed(futures):
            kind, label, url = futures[future]
            result = future.result()
            results.append(dict(kind=kind, parent_or_label=label, **result))
            print(f"{kind:10} {result['status']:20} {label}", flush=True)
            if kind == 'alternate' and result['status'] == 'downloaded':
                original = by_url[label]
                for key in fields:
                    if key != 'url':
                        original[key] = result[key]
                original['status'] = 'downloaded_alternate'

    with URL_INDEX.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(existing)
    extra_fields = ['kind', 'parent_or_label'] + fields
    path = ROOT / 'sources/collected/additional_manifest.csv'
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=extra_fields)
        writer.writeheader()
        writer.writerows(sorted(results, key=lambda row: (row['kind'], row['parent_or_label'])))
    print('Extra statuses:', dict(Counter(row['status'] for row in results)))


if __name__ == '__main__':
    main()
