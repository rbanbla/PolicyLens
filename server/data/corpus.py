"""Reproducible local corpus import. Raw research code/archives are never executed."""
import csv
import hashlib
import json
import re
from collections import Counter
from django.conf import settings
from ..models import ResearchAsset, Evidence, SyntheticProfile

ROOT = settings.BASE_DIR.parent
CORPUS = settings.BASE_DIR / "research/2026-11-02"
VERSION = "corpus-v1"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def category(path):
    name = path.name.lower()
    if "nemotron" in name: return "synthetic_profiles"
    if "policy_text" in path.parts or any(x in path.parts for x in ["KR", "INT", "REF"]): return "policy_context"
    if name.startswith(("surrey", "faculty", "students", "manchester")): return "opinion_dataset"
    if "PAPERS" in path.parts or "papers" in path.parts: return "methodology"
    if name.startswith(("hm_", "habermas", "argyle", "park", "zhang")): return "methodology_data"
    if name.startswith("asu_"): return "policy_context"
    return "research_reference"


def index_assets():
    metadata = {}
    for name in ["research_files.json", "previous_files.json", "university_sources.json", "papers.json"]:
        rows = json.loads((CORPUS / name).read_text())
        if not isinstance(rows, list): continue
        for row in rows:
            if isinstance(row, dict) and row.get("path"):
                p = (CORPUS / row["path"]).resolve()
                if p.is_relative_to(ROOT): metadata.setdefault(p, {}).update(row)
    decisions = {}
    with (CORPUS / "asset_decisions.tsv").open() as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            value = row["path_or_url"]
            if not value.startswith("http"):
                p = (CORPUS / value).resolve()
                if p.is_relative_to(ROOT):
                    decisions[p] = row["pilot_use"]
                    metadata.setdefault(p, {})
    # Include both collection rounds and extracted research repositories, not app secrets.
    for directory in [CORPUS, ROOT / "output/research"]:
        for p in directory.rglob("*"):
            if p.is_file() and not p.is_symlink() and not any(part.startswith('.') for part in p.relative_to(directory).parts):
                metadata.setdefault(p.resolve(), {})
    records = []
    for p, meta in sorted(metadata.items()):
        available = p.is_file() and not p.is_symlink()
        if p.name.startswith('.'): continue
        details = {"import_version": VERSION, "previous_decision": decisions.get(p, ""),
                   "ingestion": "catalogued", "original_metadata": meta}
        if available and p.suffix == ".parquet":
            import pyarrow.parquet as pq
            parquet = pq.ParquetFile(p)
            details.update(rows=parquet.metadata.num_rows, columns=parquet.schema.names, ingestion="schema_indexed")
        if available and p.suffix == ".zip":
            from zipfile import ZipFile, BadZipFile
            try:
                with ZipFile(p) as archive:
                    members = [info.filename for info in archive.infolist() if not info.is_dir()]
                details.update(archive_members=len(members), member_sample=members[:50], ingestion="archive_indexed")
            except BadZipFile:
                details.update(ingestion="unreadable_archive")
        if available and p.suffix in [".rar", ".pkl", ".rdata"]:
            details.update(ingestion="catalog_only", limitation="Binary/research artifact; not executed or deserialized into agent opinions.")
        records.append(ResearchAsset(path=str(p.relative_to(ROOT)), title=meta.get("title") or meta.get("scope") or p.name,
            category=category(p), source_url=meta.get("source_url") or "", available=available,
            size=p.stat().st_size if available else 0, sha256=meta.get("sha256") or "", metadata=details))
    ResearchAsset.objects.bulk_create(records, update_conflicts=True, unique_fields=["path"],
        update_fields=["title", "category", "source_url", "available", "size", "sha256", "metadata"], batch_size=500)
    return len(records)


def asset_for(path):
    asset = ResearchAsset.objects.get(path=str(path.resolve().relative_to(ROOT)))
    if path.suffix != ".parquet":
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(block)
        asset.sha256 = hasher.hexdigest()
        asset.metadata["checksum_status"] = "verified_on_import"
        asset.save(update_fields=["sha256", "metadata"])
    return asset


def evidence(asset, role, kind, locator, text, context):
    key = digest(f"{asset.path}:{role}:{kind}:{locator}:{text}")
    item, created = Evidence.objects.get_or_create(key=key, defaults={"asset": asset, "role": role, "kind": kind,
        "locator": locator, "text": text, "context": context, "managed": True, "present": True})
    if not created:
        item.managed, item.present = True, True
        item.context = context
        item.save(update_fields=["managed", "present", "context"])


def import_student_transcripts():
    from pypdf import PdfReader
    path = CORPUS / "DATA/surrey_focus.pdf"
    asset = asset_for(path)
    # Preserve interviewer context; only complete, speaker-labelled participant segments are eligible.
    group, question = "", ""
    for index, page in enumerate(PdfReader(path).pages, 1):
        text = page.extract_text() or ""
        match = re.search(r"Focus group\s+(\d+)", text, re.I)
        if match: group = match.group(1)
        parts = re.split(r"(?m)^\s*(Interviewer|Part\d+)\s*$", text)
        for i in range(1, len(parts) - 2, 2):
            speaker, body = parts[i], parts[i + 1].strip()
            if speaker == "Interviewer":
                question = body[:1000]
                continue
            if 60 <= len(body) <= 2200 and not re.search(r"[\w.+-]+@[\w.-]+", body):
                evidence(asset, "student", "participant_excerpt", f"PDF {index}쪽 / group {group} / {speaker} / segment {i}", body,
                    f"Surrey, UK higher education focus groups; CC BY 4.0. Not a Korean student representative. Interviewer context: {question}")


def import_faculty_aggregates():
    from openpyxl import load_workbook
    path = CORPUS / "DATA/faculty_1.xlsx"
    asset = asset_for(path)
    rows = list(load_workbook(path, read_only=True, data_only=True).active.values)
    headers, data = rows[0], rows[1:]
    # Questionnaire confirms these exact labelled Likert columns. No names/emails/free text sent.
    eligible = [r for r in data if str(r[3]).strip().lower() == "yes"]
    for col in range(5, 13):
        values = Counter(str(r[col]).strip() for r in eligible if r[col] is not None)
        body = json.dumps({"question": headers[col].strip(), "eligible_educators": len(eligible),
                           "valid_responses": sum(values.values()), "counts": dict(values)}, ensure_ascii=False)
        evidence(asset, "faculty", "survey_aggregate", f"Sheet1 column {col+1}; university educator=Yes; rows 2–{len(rows)}", body,
                 "Iatrellis educator survey, Zenodo 14790575, CC BY 4.0. Higher education educators, not necessarily professors. Aggregate responses, not individual quotations; location not established.")


def import_policies():
    rows = json.loads((CORPUS / "university_sources.json").read_text())
    for row in rows:
        if row.get("status") != "원문" or not row.get("text_path"): continue
        path = CORPUS / row["text_path"]
        if not path.is_file(): continue
        asset = asset_for(CORPUS / row["path"])
        # Paragraph chunks retain surrounding conditions, and never become the user's governing policy.
        text = path.read_text()
        for index, block in enumerate(re.split(r"\n\s*\n", text)):
            block = block.strip()
            if not 80 <= len(block) <= 1800: continue
            if not re.search(r"AI|인공지능|평가|공개|학습|assessment|disclos|privacy|integrity", block, re.I): continue
            evidence(asset, "administration", "institutional_proxy", f"{row['text_path']} paragraph {index+1}", block,
                f"{row.get('institution')}; region={row.get('group')}; official institutional guidance, NOT an administrator interview. Comparative reference only; not an obligation in the uploaded policy.")


def index_tabular():
    from openpyxl import load_workbook
    for name in ["students_1.xlsx", "faculty_1.xlsx", "manchester_66429761.csv"]:
        path = CORPUS / "DATA" / name
        asset = asset_for(path)
        if path.suffix == ".xlsx":
            sheet = load_workbook(path, read_only=True, data_only=True).active
            meta = {"rows": sheet.max_row - 1, "columns": list(next(sheet.values))}
        else:
            # Long-form repeated rows: count distinct participants explicitly.
            with path.open() as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                count, ids = 0, set()
                for row in reader:
                    count += 1
                    ids.add(row["id"])
                meta = {"rows": count, "participants": len(ids), "columns": reader.fieldnames}
        asset.metadata.update(meta, ingestion="schema_indexed", limitation="Raw coded responses require question/codebook mapping; not used as fabricated opinions.")
        asset.save(update_fields=["metadata"])


def import_profiles():
    import pyarrow.parquet as pq
    counts = Counter()
    for path in sorted((CORPUS / "DATA").glob("nemotron_train-*.parquet")):
        asset = asset_for(path)
        offset = 0
        # Deterministic candidate sample; all shard row counts are catalogued separately.
        for batch in pq.ParquetFile(path).iter_batches(batch_size=2048, columns=["uuid", "occupation", "education_level"]):
            for i, row in enumerate(batch.to_pylist()):
                occupation = str(row["occupation"] or "")
                role = "student" if "학생" in occupation else "faculty" if occupation.endswith("교수") else "administration" if occupation == "대학 행정조교" else None
                if role and counts[role] < 20:
                    SyntheticProfile.objects.update_or_create(key=row["uuid"], defaults={"asset": asset, "role": role,
                        "background": {"occupation": occupation, "education_level": row["education_level"], "synthetic": True},
                        "locator": f"parquet row {offset+i}"})
                    counts[role] += 1
            offset += batch.num_rows
            if counts["faculty"] >= 20 and counts["administration"] >= 20: break
    return dict(counts)


CONCEPTS = {
    "disclosure": ["공개", "기록", "표시", "출처", "disclos", "acknowledg", "record", "citation"],
    "assessment": ["평가", "과제", "성적", "채점", "assessment", "assignment", "grading", "feedback"],
    "privacy": ["개인정보", "보안", "privacy", "data collection", "personal data"],
    "fairness": ["공정", "접근", "형평", "fair", "access", "inclusiv"],
    "training": ["교육", "지원", "훈련", "training", "support", "teaching"],
    "ai": ["인공지능", "생성형", "chatgpt", "generative", " ai "]}


def tokens(text):
    text = " " + text.lower() + " "
    found = set(re.findall(r"[a-z]{3,}|[가-힣]{2,}", text))
    return found | {key for key, words in CONCEPTS.items() if any(w in text for w in words)}


def retrieve(document, role, limit=6):
    query = tokens(document)
    ranked = []
    for item in Evidence.objects.filter(active=True, present=True, role=role, asset__available=True).select_related("asset"):
        score = len(query & tokens(item.text))
        if score: ranked.append((score, item))
    ranked.sort(key=lambda row: (-row[0], row[1].key))
    if role == "administration":
        # Prefer actual administrator evidence as it becomes available. Proxies fill gaps only.
        actual = [row for row in ranked if row[1].kind != "institutional_proxy"][:limit]
        proxy = [row for row in ranked if row[1].kind == "institutional_proxy"]
        selected = []
        for region in ["region=KR", "region=INT"]:
            selected.extend([row for row in proxy if region in row[1].context][:limit//2])
        ranked = actual + sorted(selected, key=lambda row: (-row[0], row[1].key))
    return [{"id": row.key, "kind": row.kind, "text": row.text, "context": row.context,
             "locator": row.locator, "source": row.asset.source_url, "asset_path": row.asset.path, "source_sha256": row.asset.sha256}
            for _, row in ranked[:limit]]


def import_asu_policies():
    from zipfile import ZipFile
    path = CORPUS / "DATA/asu_41511.zip"
    asset = asset_for(path)
    with ZipFile(path) as archive:
        for info in archive.infolist():
            if not info.filename.endswith('.txt') or info.filename.startswith('__MACOSX') or info.file_size > 2_000_000: continue
            text = archive.read(info).decode('utf-8-sig', errors='replace')
            for index, block in enumerate(re.split(r"\n\s*\n", text)):
                block = block.strip()
                if not 80 <= len(block) <= 1800: continue
                if not re.search(r"AI|assessment|disclos|privacy|integrity", block, re.I): continue
                evidence(asset, "administration", "institutional_proxy", f"ZIP {info.filename} paragraph {index+1}", block,
                    "ASU US R1 university policy corpus; region=INT; institutional policy text, NOT administrator opinion. Comparative context only; may be an older policy version.")
