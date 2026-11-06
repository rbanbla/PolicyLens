# PolicyLens

사용자가 올린 대학 AI 정책을 모바일에서 확인하고, 학생·교수·학사행정 관점의 쟁점 탐색과 A/잠정 B 토론을 읽는 웹 앱이다. 설문은 웹 앱에서 받지 않고 별도 Google Forms로 진행한다.

## 실행

HCI 작업공간에서 `./policylens/start.sh`를 실행한다. `policylens/` 안에서는 `./start.sh`다. 최초 실행은 Python 3.11, 로컬 PostgreSQL과 가상환경을 준비하고 연구자 계정을 만든다. 접속 주소는 `http://127.0.0.1:8000/`, 종료는 터미널의 Ctrl+C다. DB·계정은 `.pgdata/`, API 설정은 `.env`에 유지된다.

`.env.example`을 참고해 `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `POLICYLENS_API_MODE`, `POLICYLENS_SUMMARY_MODEL`, `POLICYLENS_DEBATE_MODEL`을 설정한다. 키는 서버에서만 읽고 브라우저로 전달하지 않는다. 현재 연결 검증은 사용자 지정 Chat Completions 호환 엔드포인트와 `gpt-5.6-luna` 식별자로 수행했다. 상세 설정과 한계는 [데이터·호출 명세](docs/specs/DATA_CONNECTION.md)에 있다.

## 사용자 흐름

정책 PDF·DOCX·UTF-8 TXT를 올리거나 원문을 붙여 넣으면 문서의 주요 내용이 자동으로 표시된다. 요약 아래의 **쟁점 찾기**를 누르면 확인된 쟁점이 먼저 표시되고, 각 카드에서 원문, 수정 방향, A/잠정 B 비교와 토론을 읽을 수 있다. 텍스트 PDF 최대 80쪽, 파일 최대 10MB·추출 본문 10만 자를 지원한다. OCR은 아직 없다.

연구자 화면은 `/research/`, 자료 카탈로그는 `/sources/`, Django 관리 화면은 `/admin/`이다. 업로드 문서는 세션별로 보관하고 공개 정책 목록에 자동 게시하지 않는다. 토론은 단계별로 저장하며 실패한 단계는 명시적으로 재시도한다.

## 폴더와 데이터

- [문서 지도](docs/README.md): 모든 문서의 위치와 성격
- [작업환경 구조](docs/PROJECT_STRUCTURE.md): 서버 레이어, 데이터와 스크립트의 위치, 갱신 명령
- `data/b/`: 로컬 역할별 원본·사용자 엑셀 후보와 출처 교차 검토 자료. 배포 저장소에는 포함하지 않으며 선별된 DB 근거만 초기 데이터로 옮긴다.
- [쟁점 발견 계약](docs/specs/ISSUE_DISCOVERY.md) · [토론 프로토콜](docs/specs/DEBATE_PROTOCOL.md) · [단계별 체크리스트](docs/ROADMAP.md)

현재 잠정 B에는 학생 인터뷰 발화 309개, 교육자 설문 집계 8개, 대학 지침의 행정 대체 근거 2,689개가 있다. 새로 수집한 엑셀 91행은 출처 검토 후보로 등록했다. 역할 적합성을 검증하기 전까지 토론 Evidence에 자동 편입하지 않는다.

시연은 [데모 안내](docs/ops/DEMO.md)를 참고한다. 첫 화면의 **예시 결과 보기**는 `/demo/`에 저장된 모의 정책 검토 결과를 연다.

다른 기기에서 업로드·요약·토론까지 시연하는 무료 임시 경로는 [로컬 서버 + 외부 HTTPS 데모](docs/ops/LOCAL_ONLINE_DEMO.md)와 `./demo-online.sh`에 있다. 유료 상시 서버 대안은 [Render 배포 설계](docs/ops/DEPLOYMENT.md)에 준비했으며 서비스 생성은 하지 않았다.

## 검증

`PGHOST` 등 로컬 PostgreSQL 설정에서 `.venv/bin/python manage.py test server`를 실행한다. 현재 31개 테스트가 통과하며, A/B 입력 분리, 원문·근거 참조, 세션 격리, 재시도, 자료 후보 중복 적재를 검사한다. 이전 실제 모델 호출 결과는 [실행 검증 기록](validation/LIVE_VALIDATION.md)에 남아 있다.
