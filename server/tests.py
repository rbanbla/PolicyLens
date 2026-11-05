from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import TestCase
from .models import Clause, MockRevision, MockTurn, StudyCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from io import BytesIO
from zipfile import ZipFile
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject
from .features.uploads import extract


class CaseTests(TestCase):
    def setUp(self):
        self.case = {"title":"가상 규정", "source":"테스트", "learning_goal":"해석", "question":"어떻게 적용하는가?",
                     "situation":"조별 과제", "clauses":[{"location":"1항","quote":"사용 도구를 기록한다."}]}
        self.user = get_user_model().objects.create_user("editor", is_staff=True)
        self.user.user_permissions.add(Permission.objects.get(codename="add_studycase"))
        self.client.force_login(self.user)

    def post(self):
        return self.client.post("/api/admin/cases", {"document":"사용 도구를 기록한다.","case":self.case}, content_type="application/json")

    def test_registration(self):
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(Clause.objects.count(), 1)
        self.case["clauses"][0]["quote"] = "없는 문장"
        self.assertEqual(self.post().status_code, 400)
        self.assertEqual(StudyCase.objects.count(), 1)

    def test_permissions(self):
        self.client.logout()
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.client.get("/research/").status_code, 302)
        self.client.force_login(get_user_model().objects.create_user("participant"))
        self.assertEqual(self.post().status_code, 403)

    def test_a_only(self):
        self.case["evidence_pack_id"] = 2
        self.assertEqual(self.post().status_code, 400)

    def test_demo_trace(self):
        call_command("seed_demo")
        call_command("seed_demo")
        self.assertEqual(MockTurn.objects.count(), 3)
        clause = MockRevision.objects.get().turn.clause
        self.assertIn(clause.quote, clause.case.document)


class LibraryTests(TestCase):
    def test_catalogue_and_issue(self):
        call_command("seed_demo")
        policy = StudyCase.objects.get()
        self.assertContains(self.client.get("/policies/"), policy.title)
        page = self.client.get(f"/policies/{policy.pk}/")
        self.assertContains(page, policy.clauses.get().issue["consequence"])
        self.assertContains(page, policy.document)
        self.assertEqual(self.client.get("/study/").status_code, 404)
        self.assertEqual(self.client.post("/", {"action":"resume"}).status_code, 405)
        policy.published = False
        policy.save()
        self.assertNotContains(self.client.get("/policies/"), policy.title)
        self.assertEqual(self.client.get(f"/policies/{policy.pk}/").status_code, 404)


class UploadTests(TestCase):
    document = "제1조 AI 도구 사용 시 도구명과 사용 범위를 공개한다."

    def upload(self):
        return self.client.post("/upload/", {"document": SimpleUploadedFile(
            "정책.txt", self.document.encode("utf-8"))})

    def test_upload_review_and_private_input(self):
        self.assertRedirects(self.upload(), "/review/")
        self.assertContains(self.client.get("/review/"), self.document)
        self.assertRedirects(Client().get("/review/"), "/")
        self.assertEqual(StudyCase.objects.count(), 0)
        self.assertContains(self.client.get("/review/"), "주요 내용 확인")
        self.assertNotContains(self.client.get("/review/"), 'name="quote"')
        self.assertNotContains(self.client.get("/review/"), 'name="situation"')
        self.assertRedirects(self.client.get("/perspectives/"), "/review/")
        self.assertRedirects(self.client.post("/review/", {"quote": "임의 쟁점", "situation": "임의 상황"}), "/perspectives/")
        self.assertNotIn("quote", self.client.session["policy_draft"])
        result_page = self.client.get("/perspectives/")
        self.assertContains(result_page, "이 정책에서 검토할 쟁점")
        self.assertNotContains(result_page, 'id="use-profiles"')
        self.assertNotContains(result_page, "쟁점 검토와 토론 실행")
        self.client.post("/upload/", {"text": "새로운 정책 문서 내용"})
        self.assertFalse(self.client.session["policy_draft"]["confirmed"])
        self.assertRedirects(self.client.get("/perspectives/"), "/review/")

    def test_reject_files_and_empty_input(self):
        for name, data in [("bad.exe", b"data"), ("bad.pdf", b"broken"), ("bad.docx", b"broken"), ("bad.txt", b"\xff"), ("empty.txt", b"")]:
            self.assertEqual(self.client.post("/upload/", {"document": SimpleUploadedFile(name, data)}).status_code, 400)
        self.assertEqual(self.client.post("/upload/", {}).status_code, 400)
        file = SimpleUploadedFile("large.txt", b"a")
        file.size = 11 * 1024 * 1024
        with self.assertRaisesMessage(ValueError, "10MB"):
            extract(file)

    def test_real_docx_and_pdf_extraction(self):
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>정책 원문</w:t></w:r></w:p></w:body></w:document>')
        self.assertEqual(extract(SimpleUploadedFile("policy.docx", buffer.getvalue()))[0]["text"], "정책 원문")
        writer = PdfWriter()
        page = writer.add_blank_page(300, 300)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 250 Td (Policy text) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        buffer = BytesIO()
        writer.write(buffer)
        self.assertIn("Policy text", extract(SimpleUploadedFile("policy.pdf", buffer.getvalue()))[0]["text"])

    def test_csrf_and_escaped_input(self):
        self.assertEqual(Client(enforce_csrf_checks=True).post("/upload/", {"text": "test"}).status_code, 403)
        self.client.post("/upload/", {"text": "<script>alert(1)</script>"})
        self.assertContains(self.client.get("/review/"), "&lt;script&gt;")
        self.assertNotContains(self.client.get("/review/"), "<script>alert")
