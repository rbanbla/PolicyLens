"""HTTP entry points for debate runs. Rules live in application/debates.py."""
import hashlib

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_safe

from ..application.debates import prepare_run, run_step, serialize
from ..application.documents import fingerprint
from ..integrations import transport
from ..integrations.transport import configuration, debate_model
from ..models import DebatePair


def owner(request):
    return hashlib.sha256(request.session.session_key.encode()).hexdigest()


@require_POST
@never_cache
def start(request):
    draft = request.session.get("policy_draft")
    if not draft or not draft.get("confirmed"):
        return JsonResponse({"error": "먼저 문서를 확인해 주세요."}, status=400)
    if request.POST.get("document_hash") != fingerprint(draft):
        return JsonResponse({"error": "문서가 바뀌었습니다. 새로고침해 주세요."}, status=409)
    key, default_model = configuration()
    if not key: return JsonResponse({"error": "서버의 OPENAI_API_KEY 설정이 필요합니다."}, status=503)
    pair = prepare_run(draft, owner(request), debate_model(default_model), request.POST.get("profiles") == "1")
    if pair is None: return JsonResponse({"error": "자료 DB가 비어 있거나 관련 근거를 찾지 못했습니다. import_corpus 후 다시 시도해 주세요."}, status=409)
    request.session["debate_pair"] = str(pair.pk)
    return JsonResponse(serialize(pair))


@require_POST
@never_cache
def step(request, pk):
    if not request.session.session_key: return JsonResponse({"error": "세션이 없습니다."}, status=404)
    with transaction.atomic():
        pair = get_object_or_404(DebatePair.objects.select_for_update(), pk=pk, owner=owner(request))
        if pair.status == "complete": return JsonResponse(serialize(pair))
        if pair.status == "failed" and request.POST.get("retry") != "1":
            return JsonResponse(serialize(pair), status=502)
        # An expected cursor prevents two tabs from advancing two stages on one click.
        if request.POST.get("cursor") != str(pair.cursor): return JsonResponse(serialize(pair))
        key, _ = configuration()
        if pair.spec.get("provider") != transport.identity():
            return JsonResponse({"error": "API 제공자 설정이 바뀌었습니다. 새 실행을 시작해 주세요."}, status=409)
        if not key: return JsonResponse({"error": "서버의 OPENAI_API_KEY 설정이 필요합니다."}, status=503)
        run_step(pair, key, parallel_discovery=request.POST.get("parallel_discovery") == "1")
    return JsonResponse(serialize(pair), status=502 if pair.status == "failed" else 200)


@require_safe
@never_cache
def status(request, pk):
    if not request.session.session_key: return JsonResponse({"error": "세션이 없습니다."}, status=404)
    return JsonResponse(serialize(get_object_or_404(DebatePair, pk=pk, owner=owner(request))))
