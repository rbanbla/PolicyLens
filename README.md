# PolicyLens v2

공공정책 문서에서 이해관계자를 추출하고, 역할별 입장과 토론으로 논쟁 지점을 찾아, 내 입장에서 주의할 조항과 역할별 의견서를 만드는 독립 Django 프로젝트다. 부동산, 세금, 청년 정책처럼 주제가 다른 문서를 같은 절차로 다룬다. 실제 모델 API를 사용하며 모의 응답은 테스트에서만 사용한다.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# .env에 API 키, 제공자, 모델 이름과 로컬 개발용 DJANGO_DEBUG=1 입력
.venv/bin/python manage.py migrate
.venv/bin/python manage.py load_personas  # Nvidia 페르소나 표본 3,000명, 처음 한 번
.venv/bin/python manage.py runserver 127.0.0.1:8001
```

영어 화면 문구는 `locale/en/LC_MESSAGES/django.po`에 있다. 문구를 고친 뒤 `.venv/bin/python manage.py makemessages -l en --ignore='.venv/*'`로 목록을 갱신하고 `msgfmt -o locale/en/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.po`로 컴파일한다.

## 배포 (VibeHub)

VibeHub GitLab 저장소의 main에 push하면 CI가 루트의 `Dockerfile`로 이미지를 만들고 `https://<app-id>.ai.hy.miwork.ai`에 배포한다. 컨테이너는 시작할 때마다 `migrate`와 `load_sources`를 실행한 뒤 waitress로 3000 포트에서 요청을 받는다. DEBUG는 기본으로 꺼져 있다.

1. VibeHub에서 웹 앱과 PostgreSQL DB를 만들고, 앱의 연결된 내부 리소스에서 DB를 연결한다. 환경변수 prefix는 `DB`로 둔다. 앱은 주입된 `DB_DATABASE_URL`을 읽는다. DB를 연결하지 않으면 컨테이너 안의 SQLite를 써서 재배포할 때 기록이 사라진다.
2. 런타임 설정에서 컨테이너 포트를 `3000`, 준비 상태 확인을 HTTP 경로 `/`로 둔다.
3. AI Agent 모델 키를 신청한다. 승인되면 `MINIAPP_LLM_BASE_URL`과 `MINIAPP_LLM_API_KEY`가 자동으로 주입되며, `OPENAI_*`를 따로 넣으면 그 값이 우선한다.
4. 환경변수를 넣는다. 바꾼 값은 배포 이력에서 재배포해야 반영된다.
   - Secret: `DJANGO_SECRET_KEY`(`python -c "import secrets; print(secrets.token_urlsafe(50))"`로 만든 값), `NEWEST_POLICY_KEY`(없으면 최신 정책 목록만 비어 보인다)
   - 일반: `DJANGO_ALLOWED_HOSTS=<app-id>.ai.hy.miwork.ai`, `POLICYLENS_API_MODE=chat_completions`, `POLICYLENS_SUMMARY_MODEL=<VibeHub에 등록된 모델명>`
5. 앱 설정의 "자동 배포가 되지 않아요"에 있는 `.gitlab-ci.yml`을 저장소 루트에 두고 push한다. 이 파일에는 앱 전용 Webhook 주소가 들어 있어 저장소마다 다르다.

서버 자료는 검수를 통과한 파일만 저장소에 들어 있다(`data/reviewed/documents.jsonl`, `data/reviewed/opinions.jsonl`, 통과한 문서의 `data/processed/<doc_id>/pages.json`). `data/`는 .gitignore 대상이므로 새로 통과한 문서는 `git add -f`로 추가하고, 검수에서 빠진 문서는 `git rm --cached`로 뺀다.

한 단계의 모델 호출이 1분을 넘을 수 있다. VibeHub 프록시가 먼저 응답을 끊으면 화면에 오류가 보이지만 서버는 그 단계를 끝까지 진행해 저장하므로 재시작 버튼으로 이어간다.

## 사용 흐름

화면은 문서 넣기 → 핵심 요약·입장 선택 → 쟁점 찾기 → 쟁점 토론 → 주의 조항의 다섯 페이지다. 역할 수는 문서마다 2~3명이고 역할마다 사용자에게 보이지 않는 가상 인물(NVIDIA Nemotron-Personas-Korea)을 붙인다. 토론은 쟁점마다 사용자 역할이 먼저 말하고(그 쟁점과 관련이 낮으면 관련된 첫 역할), 그다음 발언자와 쟁점을 닫을 때는 사회자 에이전트가 정한다. 발언 수는 정해져 있지 않으며 쟁점당 10개가 안전 상한이다. 모델 호출은 분석 1회와 검토 `2 + 쟁점마다 (2 × 발언 수)`회 안팎이다(발언 3개로 닫히면 쟁점당 6회, 쟁점 3개면 20회). 서버 자료를 쓰면 역할의 첫 발언과 최종 단계에 검색 호출이 더해진다. 실제 API 호출은 비용이 발생한다. UI 확인에는 `.env`에 `POLICYLENS_DUMMY=1`을 넣으면 모델과 정책브리핑 대신 더미 데이터를 쓴다(호출 비용 없음, 서버 재시작 불필요). 더미로 만든 실행은 더미 모드에서만 이어갈 수 있다.

입장을 선택하면 3페이지의 쟁점 정리가 자동 진행된다. 페이지를 넘기는 버튼을 누르면 4페이지의 쟁점 토론, 5페이지의 주의 조항 정리가 이어진다. 오류가 나면 멈추고 재시작 버튼으로 저장된 단계부터 이어간다. 세션 소유자만 검토에 접근한다.

5페이지는 수정 문구가 아니라 내 입장의 주의 조항, 확인할 것, 담당 기관에 물어볼 질문, 불확실한 부분을 보여준다. 역할별 의견서는 토론 결과를 서버가 조립하며 추가 호출이 없고 텍스트 파일로 내려받는다. 실제 제출은 사용자가 직접 한다.

## 비교 평가

5페이지의 **두 결과 비교하기**에서 **비교 결과 만들기**를 누르면 같은 문서와 입장으로 단일 프롬프트 답변을 만든다(호출 2회 추가: 단일 프롬프트 1회, 같은 형식으로 옮기기 1회). 두 결과를 A·B로 나란히 보고 평가를 저장하면 어느 쪽이 어떤 방식인지 공개된다. 평가 결과는 `.venv/bin/python manage.py dumpdata server.reviewrun --indent 2`로 내보낸다. 이 출력에는 문서 원문이 포함된다.

현재 입력은 PDF·TXT·붙여넣기를 지원한다. 실행 중 외부 호출은 동기식이며 DB 트랜잭션 안에서 진행한다(로컬은 SQLite, 배포는 PostgreSQL).

## 서버 자료

토론 에이전트와 최종 정리는 입력 문서 밖의 공개 자료를 서버에서 찾아 근거로 쓴다. `data/reviewed/documents.jsonl`과 `data/processed/`를 준비한 뒤 `.venv/bin/python manage.py load_sources`로 적재한다. 검수를 통과한 문서만 올라가고, 적재된 자료가 없으면 문서만 읽는다.

## 평가

`.venv/bin/python manage.py evaluate <doc_id>`는 문서 하나를 서비스와 같은 파이프라인으로 실행해 `data/reviewed/runs/`에 저장한다. 문서 발행일 이전의 정책 자료만 보며, `--no-sources`를 붙이면 서버 자료 없이 실행한다. `.venv/bin/python manage.py score`는 저장된 결과가 정답 초안의 쟁점을 언급하는지 키워드로 세며 사람 채점을 대신하지 않는다.

제품 계약은 docs/PRODUCT_PLAN.md, 작업 규칙은 AGENTS.md, 화면 규칙은 docs/DESIGN.md, 검증 기록은 docs/IMPLEMENTATION_STATUS.md, 데이터 수집과 평가는 docs/DATA_PLAN.md를 따른다. `.venv/bin/python manage.py test server`로 회귀 검증을 실행한다.

### DATA SOURCE
본 프로젝트는 다음 공공기관에서 제공하는 정책 정보를 활용한다.
 - 대한민국 정책브리핑 (https://www.korea.kr) - 정부 정책 발표, 보도자료 및 정책 관련 공식 문서 (최신 정책 문서 활용에 사용)
 - NVIDIA Nemotron-Personas-Korea (https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea, CC BY 4.0) - 역할에 붙이는 합성 페르소나
