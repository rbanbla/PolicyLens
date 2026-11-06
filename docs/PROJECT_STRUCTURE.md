# 작업환경 구조와 책임

## 코드 레이어

| 경로 | 책임 |
| --- | --- |
| `server/features/` | HTTP 진입점만 담당: 요청 확인, 세션, 잠금, 응답. 업로드 텍스트 추출도 여기에 있음 |
| `server/application/` | 규칙: 사례 등록(`cases`), 문서 지문·인용 복원(`documents`), 요약(`summaries`), 토론 단계·프롬프트·검증(`debates`) |
| `server/data/` | 수집 코퍼스 카탈로그, Evidence·프로필 적재와 역할별 근거 검색 |
| `server/integrations/` | 외부 모델 API 호출, 응답 형식 통일, 모델 설정 읽기, 공통 오류 `ModelError` |
| `server/models.py`, `server/migrations/` | PostgreSQL 스키마와 변경 이력 |
| `server/management/commands/` | 초기 자료 적재, 엑셀 후보 등록, B 자료 목록 생성 |
| `server/static/`, `server/templates/` | 모바일 웹 자산과 HTML |
| `server/tests/` | DB, 모델 호출 계약, 화면과 보안 검증 |
| `scripts/data/` | 공개 출처 수집·행 검증·역할별 링크 생성 도구. 서버 요청 경로에서 실행되지 않음 |
| `study/` | A 프롬프트·단계 설정 고정본(`study_v1.json`)과 사례 입력 검사(`prepare_case.py`). 서버가 실행 중에 읽음 |
| `render.yaml`, `deploy/` | Render 웹·DB 배포 설정, 정적 파일 빌드와 선별 DB 초기 적재본 |
| `docs/` | 구조·로드맵(`README.md`가 지도), 명세(`specs/`), 운영(`ops/`) 문서 |
| `validation/` | 실제 모델 호출 결과와 전송 내용 확인본. `/demo/`가 `LIVE_RUN_RESULT.json`을 실행 중에 읽음 |
| `design/` | 첫 화면 미리보기 이미지의 Stageshow 소스. 서버 실행에는 쓰이지 않음 |

의존 방향은 `urls → features → application → data·integrations·models`다. `features/`끼리는 서로 가져다 쓰지 않고, 공통 규칙은 `application/`에 둔다. `.env`는 `integrations/transport.py`의 `setting()`으로만 읽는다. 외부 API 키는 `integrations/`에서만 HTTP 요청에 첨부한다. 원격 원문과 업로드 문서는 실행 지시가 아닌 입력 데이터로 취급한다.

## 데이터 레이어

| 경로 | 내용 |
| --- | --- |
| `data/b/roles/student/` | 학생 B Evidence 원본, 엑셀 학생 후보의 파일 링크·행 목록 |
| `data/b/roles/faculty/` | 교수 B Evidence 원본, 교육자 설문 설명, 엑셀 교수 후보 |
| `data/b/roles/administration/` | 행정 대체 근거가 된 정책 원본·추출 텍스트, 엑셀 직원 후보 |
| `data/b/shared/profiles/` | 실제 후보 추출에 사용한 합성 프로필 파일 링크 |
| `data/b/sources/collected/` | 엑셀 URL의 저장 원본 1벌, 추출 텍스트, 체크섬·수집 상태 |
| `data/b/review/` | 엑셀과 과거 코퍼스의 교차 검토 문서 |
| `data/b/archive/file_inventory.csv` | 과거 수집 파일 15,101개의 현재 B 사용 여부 |
| `research/2026-11-02/`, `../output/research/` | 선행연구와 정책의 기존 수집 원본. 경로와 출처 보존 |

역할 폴더의 `evidence/`는 **현재 B 검색에 쓰이는 원본**이며, `candidates/`는 **아직 B 모델 입력에 넣지 않은 엑셀 출처**다. 동일 문서가 둘 이상의 역할에 등장하면 각 역할에는 링크만 두고 파일은 한 번 저장한다. `candidate_rows.csv`가 엑셀 시트·행, URL, 수집 상태와 인용문 확인 결과를 잇는다. 웹에서만 확인된 원문은 파일 링크 없이 URL로 남긴다.

## 갱신 순서

`./start.sh`는 마이그레이션 → 모의 정책 등록 → 최초 코퍼스 적재 → 엑셀 후보 등록 → B 근거 목록과 역할 폴더 갱신을 수행한다. 이후 기존 수집 원본을 바꾸었다면 다음 순서로 갱신한다.

1. `.venv/bin/python manage.py import_corpus`
2. `.venv/bin/python manage.py import_b_sources`
3. `.venv/bin/python manage.py export_b_inventory`
4. `.venv/bin/python scripts/data/organize_roles.py`

외부 출처 추가 수집은 현재 중단했다. `scripts/data/collect_*.py`는 보존하되 자동 실행하지 않는다. 토론의 기존 스냅샷은 자료 폴더를 재정리해도 바뀌지 않는다.
