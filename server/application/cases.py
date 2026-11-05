import hashlib
import json
from django.conf import settings
from django.db import transaction
from phase1.prepare_case import prepare
from ..models import Clause, StudyCase


@transaction.atomic
def register(document, case):
    if not isinstance(case, dict):
        raise ValueError("사례는 JSON 객체여야 합니다.")
    if case.get("condition", "A") != "A" or any(k in case for k in ("evidence_ids", "evidence_pack", "evidence_pack_id")):
        raise ValueError("Phase 2는 실제 의견 자료가 없는 A 조건만 등록합니다.")
    spec = json.loads((settings.BASE_DIR/"phase1"/"study_v1.json").read_text(encoding="utf-8"))
    inputs = prepare(document, case, spec)
    for checked, original in zip(inputs["clauses"], case["clauses"]):
        issue = original.get("issue")
        if issue is not None:
            fields = ("question", "interpretation_one", "interpretation_two", "consequence")
            if not isinstance(issue, dict) or any(not isinstance(issue.get(k), str) or not issue[k].strip() for k in fields):
                raise ValueError("쟁점에는 질문, 두 해석, 판단이 달라지는 이유가 모두 필요합니다.")
            checked["issue"] = {k: issue[k].strip() for k in fields}
    if len(inputs["title"]) > 250:
        raise ValueError("제목은 250자 이내로 입력하세요.")
    payload = json.dumps([inputs, spec], sort_keys=True, ensure_ascii=False).encode()
    fields = {k: inputs[k] for k in ("title","source","situation","learning_goal","question","document_sha256")}
    obj, created = StudyCase.objects.get_or_create(fingerprint=hashlib.sha256(payload).hexdigest(),
        defaults={**fields, "document": document, "spec": spec})
    if created:
        Clause.objects.bulk_create([Clause(case=obj, key=c["id"], location=c["location"], quote=c["quote"], issue=c.get("issue", {}))
                                    for c in inputs["clauses"]])
    return obj, created
