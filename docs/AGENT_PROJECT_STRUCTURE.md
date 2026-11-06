# PolicyLens 에이전트 프로젝트 폴더 구조

현재 Django·PostgreSQL 프로젝트를 기준으로 한 목표 구조다. PolicyLens는 업로드된 대학 AI 정책에서 쟁점을 찾고, 학생·교수·학사행정 에이전트의 토론을 거쳐 수정 제안과 남은 이견을 보여준다. 연구 조건 A는 연구자가 작성한 역할 지침을, 잠정 B는 역할별 수집 근거를 사용한다.

강의자료 9–14쪽의 Core·Planning·Memory·Tool 모델을 실행 코드의 경계로 삼았다. 17–27쪽의 작업 분해와 결과 검토는 단계 계획 및 검증에, 28–43쪽의 단기·장기 메모리는 실행 체크포인트 및 검색 가능한 근거에, 44–52쪽의 RAG는 B 조건의 근거 검색에 적용한다. 59–67쪽의 도구 실행과 사용자 피드백은 도구 호출 기록, 오류 복구, 연구자 검수에 적용한다. 강의 실습의 예시 프롬프트와 명령은 참고 자료로 사용했다.

## 전체 폴더 트리

`[신규]`는 목표 구조에서 추가할 경로다. 표시가 없는 경로는 현재 프로젝트에 있다. 역할별로 동일한 하위 구조는 한 번만 표시했다.

```text
policylens/
├── README.md                         # 실행법과 프로젝트 진입점
├── .env.example                      # 서버 설정 변수 이름과 예시
├── .gitignore
├── manage.py
├── requirements.txt
├── requirements-deploy.txt
├── start.sh, server.sh, demo-online.sh # 로컬 실행과 시연
├── render.yaml                       # 웹 서비스와 PostgreSQL 배포 정의
├── data/                             # 로컬 수집·정제·검수 자료
│   └── b/
│       ├── sources/
│       │   ├── PolicyLens_Sources.xlsx # 역할별 출처 후보 목록
│       │   └── collected/
│       │       ├── raw/               # 저장한 PDF·HTML·설문 파일 원본
│       │       └── text/              # 검색·검수용 추출 텍스트
│       ├── roles/
│       │   ├── student/              # 인터뷰·포커스그룹 발화
│       │   │   ├── evidence/          # 현재 근거에 쓰이는 자료 링크
│       │   │   └── candidates/        # 검토 중인 출처와 행 목록
│       │   ├── faculty/              # 교육자 설문 집계와 해설
│       │   └── administration/       # 기관 정책 등 행정 대체 근거
│       ├── shared/profiles/           # 별도 관리하는 합성 배경
│       ├── review/                   # 원문 대조와 채택·보류 판정
│       └── archive/                  # 과거 수집 파일의 사용 여부 목록
├── research/                         # 선행연구와 기존 정책 수집본
│   └── 2026-11-02/                   # DATA/, KR/, INT/, REF/, policy_text/
├── scripts/
│   ├── data/                         # 배치 수집·대조·역할별 링크 정리
│   └── local_server.py               # 로컬 서버 실행 지원
├── study/
│   ├── study_v1.json                 # 기존 연구 설정과 프롬프트 원본
│   └── prepare_case.py               # 연구 사례 입력 검증
├── prompts/                          # [신규] 모델에 전달하는 버전 고정 지침
│   └── v1/
│       ├── manifest.json             # 버전, 단계·조건별 파일 연결
│       ├── common.md                 # 원문 인용, 출력 규칙, 역할 공통 지침
│       ├── summary.md                # 정책 요약
│       ├── discovery/                # discover.md, merge.md
│       ├── conditions/               # a.md, b.md
│       ├── roles/                    # student.md, faculty.md, administration.md
│       ├── stages/                   # opening.md, reply.md, draft.md, review.md, final.md
│       └── repair.md                 # 검증 오류와 필요한 수정 범위를 전달
├── server/
│   ├── settings.py, urls.py, wsgi.py  # Django 설정·라우팅·서버 진입점
│   ├── middleware.py, admin.py       # 공통 HTTP 처리와 관리자 화면
│   ├── features/                    # 업로드·정책·요약·토론·자료 HTTP 진입점
│   │   ├── uploads.py, policies.py   # 문서 등록과 정책 화면
│   │   ├── summaries.py, debates.py  # 요약 요청과 토론 시작·진행·조회
│   │   ├── sources.py, research.py  # 출처 카탈로그와 연구자 화면
│   │   └── demo.py, health.py       # 시연과 서버 상태
│   ├── application/                 # 문서·사례·요약·토론 유스케이스
│   │   ├── documents.py, cases.py   # 문서 지문·인용 확인과 사례 등록
│   │   ├── summaries.py             # 정책 요약 생성과 검증
│   │   └── debates.py               # HTTP 계층이 호출하는 토론 진입점
│   ├── agents/                      # [신규] 에이전트 런타임
│   │   ├── runner.py                 # Core. 단계 준비 → 호출 → 검증 → 저장
│   │   ├── planning.py               # 단계 순서, 조건, 종료 및 재시도 규칙
│   │   ├── prompting.py              # 버전별 지침 + 현재 입력으로 요청 조립
│   │   ├── schemas.py                # 쟁점·발언·검토·수정안의 구조화 출력 계약
│   │   ├── validation.py             # 출처·발언 ID 및 허용 범위 검증
│   │   ├── memory/
│   │   │   ├── checkpoints.py        # 실행 스냅샷·커서·확정 결과·실패 이력
│   │   │   ├── context.py            # 조건·역할·단계에 맞는 기록만 읽기
│   │   │   └── knowledge.py          # 승인된 장기 근거 조회와 버전 고정
│   │   └── tools/
│   │       ├── registry.py           # 도구 목록, 인자 스키마, 실행 권한
│   │       ├── policy.py             # 조항·페이지 조회, 원문 인용 확인
│   │       └── evidence.py           # B 역할에 허용된 근거 조회
│   ├── data/corpus.py                # 출처·근거 적재와 기존 역할별 검색
│   ├── integrations/transport.py     # 외부 모델 API 호출과 오류 변환
│   ├── models.py, migrations/        # PostgreSQL 모델과 스키마 변경 이력
│   ├── management/commands/
│   │   ├── import_corpus.py         # 기존 코퍼스와 근거 적재
│   │   ├── import_b_sources.py      # 엑셀 출처 후보 적재
│   │   ├── export_b_inventory.py   # B 근거와 후보 목록 내보내기
│   │   └── seed_demo.py, seed_deploy.py # 데모와 배포 데이터 초기화
│   ├── templates/, static/           # 모바일 화면과 브라우저 코드
│   └── tests/                       # 서버·토론·데이터·배포 검증
├── deploy/                           # 웹 시작·빌드·선별 자료 시드
│   └── build.sh, start.sh, seed.json.gz
├── validation/                       # 기존 실행 결과와 검증 보고서
├── design/                           # 시연 및 화면 디자인 자산
└── docs/                             # 현행 구조, 설계, 운영 문서
```

## 플래닝·메모리·툴의 책임

| 구성 | 구현 위치 | PolicyLens에서 하는 일 |
| --- | --- | --- |
| Core | `server/agents/runner.py` | 계획에서 현재 단계를 읽고, 해당 역할의 입력을 구성해 모델을 호출한다. 검증을 통과한 결과를 저장한 후 다음 단계로 진행한다. |
| Planning | `server/agents/planning.py` | 공통 쟁점 찾기와 A/B 토론의 순서, 각 역할이 읽는 결과, 종료 및 실패 복구 규칙을 관리한다. A와 B에 같은 순서와 상한을 적용한다. |
| Memory | `server/agents/memory/` | 단기 메모리는 `DebatePair`, `DebateCall`, `DebateAttempt`를 이용해 실행을 복구한다. 장기 메모리는 승인된 `Evidence`와 `ResearchAsset`을 근거 카탈로그로 읽는다. |
| Tool use | `server/agents/tools/` | 정책 페이지 조회, B 근거 조회, 원문 인용 대조를 함수로 제공한다. `registry.py`가 입력과 권한을 확인하며 실제 원문 확인과 검색은 기존 문서·코퍼스 함수를 재사용한다. |
| Reflection | `server/agents/validation.py` + `prompts/v1/repair.md` | 인용·발언 참조가 잘못되면 서버가 오류를 판정한다. 수정 가능한 오류는 해당 단계 안에서 제한된 횟수로 수정하고, 실패가 계속되면 재시도 가능한 상태나 검수 상태로 기록한다. |

정책 조항과 근거 조회는 서버가 현재 단계에 맞춰 호출하는 도구로 시작한다. 향후 에이전트가 조회 여부나 검색어를 선택하는 Agentic RAG를 실험한다면 별도 프로토콜로 버전 관리한다. 검색 결과를 확인하고 필요할 때 검색어를 다시 작성하는 방식이며, 조회 횟수에 상한을 둔다. 기존 A/B 연구 실행에서는 역할별 B 근거 묶음을 시작 시 고정한다.

## 수집에서 화면까지

1. **수집·검수** — `scripts/data/`에서 원본과 추출 텍스트를 수집하고, 원본 URL·체크섬·페이지 또는 시트와 행을 기록한다. `data/b/roles/`에는 역할별 링크와 근거 목록을 둔다. 동일한 출처 파일은 한 곳에 저장한다.
2. **근거 적재** — 검토 중인 출처는 `BSourceCandidate`로 관리한다. 역할 적합성과 원문 대조를 통과한 항목만 `Evidence`로 적재한다. 학생 직접 발화, 교수 설문 집계, 행정 대체 근거는 출처 유형을 구분한다.
3. **실행 고정** — Django가 세션과 업로드 문서를 확인한다. 실행에는 문서 지문, 프로토콜·프롬프트 버전, 모델 설정, 역할 배경, B 근거 ID와 해당 발췌를 저장한다. 단계가 재시도되거나 자료를 갱신해도 기존 실행은 당시 입력으로 복구한다.
4. **공통 쟁점 → 조건별 토론** — 공통 쟁점은 업로드 원문을 기준으로 세 역할의 후보 3회와 통합 1회로 찾는다. 쟁점이 없으면 종료한다. 쟁점이 있으면 조건별로 입장 3회 → 반론 3회 → 초안 1회 → 검토 3회 → 최종 편집 1회를 실행한다. 기준 모델 호출은 최대 26회이며 실패 복구 호출은 별도로 집계한다.
5. **검증·표시** — 서버가 문서의 실제 페이지·인용과 실행 내 발언 ID를 검증한다. 모바일에는 원문, 진행 상태, 근거에 연결된 제안과 남은 이견을 표시한다. 연구 참여자에게 공개할 결과는 연구자 검수 상태와 분리해 관리한다.

```text
업로드 → Django features/ → application/ → agents/runner.py
                                              │
                     planning → memory/context → prompting → 모델 호출
                                        ↑                    │
                               tools → corpus·원문       validation
                                                             │
                                           PostgreSQL ← 체크포인트 저장
                                                             │
                                                    진행 상태·결과 응답
```

## 저장과 접근 범위

| 데이터 | 저장 위치 | 접근 규칙 |
| --- | --- | --- |
| 수집 원본·후보 | `data/b/`, `research/` | 로컬 검수용. 배포는 선별한 DB 시드 사용 |
| 정책 업로드·확정 발언 | PostgreSQL과 서버 세션 | 세션 소유권 확인. 토론 기록은 실행·조건·단계로 분리 |
| A 역할 지침과 B 근거 | 버전 고정 프롬프트, 실행 스냅샷 | A와 공통 쟁점 발견은 B 발췌 접근 금지. B 발언자는 자기 역할 근거와 같은 조건의 허용된 이전 발언만 읽음 |
| 진행자 입력 | 단계별 컨텍스트 | 기본은 공개 발언·조항·허용 근거 ID. B 진행자의 원문 발췌 접근은 프로토콜에서 별도로 명시 |
| 오류·호출 이력 | `DebateAttempt` 및 서버 로그 | 개발·연구자용 이력과 공개 응답을 분리. 운영 로그는 단계·시간·오류 등 필요한 메타데이터 중심 |
| 모델 키와 배포 설정 | 로컬 `.env` 또는 배포 서비스 환경 변수 | `integrations/`가 서버에서 사용. Git에는 `.env.example`만 포함 |

원문·수집 페이지·도구 결과는 모델의 데이터 입력으로 전달한다. 실행 지침은 버전이 고정된 `prompts/`에서 로드한다. 업로드 문서와 합성 토론은 승인된 장기 근거로 자동 승격하지 않는다.

## 현행 코드에서 옮기는 순서

| 순서 | 현재 위치 | 목표 작업과 확인 방법 |
| --- | --- | --- |
| 1 | `study/study_v1.json`, `server/application/debates.py`, `server/application/summaries.py` | 지침 문구를 `prompts/v1/`로 추출한다. 현재 단계별 요청과 비교해 역할·단계 조합 및 출력 계약이 같은지 확인한다. 기존 실행의 저장된 `spec`은 그대로 읽고, 새 실행은 프롬프트 버전과 실제 지침을 함께 고정한다. |
| 2 | `server/application/debates.py` | `STEPS`와 전이 조건은 `planning.py`, 실행과 호출 기록은 `runner.py`, 출력 계약과 검사는 `schemas.py`·`validation.py`로 분리한다. 기존 Django 진입점의 요청·응답과 26회 단계 순서를 확인한다. |
| 3 | `history_for()`, `packet()`, `prepare_run()`, `server/data/corpus.py` | 기록 선택·스냅샷 저장은 `memory/`, 정책·근거 조회 진입점은 `tools/`에 둔다. A/B 격리, 다른 역할의 비공개 발췌 차단, 실패 단계 재시도, 원문 인용을 검사한다. |
| 4 | `server/features/debates.py`, `server/templates/`, `deploy/` | 현재 Django 요청으로 한 단계씩 진행하는 방식에서 먼저 연결한다. 서버에 프롬프트 파일이 포함되는지와 초기 적재 후 실행이 복구되는지를 확인한다. 운영에서 요청과 실행을 분리해야 할 때 워커를 추가하고, 같은 단계를 두 요청이 동시에 확정하지 않도록 실행 키와 상태 전이를 검증한다. |

폴더 분리와 연구 규칙 변경은 별개로 관리한다. 현재 코드에는 B 근거가 한 역할에만 있어도 실행할 수 있고 B 진행자에게 역할별 발췌를 합쳐 제공하는 경로가 있다. 연구용으로 세 역할의 근거를 모두 요구하거나 진행자 입력을 좁힐 때는 새로운 프로토콜 버전에서 적용한다. 검증은 기존 `server/tests/`의 토론·자료·요약·배포 테스트를 기준으로 진행한다.

현행 경로와 운영 명령은 [현재 프로젝트 구조](PROJECT_STRUCTURE.md), A/B의 단계·참조 규칙은 [토론 프로토콜](specs/DEBATE_PROTOCOL.md), 실제 모델 입력의 자료 구분은 [역할별 입력 점검](specs/AB_ROLE_INPUT_AUDIT.md)에 있다.
