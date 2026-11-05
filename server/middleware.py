"""Small shared gate for the short-lived public demo deployment."""
import base64
import binascii
import hmac
import os

from django.http import HttpResponse


class DemoBasicAuthMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/health/":
            return self.get_response(request)
        expected_user = os.environ.get("POLICYLENS_DEMO_USER", "demo")
        expected_password = os.environ.get("POLICYLENS_DEMO_PASSWORD", "")
        authorization = request.META.get("HTTP_AUTHORIZATION", "")
        try:
            scheme, encoded = authorization.split(" ", 1)
            if scheme.lower() != "basic":
                raise ValueError("scheme")
            user, password = base64.b64decode(encoded, validate=True).decode("utf-8").split(":", 1)
        except (ValueError, UnicodeDecodeError, binascii.Error):
            user, password = "", ""
        if (expected_password and hmac.compare_digest(user, expected_user)
                and hmac.compare_digest(password, expected_password)):
            return self.get_response(request)
        response = HttpResponse("데모 접속 정보가 필요합니다.", status=401)
        response["WWW-Authenticate"] = 'Basic realm="PolicyLens demo", charset="UTF-8"'
        response["Cache-Control"] = "no-store"
        return response
