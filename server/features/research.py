import json
from django import forms
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import permission_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from ..application.cases import register


class IntakeForm(forms.Form):
    document = forms.CharField(label="정책 본문", widget=forms.Textarea, strip=False)
    case = forms.JSONField(label="사례 JSON", widget=forms.Textarea)


@staff_member_required
@permission_required("server.add_studycase", raise_exception=True)
def intake(request):
    form = IntakeForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            obj, _ = register(**form.cleaned_data)
        except ValueError as exc:
            form.add_error(None, str(exc))
        else:
            return redirect("admin:server_studycase_change", obj.pk)
    return render(request, "intake.html", {"form": form})


@require_POST
def register_api(request):
    if not request.user.is_staff or not request.user.has_perm("server.add_studycase"):
        return JsonResponse({"error": "연구자 등록 권한이 필요합니다."}, status=403)
    try:
        body = json.loads(request.body)
        if not isinstance(body, dict) or not isinstance(body.get("document"), str):
            raise ValueError("document 문자열과 case 객체를 입력하세요.")
        obj, created = register(body["document"], body.get("case"))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"case_id": obj.pk, "fingerprint": obj.fingerprint}, status=201 if created else 200)
