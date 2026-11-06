"""사용자가 제공한 UTF-8 정책 본문과 사례를 검증해 A의 실행 입력을 출력한다."""
import argparse
import hashlib
import json
from pathlib import Path

def prepare(document, case, spec):
    if not document.strip():
        raise ValueError("정책 본문이 비어 있습니다.")
    for key in ("title", "source", "situation", "learning_goal", "question"):
        if not isinstance(case.get(key), str) or not case[key].strip():
            raise ValueError(f"필수 사례 항목: {key}")
    clauses = case.get("clauses")
    if not isinstance(clauses, list) or not clauses:
        raise ValueError("원문에서 조항을 한 개 이상 선택하세요.")
    checked = []
    for index, clause in enumerate(clauses, 1):
        if not isinstance(clause, dict):
            raise ValueError("조항에는 위치와 발췌문이 필요합니다.")
        quote = clause.get("quote")
        location = clause.get("location")
        if not isinstance(location, str) or not location.strip():
            raise ValueError("조항 번호, 쪽수 또는 문단 위치를 입력하세요.")
        if not isinstance(quote, str) or not quote.strip() or quote not in document:
            raise ValueError("발췌문이 입력 문서의 원문과 일치해야 합니다.")
        checked.append({"id": f"C{index}", "location": location, "quote": quote})
    return {"condition": spec["condition"], "spec_version": spec["version"],
            "document_sha256": hashlib.sha256(document.encode()).hexdigest(),
            **{k: case[k] for k in ("title","source","situation","learning_goal","question")},
            "clauses": checked, "role_ids": list(spec["roles"])}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("case", type=Path)
    args = parser.parse_args()
    try:
        spec = json.loads(Path(__file__).with_name("study_v1.json").read_text(encoding="utf-8"))
        case = json.loads(args.case.read_text(encoding="utf-8"))
        if not isinstance(case, dict):
            raise ValueError("사례 파일은 JSON 객체여야 합니다.")
        result = prepare(args.document.read_text(encoding="utf-8-sig"), case, spec)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
