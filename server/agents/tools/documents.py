import re
from django.utils.translation import gettext as _
from pypdf import PdfReader
from pypdf.errors import PyPdfError

MIN_QUOTE = 6

def read_pages(upload, text):
    if upload:
        if upload.size > 10 * 1024 * 1024:
            raise ValueError(_('파일은 10MB 이하로 입력하세요.'))
        if upload.name.lower().endswith('.pdf'):
            try:
                document = PdfReader(upload)
                if len(document.pages) > 80:
                    raise ValueError(_('80쪽 이하 문서를 입력하세요.'))
                pages = [page.extract_text() or '' for page in document.pages]
            except PyPdfError as exc:
                raise ValueError(_('PDF를 읽을 수 없습니다. 손상되었거나 암호가 걸렸는지 확인하세요.')) from exc
        elif upload.name.lower().endswith('.txt'):
            pages = [upload.read().decode('utf-8-sig')]
        else:
            raise ValueError(_('PDF 또는 UTF-8 TXT를 입력하세요.'))
    else:
        pages = [text.strip()]
    if not ''.join(pages).strip() or sum(map(len, pages)) > 100000:
        raise ValueError(_('추출 가능한 본문을 10만 자 이내로 입력하세요. 이미지 PDF는 텍스트 변환이 필요합니다.'))
    return pages

def numbered_pages(pages):
    return [{'page': number, 'text': text} for number, text in enumerate(pages, 1)]

def clean(text):
    # Notices mix look-alike dots, tildes and invisible characters that a model never copies exactly.
    return re.sub(r'[\s"\'“”‘’「」『』·‧∙․ㆍ・･•:：~∼～〜\x00\ue000-\uf8ff]', '', text)

def align_citations(pages, citations):
    # Models cite the number printed in the document; the quote decides which stored page it is.
    texts = [clean(page) for page in pages]
    for citation in citations:
        quote = clean(citation['quote'])
        found = [number for number, text in enumerate(texts, 1) if quote and quote in text]
        if found and citation['page'] not in found:
            citation['page'] = found[0]

def check_quote(pages, citation):
    page, quote = citation['page'], citation['quote']
    if not 1 <= page <= len(pages):
        raise ValueError(_('인용 페이지 또는 내용이 잘못되었습니다.'))
    if len(clean(quote)) < MIN_QUOTE:
        raise ValueError(_('인용은 %(n)s자 이상의 원문 구간이어야 합니다.') % {'n': MIN_QUOTE})
    if clean(quote) not in clean(pages[page - 1]):
        # The wording goes back to the model on repair, so it has to name the quote to fix.
        raise ValueError(_('모델이 제시한 인용이 원문과 일치하지 않습니다: %(page)s쪽 "%(quote)s"') % {'page': page, 'quote': quote[:40]})
