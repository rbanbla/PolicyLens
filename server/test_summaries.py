from copy import deepcopy
from io import BytesIO
import json
from unittest.mock import patch
from urllib.error import HTTPError

from django.test import TestCase, Client, SimpleTestCase
from .models import PolicySummary
from .features.summaries import SummaryError, fingerprint, generate, validate_summary

PAGES = [{"label": "1쪽", "text": "AI 사용 범위를 기록한다. 단, 맞춤법 교정은 제외한다."}]
RESULT = {"items": [{"title": "AI 사용 기록", "summary": "AI 사용 범위를 기록하되 맞춤법 교정은 제외합니다.",
                     "citations": [{"page": 1, "quote": PAGES[0]["text"]}]}]}


@patch("server.integrations.transport.provider", return_value=("https://api.openai.com/v1", "responses"))
class SummaryValidationTests(SimpleTestCase):
    def test_quotes_and_page_must_match(self, provider):
        self.assertEqual(validate_summary(deepcopy(RESULT), PAGES)["items"][0]["citations"][0]["label"], "1쪽")
        for citation in [{"page": 1, "quote": "자동으로 퇴학된다."}, {"page": 2, "quote": PAGES[0]["text"]}, {"page": True, "quote": "AI"}]:
            bad = deepcopy(RESULT)
            bad["items"][0]["citations"] = [citation]
            with self.assertRaises(SummaryError):
                validate_summary(bad, PAGES)

    def test_pdf_whitespace_is_recovered_as_exact_source_text(self, provider):
        pages = [{"label": "7쪽", "text": "AI  사용\n범위를 기록한다. 단, 교정은 제외한다."}]
        result = deepcopy(RESULT)
        result["items"][0]["citations"] = [{"page": 1, "quote": "AI 사용 범위를 기록한다. 단, 교정은 제외한다."}]
        recovered = validate_summary(result, pages)["items"][0]["citations"][0]
        self.assertEqual(recovered["quote"], pages[0]["text"])
        result["items"][0]["citations"] = [{"page": 1, "quote": "AI 사용 범위를 금지한다. 단, 교정은 제외한다."}]
        with self.assertRaises(SummaryError):
            validate_summary(result, pages)

    @patch("server.integrations.transport.urlopen")
    def test_responses_transport(self, open_url, provider):
        open_url.return_value = BytesIO(json.dumps({"status": "completed", "id": "resp_test", "usage": {"input_tokens": 10},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(RESULT)}]}]}).encode())
        result, response_id, usage = generate(PAGES, "test-key", "gpt-4.1")
        request = open_url.call_args.args[0]
        payload = json.loads(request.data)
        self.assertFalse(payload["store"])
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertIn(PAGES[0]["text"], payload["input"])
        self.assertEqual(response_id, "resp_test")
        self.assertEqual(result["items"][0]["title"], "AI 사용 기록")

    @patch("server.integrations.transport.urlopen")
    def test_errors_do_not_leak_provider_data(self, open_url, provider):
        open_url.side_effect = HTTPError("https://api.openai.com", 401, "secret-provider-error", {}, None)
        with self.assertRaises(SummaryError) as error:
            generate(PAGES, "test-key", "gpt-4.1")
        self.assertNotIn("secret-provider-error", str(error.exception))


@patch("server.features.summaries.configuration", return_value=("test-key", "gpt-4.1"))
class SummaryEndpointTests(TestCase):
    def setUp(self):
        self.client.post("/upload/", {"text": PAGES[0]["text"]})
        self.digest = fingerprint(self.client.session["policy_draft"])

    def post(self, **extra):
        return self.client.post("/api/summary/", {"document_hash": self.digest, **extra})

    @patch("server.features.summaries.generate", return_value=(RESULT, "resp_test", {}))
    def test_cache_scope_and_replaced_document(self, generate_mock, config):
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(generate_mock.call_count, 1)
        other = Client()
        other.post("/upload/", {"text": PAGES[0]["text"]})
        self.assertEqual(other.post("/api/summary/", {"document_hash": self.digest}).status_code, 200)
        self.assertEqual(generate_mock.call_count, 2)
        self.client.post("/upload/", {"text": "새 정책"})
        self.assertEqual(self.post().status_code, 409)
        self.assertEqual(generate_mock.call_count, 2)
        self.assertEqual(PolicySummary.objects.count(), 2)

    def test_missing_config_and_session_and_csrf(self, config):
        config.return_value = ("", "gpt-4.1")
        response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(PolicySummary.objects.count(), 0)
        self.assertEqual(Client().post("/api/summary/").status_code, 400)
        self.assertEqual(Client(enforce_csrf_checks=True).post("/api/summary/").status_code, 403)

    @patch("server.features.summaries.generate", side_effect=SummaryError("일시적 연결 실패"))
    def test_failure_requires_explicit_retry(self, generate_mock, config):
        self.assertEqual(self.post().status_code, 502)
        self.assertEqual(self.post().status_code, 502)
        self.assertEqual(generate_mock.call_count, 1)
        self.assertEqual(self.post(retry="1").status_code, 502)
        self.assertEqual(generate_mock.call_count, 2)
