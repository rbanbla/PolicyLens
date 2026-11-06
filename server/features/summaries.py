"""HTTP entry point for the policy summary."""
import hashlib

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from ..application.documents import fingerprint
from ..application.summaries import PROMPT_VERSION, generate
from ..integrations import transport
from ..integrations.transport import ModelError, configuration
from ..models import PolicySummary


@require_POST
@never_cache
def summarize(request):
    draft = request.session.get("policy_draft")
    if not draft:
        return JsonResponse({"error": "먼저 정책 문서를 올려주세요."}, status=400)
    digest = fingerprint(draft)
    if request.POST.get("document_hash") != digest:
        return JsonResponse({"error": "문서가 변경됐습니다. 화면을 새로고침해 주세요."}, status=409)
    key, model = configuration()
    if not key:
        return JsonResponse({"error": "요약 서비스를 설정하고 있습니다. 서버의 OPENAI_API_KEY 설정이 필요합니다."}, status=503)
    cache_key = hashlib.sha256(f"{request.session.session_key}:{digest}:{model}:{PROMPT_VERSION}:{transport.identity()}".encode()).hexdigest()
    # Serialize requests for the same session/document so double clicks do not bill twice.
    with transaction.atomic():
        PolicySummary.objects.get_or_create(cache_key=cache_key, defaults={"model": model, "prompt_version": PROMPT_VERSION})
        record = PolicySummary.objects.select_for_update().get(cache_key=cache_key)
        if record.result:
            return JsonResponse(record.result)
        if record.error and request.POST.get("retry") != "1":
            return JsonResponse({"error": record.error}, status=502)
        try:
            record.result, record.response_id, record.usage = generate(draft["pages"], key, model)
            record.error = ""
        except ModelError as error:
            record.error = str(error)
        record.save()
        if record.error:
            return JsonResponse({"error": record.error}, status=502)
        return JsonResponse(record.result)
