"""Private, session-scoped document intake. No generated analysis at this stage."""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, BadZipFile
import xml.etree.ElementTree as ET

from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from pypdf import PdfReader
from ..application.documents import fingerprint

MAX_BYTES = 10 * 1024 * 1024
MAX_TEXT = 100_000


def extract(upload):
    if upload.size > MAX_BYTES:
        raise ValueError("파일은 10MB 이하로 올려주세요.")
    suffix = Path(upload.name).suffix.lower()
    data = upload.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("파일은 10MB 이하로 올려주세요.")
    try:
        if suffix == ".pdf":
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise ValueError("암호를 해제한 PDF를 올려주세요.")
            if len(reader.pages) > 80:
                raise ValueError("80쪽 이하의 문서를 올려주세요.")
            pages = [{"label": f"{i + 1}쪽", "text": page.extract_text() or ""}
                     for i, page in enumerate(reader.pages)]
            if any(not page["text"].strip() for page in pages):
                raise ValueError("텍스트를 읽을 수 없는 페이지가 있습니다. 스캔 문서는 OCR 처리하거나 원문을 직접 붙여넣어 주세요.")
        elif suffix == ".docx":
            with ZipFile(BytesIO(data)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > MAX_BYTES:
                    raise ValueError("문서 내용이 너무 큽니다.")
                xml = archive.read(info)
            if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                raise ValueError("지원하지 않는 문서 형식입니다.")
            root = ET.fromstring(xml)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            text = "\n".join("".join(p.itertext()) for p in root.findall(".//w:p", ns))
            pages = [{"label": "문서 전체", "text": text}]
        elif suffix == ".txt":
            pages = [{"label": "문서 전체", "text": data.decode("utf-8-sig")}]
        else:
            raise ValueError("PDF, DOCX, UTF-8 TXT 파일을 올려주세요.")
    except UnicodeDecodeError:
        raise ValueError("TXT 파일은 UTF-8 형식으로 저장해 주세요.")
    except ValueError:
        raise
    except (BadZipFile, KeyError, ET.ParseError):
        raise ValueError("DOCX 파일을 읽을 수 없습니다. 파일을 확인해 주세요.")
    except Exception:
        raise ValueError("파일을 읽을 수 없습니다. 텍스트를 직접 붙여넣을 수도 있습니다.")
    validate_text("\n\n".join(page["text"] for page in pages))
    return pages


def validate_text(text):
    if not text.strip():
        raise ValueError("문서에서 텍스트를 찾지 못했습니다. 원문을 직접 붙여넣어 주세요.")
    if "\x00" in text or len(text) > MAX_TEXT:
        raise ValueError("텍스트 형식을 확인해 주세요. 최대 10만 자까지 지원합니다.")


@require_http_methods(["POST"])
def upload(request):
    try:
        file = request.FILES.get("document")
        pasted = request.POST.get("text", "").strip()
        if file and pasted:
            raise ValueError("파일과 직접 입력 중 하나만 사용해 주세요.")
        if file:
            pages = extract(file)
            title = Path(file.name).stem[:250]
            filename = file.name
        else:
            validate_text(pasted)
            pages = [{"label": "문서 전체", "text": pasted}]
            title, filename = "직접 입력한 정책", "직접 입력"
        request.session.pop("debate_pair", None)
        request.session["policy_draft"] = {"title": title, "filename": filename,
            "pages": pages, "document": "\n\n".join(p["text"] for p in pages),
            "confirmed": False}
        return redirect("review")
    except ValueError as exc:
        return render(request, "home.html", {"error": str(exc), "text": request.POST.get("text", "")}, status=400)


@require_http_methods(["GET", "POST"])
@never_cache
def review(request):
    draft = request.session.get("policy_draft")
    if not draft:
        return redirect("home")
    if request.method == "POST":
        # Discovery belongs to the agents; do not accept client-supplied issues.
        draft.pop("quote", None)
        draft.pop("situation", None)
        draft["confirmed"] = True
        request.session["policy_draft"] = draft
        return redirect("perspectives")
    return render(request, "review.html", {"draft": draft, "document_hash": fingerprint(draft)})



@require_http_methods(["GET"])
@never_cache
def perspectives(request):
    draft = request.session.get("policy_draft")
    if not draft or not draft.get("confirmed"):
        return redirect("review")
    return render(request, "perspectives.html", {"draft": draft, "document_hash": fingerprint(draft)})


@require_http_methods(["GET"])
@never_cache
def revisions(request):
    draft = request.session.get("policy_draft")
    if not draft or not draft.get("confirmed"):
        return redirect("review")
    return redirect(reverse("perspectives") + "#debate-output")
