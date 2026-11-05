"""Read-only presentation of the previously validated mock-policy run."""
import json

from django.conf import settings
from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def snapshot(request):
    path = settings.BASE_DIR / "validation" / "LIVE_RUN_RESULT.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    finals = {call["condition"]: call["output"]["statements"]
              for call in result["calls"] if call["stage"] == "final"}
    issues = []
    for issue in result["issues"]:
        issues.append({
            "question": issue["question"],
            "quote": issue["citation"]["quote"],
            "a": next((row for row in finals.get("A", []) if row["issue_id"] == issue["id"]), None),
            "b": next((row for row in finals.get("B", []) if row["issue_id"] == issue["id"]), None),
        })
    return render(request, "demo_snapshot.html", {"issues": issues})
