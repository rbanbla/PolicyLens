import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from django.test import TestCase, Client
from .models import DebatePair, DebateCall, ResearchAsset, Evidence
from .features.debates import STEPS, check_citation
from .features.summaries import fingerprint, SummaryError
from .data.corpus import retrieve

TEXT = "과제에 사용한 AI 도구를 공개한다."
ISSUE = {"question": "공개 범위는 어디까지인가?", "interpretation_one": "도구명만 공개한다.",
         "interpretation_two": "사용 범위도 공개한다.", "consequence": "준수 부담과 평가 가능성이 달라진다.",
         "scenario": "가정: 교정과 문단 재배열을 함께 사용했다.", "citation": {"page": 1, "quote": TEXT}, "candidate_ids": []}


def mock_response(payload, key):
    call = DebateCall.objects.latest("id")
    context = json.loads(payload["input"])
    if call.stage in ["discover", "merge"]:
        issue = deepcopy(ISSUE)
        if call.stage == "merge": issue["candidate_ids"] = [h["output"]["issues"][0]["id"] for h in context["history"]]
        return {"issues": [issue]}, "test_response", {"input_tokens": 1}
    targets = []
    for history in context["history"]:
        if call.stage == "reply" and history["role"] != context["assigned_target_role"]: continue
        if call.stage == "review" and history["stage"] != "draft": continue
        if call.stage == "final" and history["stage"] != "review": continue
        targets.extend(s["id"] for s in history["output"]["statements"])
    return {"statements": [{"issue_id": "I1", "position": "公開範囲を明示する", "reason": "原文の範囲が曖昧である", "citations": [{"page": 1, "quote": TEXT}],
        "evidence_ids": [e["id"] for e in context["evidence"]], "target_ids": targets, "proposal": "사용 범위를 표시한다.",
        "verdict": "proposal", "unresolved": "과제별 예외"}]}, "test_response", {"input_tokens": 1}


@patch("server.features.debates.configuration", return_value=("test-key", "gpt-4.1"))
class DebateTests(TestCase):
    def test_pdf_quote_is_restored_to_literal_source(self, config):
        pair = SimpleNamespace(document={"pages": [{"text": "다른 정책 문구"}, {"text": "AI  사용\n범위를 공개한다."}]})
        citation = {"page": 1, "quote": "AI 사용 범위를 공개한다."}
        check_citation(citation, pair)
        self.assertEqual(citation["page"], 2)
        self.assertEqual(citation["quote"], pair.document["pages"][1]["text"])
        with self.assertRaises(ValueError):
            check_citation({"page": 1, "quote": "AI 사용 범위를 금지한다."}, pair)

    def test_escaped_newline_and_wrong_list_marker_keep_exact_source(self, config):
        pair = SimpleNamespace(document={"pages": [{"text": "2 사용 허용 (자유롭게 사용)\n- 수업 활동에서 AI 사용이 가능하다."}]})
        citation = {"page": 1, "quote": "③ 사용 허용 (자유롭게 사용)\\n- 수업 활동에서 AI 사용이 가능하다."}
        check_citation(citation, pair)
        self.assertIn(citation["quote"], pair.document["pages"][0]["text"])
        self.assertNotIn("③", citation["quote"])

    def setUp(self):
        asset = ResearchAsset.objects.create(path="test", title="Test", category="opinion_dataset")
        for role in ["student", "faculty", "administration"]:
            Evidence.objects.create(key=role, asset=asset, role=role,
                kind="institutional_proxy" if role=="administration" else "participant_excerpt",
                locator="row 1", text="AI disclosure assessment 공개 기록", context="region=KR; test fixture")
        self.client.post("/upload/", {"text": TEXT})
        self.client.post("/review/")
        self.digest = fingerprint(self.client.session["policy_draft"])

    def start(self):
        return self.client.post("/api/debates/start/", {"document_hash": self.digest})

    @patch("server.features.debates.run_model", side_effect=mock_response)
    def test_full_pair_and_condition_isolation(self, model, config):
        response = self.start()
        self.assertEqual(response.status_code, 200)
        pk = response.json()["id"]
        for step in range(len(STEPS)):
            response = self.client.post(f"/api/debates/{pk}/step/", {"cursor": str(step)})
            self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "complete")
        self.assertEqual(model.call_count, 26)
        self.assertEqual(DebateCall.objects.count(), 26)
        self.client.post(f"/api/debates/{pk}/step/", {"cursor": "26"})
        self.start()
        self.assertEqual(model.call_count, 26)
        for call in DebateCall.objects.exclude(condition="shared"):
            inputs = json.loads(call.request["input"])
            for h in inputs["history"]:
                self.assertTrue(all(s["id"].startswith(call.condition + "-") for s in h["output"]["statements"]))
            if call.condition == "A":
                self.assertEqual(inputs["evidence"], [])
                self.assertEqual(call.request["text"]["format"]["schema"]["properties"]["statements"]["items"]["anyOf"][0]["properties"]["evidence_ids"]["maxItems"], 0)
            else:
                allowed = call.request["text"]["format"]["schema"]["properties"]["statements"]["items"]["anyOf"][0]["properties"]["evidence_ids"]["items"]["enum"]
                self.assertEqual(set(allowed), {e["id"] for e in inputs["evidence"]})
            if call.condition == "B" and call.role != "moderator":
                self.assertEqual([e["id"] for e in inputs["evidence"]], [call.role])
        self.assertEqual(Client().get(f"/api/debates/{pk}/").status_code, 404)
        self.assertEqual(Client(enforce_csrf_checks=True).post("/api/debates/start/").status_code, 403)

    @patch("server.features.debates.run_model", side_effect=mock_response)
    def test_retry_and_duplicate_cursor(self, model, config):
        pk = self.start().json()["id"]
        url = f"/api/debates/{pk}/step/"
        self.client.post(url, {"cursor": "0"})
        self.client.post(url, {"cursor": "0"})
        self.assertEqual(model.call_count, 1)
        model.side_effect = SummaryError("test timeout")
        self.assertEqual(self.client.post(url, {"cursor": "1"}).status_code, 502)
        self.assertEqual(DebatePair.objects.get(pk=pk).cursor, 1)
        model.side_effect = mock_response
        self.assertEqual(self.client.post(url, {"cursor": "1", "retry": "1"}).status_code, 200)
        self.assertEqual(DebateCall.objects.get(step=1).attempts, 2)
        self.assertEqual(DebatePair.objects.get(pk=pk).cursor, 2)

    @patch("server.features.debates.run_model")
    def test_invalid_quote_not_committed(self, model, config):
        bad = deepcopy(ISSUE)
        bad["citation"]["quote"] = "없는 문장"
        model.return_value = {"issues": [bad]}, "test", {}
        pk = self.start().json()["id"]
        self.assertEqual(self.client.post(f"/api/debates/{pk}/step/", {"cursor": "0"}).status_code, 502)
        self.assertEqual(DebatePair.objects.get(pk=pk).cursor, 0)
        self.assertEqual(DebateCall.objects.get().response, {})

    @patch("server.features.debates.run_model", return_value=({"issues": []}, "test", {}))
    def test_no_issue_stops_without_fabricated_debate(self, model, config):
        pk = self.start().json()["id"]
        for cursor in range(4):
            response = self.client.post(f"/api/debates/{pk}/step/", {"cursor": str(cursor)})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "complete")
        self.assertEqual(model.call_count, 4)

    def test_no_key_or_wrong_document(self, config):
        config.return_value = ("", "gpt-4.1")
        self.assertEqual(self.start().status_code, 503)
        self.assertEqual(self.client.post("/api/debates/start/", {"document_hash": "stale"}).status_code, 409)


class CorpusTests(TestCase):
    def test_retrieval_separates_role_and_proxies(self):
        asset = ResearchAsset.objects.create(path="a", title="A", category="opinion_dataset")
        for index, role in enumerate(["student", "faculty", "administration"]):
            Evidence.objects.create(key=str(index), asset=asset, role=role, kind="institutional_proxy" if index==2 else "participant_excerpt", locator="p1",
                text="disclosure AI assessment", context="region=INT")
        self.assertEqual([e["id"] for e in retrieve("공개 기록 과제", "student")], ["0"])
        self.assertEqual(retrieve("공개 기록 과제", "administration")[0]["kind"], "institutional_proxy")
        self.assertEqual(retrieve("우주 궤도 역학", "student"), [])

    def test_actual_administrator_evidence_precedes_proxy(self):
        asset = ResearchAsset.objects.create(path="admin", title="Admin", category="opinion_dataset")
        Evidence.objects.create(key="actual", asset=asset, role="administration", kind="participant_excerpt", locator="p1", text="AI disclosure", context="Actual administrator interview fixture")
        Evidence.objects.create(key="proxy", asset=asset, role="administration", kind="institutional_proxy", locator="p2", text="AI disclosure assessment privacy training", context="region=KR")
        self.assertEqual(retrieve("공개 기록 과제 개인정보", "administration")[0]["id"], "actual")

    def test_reimport_preserves_manual_disable_and_filters_stale(self):
        from .data.corpus import evidence
        asset = ResearchAsset.objects.create(path="source", title="Source", category="opinion_dataset")
        evidence(asset, "student", "participant_excerpt", "page 1", "AI disclosure", "test context")
        item = Evidence.objects.get()
        item.active = False
        item.present = False
        item.save()
        evidence(asset, "student", "participant_excerpt", "page 1", "AI disclosure", "test context")
        item.refresh_from_db()
        self.assertEqual(Evidence.objects.count(), 1)
        self.assertFalse(item.active)
        self.assertTrue(item.present)
        self.assertEqual(retrieve("AI disclosure", "student"), [])
        item.active, item.present = True, False
        item.save()
        self.assertEqual(retrieve("AI disclosure", "student"), [])
