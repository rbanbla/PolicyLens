"""Read-only presentation of the previously validated mock-policy run."""
import json

from django.conf import settings
from django.shortcuts import render
from django.views.decorators.http import require_GET

DEMO_DIRECTIONS = {
    "제2조 과제에 사용한 AI 도구를 공개한다.": "도구명, 사용 목적, 과제에 반영한 부분을 기본 공개 항목으로 명시합니다.",
    "제1조 과제에 AI를 활용할 수 있다.": "학생의 검토 책임을 명시하고, AI 사용 범위와 공개 요건을 과제별로 미리 안내합니다.",
}


@require_GET
def snapshot(request):
    path = settings.BASE_DIR / "validation" / "LIVE_RUN_RESULT.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    finals = {call["condition"]: call["output"]["statements"]
              for call in result["calls"] if call["stage"] == "final"}
    issues = []
    for issue in result["issues"]:
        quote = issue["citation"]["quote"]
        variants = [dict(row, label=label)
                    for condition, label in [("A", "A · 역할별 검토"), ("B", "B · 자료 기반 잠정 검토")]
                    for row in finals.get(condition, []) if row["issue_id"] == issue["id"]]
        issues.append({
            "question": issue["question"],
            "quote": quote,
            "direction": DEMO_DIRECTIONS.get(quote),
            "variants": variants,
        })
    return render(request, "demo_snapshot.html", {"issues": issues})
