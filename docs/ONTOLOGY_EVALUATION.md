# 정책 온톨로지 구현·검토 결과 — 2026-11-08

## 구현 상태

현재 서비스는 기존 원문 검색에 검수된 정책 사실을 추가 조회할 수 있다. Policy → PolicyVersion → PolicyFact → FactEvidence를 기존 Django 모델로 구현했다. 새 실행은 구조화 검색을 사용하고, 이전 실행은 기존 경로를 유지한다. 구조화 사실이 없으면 기존 검색 결과가 그대로 쓰인다.

구현 파일:

- `server/models.py`, migrations 0008–0011: 정책, 적용 버전, 명시적 대체 관계, 검수 사실, 원문 근거, 실행별 선택.
- `server/agents/tools/policy_facts.py`: 제한된 조건 검증·3값 평가, 원문 스냅샷 해시, 공개 시점/적용일/검수 상태를 적용한 사실 조회.
- `server/management/commands/load_policy_facts.py`: 원자적 JSONL 적재와 dry-run. 누락 레코드를 삭제하지 않는다.
- `server/agents/tools/sources.py`: 기존 검색 결과에 structured_facts 추가. 같은 업로드 제외, 의견 검색에는 정책 사실 제외, 5쪽/문서당 2쪽 한도 유지.
- `server/agents/runner.py`: 호출 목적·시도·단계·입출력 토큰·시간, 역할별 사실 스냅샷.
- `server/templates/review_steps.html`: 최종 답변의 인용 근거에 정책 버전과 추가 확인 안내 표시.
- `server/management/commands/evaluate.py`: 구조화 비교 조건 및 동일 분석·기준선 재사용.
- `server/management/commands/evaluate_conditions.py`: 모델을 호출하지 않는 결정적 조건 사례 검증.

조건 평가는 독립 함수다. 사용자 프로필 수집 화면이나 자동 수급 승인 기능은 추가하지 않았다. 역할 에이전트가 임의로 입력한 프로필을 사실처럼 판정하는 경로도 없다. 역할 추출, 독립성, 쟁점 수, 순차 토론과 제품 A/B는 유지한다.

## 검토에서 발견하고 수정한 사항

1. **소득 주체·가구 범위 누락:** income_ratio는 `basis: {date, subject, household_scope}`를 반드시 요구한다. 입력이 다른 기준을 쓰면 unknown이다. 나머지 기준일은 ISO 날짜다.
2. **정정 공고와 기존 버전 충돌:** 명시적인 `supersedes`를 추가했다. 같은 정책의 기존 버전만 지정 가능하다. 대체 버전의 검수된 근거가 조회 기준일에 이미 공개되어 있고 적용 기간에 해당할 때만 이전 버전을 제외한다. 단순 최신 문서는 우선하지 않는다. 완전 대체 관계이며 부분 정정은 정정 후 전체 조건을 재구성·검수해야 한다.
3. **근거 삭제 후 일부 근거만으로 검수 유지:** Source 삭제 시 근거 행을 지우지 않고 빈 참조로 남겨 사실 전체를 조회에서 제외한다.
4. **보이지 않은 페이지 구간 인용:** 검색 시 실제 반환한 발췌 구간만 인용을 허용한다. 전체 페이지를 read_source로 읽으면 그 범위까지 허용한다. 발췌 사이를 이어 만든 인용은 허용하지 않는다.
5. **입력 경계:** 숫자·중첩·인용 길이를 제한하고 잘못된 해시·인용·검수 메타데이터·자료 게이트를 거부한다.
6. **평가 문서 전송:** evaluate도 기술·권리·외부 전송 게이트를 확인한다.

별도 검토 에이전트가 소득 기준과 정정 버전 문제를 재현했다. 수정 후 회귀 테스트에 포함했다. 추가 유료 API 호출은 하지 않았다.

## 검증

- 시작 시 기존 테스트 91개 통과.
- 최종 전체 테스트 수와 실행 결과는 아래 최종 확인 절에 기록한다.
- 합성 조건 사례 **30/30 통과**: 경계값, 지역 일치, 재학/취업, 가구원 수, 누락 정보, 다른 단위/기준일/소득 주체, AND/OR/NOT.
- 실 DB 복사본에서 마이그레이션 적용 → 0007로 복구 → 재적용. 기존 실행 pages/steps/calls 해시 동일.
- 실 DB 적용 후에도 기존 실행 **6건**, 공개 자료 **67개·709쪽** 보존. 기존 실행의 structured_facts는 False.
- 공식 자료 10개에서 **30개의 pending 인용 후보**를 만들고 적재 dry-run 통과. 검수 완료 사실 **0건**.
- 로컬 검색 10회씩 측정: 원문 경로 중앙값 38.74ms, 구조화 경로 40.19ms. 검수 사실이 없는 상태의 추가 비용 측정이며 데이터가 채워진 상태의 성능이나 답변 품질을 증명하지 않는다.
- 모델 전체 지연·첫 표시 시간·실제 정책 조건 정확도·의견 품질은 아직 실험하지 않았다. 기존 모델 대기 140~217초 대비 개선 비율을 주장하지 않는다.

## 데이터 검토 대기열

`data/reviewed/policy_fact_candidates_2026-11-08.jsonl`은 공개 자료 10개에서 신청·지원·대상 주변을 추출한 30개 인용 후보다. **10개의 서로 다른 정책으로 확정된 자료도, 정답 평가 세트도 아니다.**

후보의 policy/version 식별자는 임시이고 region_code는 UNREVIEWED, 적용·신청 기간은 null, status는 pending이다. 문맥을 읽지 않고 신청 규정이라고 확정하지 않기 위해 전체 후보를 미검수로 유지했다. 자동 추출창은 문장을 중간에서 끊거나 표 맥락을 놓칠 수 있다.

검토 순서:

1. 원문·쪽·앞뒤 문맥을 읽고 잘린 인용을 보완한다.
2. 같은 정책의 문서를 묶고 지역·회차·기관 식별자를 확정한다. 실제 독립 정책 수를 따로 집계한다.
3. 발행일로 시행일을 추정하지 않는다. 적용 기간·신청 기간과 정정 관계를 별도 확인한다.
4. predicate를 eligibility/exclusion/benefit/application/interaction 중 맞는 것으로 수정한다. eligibility/exclusion은 제한된 조건 트리, benefit/application은 `{text}`, interaction은 대상 버전·방향·조건이다.
5. 공식 문서의 모든 필수 조건을 추출했다고 단정하지 않는다. 표현할 수 없는 조건은 원문 검토 사항으로 남긴다.
6. 실제 검수자·검수 시각과 verified 상태를 기록한 새 manifest를 만든다. 스크립트로 pending을 일괄 승격하지 않는다.

아직 이 대기열을 실 DB에 적재하지 않았다. 형식·인용 검증만으로 의미적 정확성이 확인된 것은 아니다.

## 실행 방법

프로젝트 루트에서 가상환경의 Python으로 실행한다. 현재 환경에서는 `../policylens/.venv/bin/python`을 사용했다.

```bash
python manage.py test server
python manage.py evaluate_conditions --cases server/fixtures/ontology_conditions.jsonl
python manage.py load_policy_facts --manifest data/reviewed/policy_fact_candidates_2026-11-08.jsonl --dry-run
# 검수 완료 manifest를 별도 작성한 뒤:
python manage.py load_policy_facts --manifest data/reviewed/policy_facts_verified.jsonl
```

적재 파일은 한 줄에 policy/version/fact/evidence를 담는다. 검수 전 상태로 적재하면 조회에 노출하지 않는다. 같은 fact_id를 pending/rejected로 다시 적재하면 이전 검수 완료 사실도 비활성화된다. 정책·버전 정의는 덮어쓰지 않으며 변경 시 새 버전 ID를 쓴다. 동일 버전 정의는 manifest 안에서 일치해야 한다. supersedes 대상 버전은 먼저 적재해야 한다.

`source_hash`는 원본 PDF 바이트가 아니라 **Source의 본문·메타데이터 스냅샷 해시**다. `source_digest(Source.objects.get(doc_id=...))`로 계산한다. 문서 해시와 별도로 각 사실 revision을 저장한다. 공용 캐시가 없으므로 전역 corpus revision 캐시는 만들지 않았다.

모델 비교는 검수된 자료가 준비된 후 다음처럼 수행한다. 실제 모델 호출과 비용이 발생한다.

```bash
python manage.py evaluate youth-housing-kr-01 --role 0
python manage.py evaluate youth-housing-kr-01 --role 0 --structured-facts --reference-run data/reviewed/runs/youth-housing-kr-01-sources.json
```

참조 실행과 문서 해시·기준일·역할·모델·제공자·프롬프트가 같아야 한다. 참조의 역할 분석과 단일 프롬프트 결과를 재사용한다. 두 실행의 속도는 analysis/baseline 호출을 제외한 같은 검토 단계끼리 비교한다. 참조 기능 추가 전 실행 파일은 필요한 해시가 없으므로 새 기준선이 필요하다. 자료 저장소는 두 실행 사이에 갱신하지 않는다. 검수 세트의 인용·버전 위반, unknown 오확정, 중요 쟁점 누락과 검수 비용도 함께 측정한다.

## 계획 조정과 남은 작업

- 승인된 실행 요청에 따라 현재 체크아웃의 `codex/policy-ontology` 브랜치에서 구현했다. 기존 수집 파일·문서 변경을 보존했다. 자동 커밋·병합·배포는 하지 않았다.
- Task 1의 계측, Task 2–5의 코드, Task 6의 오프라인 실행 경로를 구현했다. 사람 검수 정답 30개와 실제 모델 비교 실험은 완료로 표시하지 않는다.
- 인간 검수를 대신했다고 주장할 수 없으므로 계획의 ‘10~20개 정책 정형화’ 대신 현재는 10개 문서의 인용 후보 30개를 제공한다. 의미 검수 전에는 서비스의 사실 수가 늘지 않는 것이 의도한 동작이다.
- DB 쓰기 잠금 해제, 화면 지연 제거, 묶음 생성·병렬화는 별도 속도 개선 작업으로 남겼다. 이번 변경은 순차 호출 수를 줄이지 않는다.
- 원본 백업: `output/ontology/pre-ontology.sqlite3`. 마이그레이션 검증 복사본과 수치: `output/ontology/migration-trial.sqlite3`, `output/ontology/verification.json`. 이 파일은 기존 사적 실행 내용을 포함할 수 있으므로 저장소에 추가하지 않는다.

## 최종 확인

2026-11-08: `python manage.py test server` **116개 통과** (기존 91개 + 새 25개). 손상 PDF 거부 테스트가 출력하는 parser 진단 외 실패 없음. `manage.py check`, `makemigrations --check --dry-run`, `git diff --check` 통과. 합성 조건 사례 30/30, 후보 적재 dry-run 30건 통과. 기존 6개 실행의 pages/steps/calls 해시 보존을 확인했다.
