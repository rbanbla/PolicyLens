import base64
import os
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from ..middleware import DemoBasicAuthMiddleware


class DemoGateTests(SimpleTestCase):
    def setUp(self):
        self.gate = DemoBasicAuthMiddleware(lambda request: HttpResponse("ok"))
        self.factory = RequestFactory()

    @patch.dict(os.environ, {"POLICYLENS_DEMO_USER": "demo", "POLICYLENS_DEMO_PASSWORD": "secret"})
    def test_public_page_requires_shared_credentials(self):
        self.assertEqual(self.gate(self.factory.get("/demo/")).status_code, 401)
        bad = base64.b64encode(b"demo:wrong").decode()
        self.assertEqual(self.gate(self.factory.get("/demo/", HTTP_AUTHORIZATION="Basic " + bad)).status_code, 401)
        good = base64.b64encode(b"demo:secret").decode()
        self.assertEqual(self.gate(self.factory.get("/demo/", HTTP_AUTHORIZATION="Basic " + good)).status_code, 200)

    @patch.dict(os.environ, {"POLICYLENS_DEMO_PASSWORD": "secret"})
    def test_health_probe_bypasses_gate(self):
        self.assertEqual(self.gate(self.factory.get("/health/")).status_code, 200)
