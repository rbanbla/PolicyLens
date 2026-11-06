# 턴제 입장 나누기·쟁점 토론 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 3쪽(입장 나누기)과 4쪽(쟁점 토론)이 모델 호출 한 번에 의견 하나씩, 역할이 차례로 돌아가며 올라오게 한다. 역할당 의견과 쟁점은 최대 3개다.

**Architecture:** 서버가 고정하는 단계 계획을 "역할 수 × 3바퀴"의 턴으로 늘린다. 한 턴은 호출 한 번에 항목 하나를 만든다. 더 낼 것이 없는 턴은 `advance`가 호출 없이 건너뛰고 같은 요청 안에서 저장한다. 화면은 단계 하나가 말풍선 하나라 기존 러너가 그대로 한 번에 하나씩 보여준다.

**Tech Stack:** Django 5.2, SQLite, 프로젝트 `.venv`, Django gettext, 모의 모델 테스트(`unittest.mock`).

**Spec:** `docs/superpowers/specs/2026-11-06-turn-based-discussion-design.md`

## Global Constraints

- `TURNS = 3`이 역할당 의견 수, 쟁점 수, 토론 바퀴 수다. 역할 3명이면 9 + 1 + 9 + 1 = 20단계, 2명이면 14단계다.
- `phases_for(n)`: `m = TURNS * n`, `discussion = (0, m + 1)`, `review = (m + 1, 2m + 1)`, `proposal = (2m + 1, 2m + 2)`.
- 건너뛴 단계의 저장 형식은 `{'stage', 'role', 'result': {'summary': '', 'items': []}, 'skipped': True}`다.
- 쟁점 유형, 우선순위, 입장, 반응 값은 한국어로 저장한다. 화면에서만 번역한다.
- CSS와 레이아웃은 바꾸지 않는다. 2·3·4쪽 디자인 변경은 사용자의 별도 승인이 필요하다.
- 새 사용자 노출 문구는 한국어 원문을 `gettext`로 감싸고 `locale/en/LC_MESSAGES/django.po`에 영어를 추가한 뒤 컴파일한다.
- 이 프로젝트는 git 저장소가 아니다. 커밋 단계는 없고, 작업마다 전체 테스트 통과로 끝낸다.
- 테스트 실행: `cd /Users/sangbum/Workspace/assignment/HCI/policylens-v2 && .venv/bin/python manage.py test server`
- 실제 모델 호출은 사용자 승인 없이 하지 않는다. 호출은 최대 20회다.

## Review Focus

1. 모든 역할이 첫 턴에 "더 없음"을 낸다: 남은 턴은 호출 없이 건너뛰고, 쟁점 정리가 빈 입력으로도 끝까지 진행된다. (Task 1)
2. 쟁점이 1~2개뿐이다: 토론 바퀴가 쟁점 수에서 멈추고, 클라이언트는 `state.cursor`를 따라 건너뛴 구간을 지나간다. (Task 1, 3)
3. 모델이 한 턴에 항목 2개 이상, 또는 쟁점 4개 이상을 낸다: 1회 재시도 후 오류로 남고 체크포인트는 유지된다. (Task 4)
4. 턴 호출이 실패(타임아웃)한다: 건너뛴 단계는 성공한 호출 뒤에만 쌓이므로 같은 턴이 다시 시도된다. (Task 1)
5. 역할 2명으로 끝까지 진행한다: 14단계, 경계 (0,7),(7,13),(13,14). (Task 1)

## 파일 구조

| 파일 | 변경 |
|---|---|
| `server/agents/planning.py` | `TURNS`, 새 `steps_for`/`phases_for`, `turn_of`, `is_skipped` |
| `server/agents/runner.py` | `advance`가 건너뛰기를 붙임, 검색 먼저 규칙, `stage_input`의 토론 한 쟁점 |
| `server/agents/memory/context.py` | `history`가 독립 입장은 자기 의견만, 건너뛴 단계는 모든 단계에서 제외 |
| `server/agents/validation.py` | 한 턴 한 항목, 쟁점 최대 3개 |
| `server/management/commands/evaluate.py` | 완료까지 `advance` 반복 |
| `server/templates/review_steps.html` | 건너뛴 단계 말풍선 숨김 |
| `prompts/independent.md`, `issues.md`, `debate.md` | 한 차례·최대 3개 문구 |
| `locale/en/LC_MESSAGES/django.po` | 새 검증 문구 영어 |
| `server/tests.py` | 도우미와 기존 테스트를 새 계획에 맞추고 새 테스트 추가 |
| `docs/PRODUCT_PLAN.md`, `docs/IMPLEMENTATION_STATUS.md` | 흐름, 구현 이력, 한계 |

---

### Task 1: 새 단계 계획과 건너뛰기

**Files:**
- Modify: `server/agents/planning.py`, `server/agents/runner.py` (`advance`), `server/agents/memory/context.py` (`history`), `server/management/commands/evaluate.py:34`, `server/tests.py`

**Interfaces:**
- Produces (`planning.py`):
  - `TURNS = 3`
  - `steps_for(count: int) -> list[tuple[str, int | None]]`
  - `phases_for(count: int) -> dict[str, tuple[int, int]]`
  - `turn_of(index: int, count: int) -> int`: 독립 입장은 `index // count`, 토론은 `(index - (TURNS * count + 1)) // count`
  - `is_skipped(steps: list[dict], index: int, count: int) -> bool`: `steps[:index]`만 보고 계획 `index` 단계를 건너뛸지 정한다. 독립 입장은 그 역할의 앞선 독립 입장 단계 중 `items`가 0개인 것이 있을 때, 토론은 `turn_of(index, count) >= len(쟁점 정리 단계의 items)`일 때 `True`. 그 밖의 단계는 `False`.
- Produces (`runner.py`): `advance(run)`은 호출이 필요한 단계 하나를 처리한 뒤 이어지는 건너뛸 단계를 모두 붙여 한 번에 저장한다. 호출이 실패하면 아무것도 붙이지 않는다.
- Produces (`context.py`): `history(run, stage)`가 `skipped` 단계를 모든 단계에서 제외한다.
- Produces (`tests.py`): `ReviewFlowTests.run_steps(run, count, **extra)`는 모델 호출 `count`번을 보내고, 매번 `run.refresh_from_db()` 뒤 `cursor = len(run.steps)`로 보낸다. `ReviewFlowTests.run_to_end(run, reply=report_response)`는 완료될 때까지(상한 50회) 같은 방식으로 보낸다. `completed_run`은 `run_to_end`를 쓴다. `run_steps_with_tools`도 DB에서 커서를 읽는다. `LanguageTests`에 `run_to_end = ReviewFlowTests.run_to_end`를 추가한다.

- [ ] **Step 1: 계획 단위 테스트를 쓴다** (`PlanTests(SimpleTestCase)`)
  - `test_plan_is_turn_based`: `[stage for stage, _ in steps_for(3)] == ['independent'] * 9 + ['issues'] + ['debate'] * 9 + ['final']`, `[role for _, role in steps_for(3)[:6]] == [0, 1, 2, 0, 1, 2]`, `len(steps_for(2)) == 14`, `phases_for(2) == {'discussion': (0, 7), 'review': (7, 13), 'proposal': (13, 14)}`, `phases_for(3) == {'discussion': (0, 10), 'review': (10, 19), 'proposal': (19, 20)}`, `[turn_of(i, 3) for i in range(9)] == [0, 0, 0, 1, 1, 1, 2, 2, 2]`, `[turn_of(i, 3) for i in range(10, 19)] == [0, 0, 0, 1, 1, 1, 2, 2, 2]`.
  - `test_is_skipped_follows_the_steps_so_far`: `step(stage, role, n)`은 `items`가 `n`개인 단계 dict. `steps = [step('independent', 0, 1), step('independent', 1, 0), step('independent', 2, 1)]`에서 `is_skipped(steps, 3, 3)`은 `False`, `is_skipped(steps, 4, 3)`은 `True`, `is_skipped(steps, 5, 3)`은 `False`. `steps = [step('independent', r, 1) for _ in range(3) for r in range(3)] + [step('issues', None, 2)]`에서 `[is_skipped(steps, 10 + i, 3) for i in range(9)] == [False] * 6 + [True] * 3`이고 `is_skipped(steps, 9, 3)`은 `False`.
- [ ] **Step 2: 실패를 확인한다.** `manage.py test server.tests.PlanTests` → 가져오기 오류 또는 FAIL.
- [ ] **Step 3: `planning.py`를 구현한다.** `steps_for`는 `[('independent', r) for _ in range(TURNS) for r in range(count)] + [('issues', None)] + [('debate', r) for _ in range(TURNS) for r in range(count)] + [('final', None)]`. `phase_of`와 `role_count`는 그대로 둔다.
- [ ] **Step 4: `PlanTests` 통과를 확인한다.**
- [ ] **Step 5: 도우미 `run_steps`, `run_to_end`, `completed_run`, `run_steps_with_tools`를 위 Interfaces대로 고친다.** 그 뒤 흐름 테스트를 `ReviewFlowTests`에 추가한다.
  - `test_roles_with_nothing_to_add_are_skipped_and_the_run_completes`: 독립 입장 단계에는 `{'summary': '쟁점 없음', 'items': []}`, 나머지는 `report_response`를 돌려주는 `reply`로 `run_to_end`. `[s.get('skipped', False) for s in run.steps[3:9]] == [True] * 6`, `len(run.steps) == 20`, `run.steps[-1]['stage'] == 'final'`, 모델 호출 8회(독립 입장 3, 쟁점 정리 1, 토론 3, 최종 1).
  - `test_cursor_jumps_past_skipped_turns`: JSON 헤더로 호출 13번째(토론 역할 2)의 응답 `cursor == 19`, 14번째 뒤 `complete`가 참.
  - `test_failed_turn_adds_no_skipped_steps`: 토론 역할 2의 호출에서 `TimeoutError`이면 `len(run.steps) == 12`이고 `skipped` 단계가 없다. 같은 커서로 다시 보내면 `len(run.steps) == 19`.
- [ ] **Step 6: 전체 테스트를 돌려 새 실패 목록을 본다.** `advance`, `history`, `evaluate`가 아직 옛 계획이라 실패한다.
- [ ] **Step 7: `advance`, `history`, `evaluate`를 구현한다.**
  - `advance`: 지금 본문으로 단계 하나를 만든 뒤, `steps = run.steps + [새 단계]`에 대해 `while len(steps) < len(plan) and is_skipped(steps, len(steps), count)`로 `{'stage', 'role', 'result': {'summary': '', 'items': []}, 'skipped': True}`를 붙이고, `numbered_steps(steps)`를 저장한다.
  - `history`: 필터에 `and not step.get('skipped')`를 더한다(번호는 `numbered_steps(run.steps)`로 건너뛴 단계를 포함해 매긴다).
  - `evaluate.py`: `for _ in steps_for(...)`를 `while not is_complete(run): advance(run)`로 바꾸고 `is_complete`를 `server.agents.progress`에서 가져온다.
- [ ] **Step 8: 기존 테스트를 새 계획에 맞춘다.** 아래 표대로 고친다(3명, 쟁점 1개, 모든 호출이 항목 1개인 가짜 모델 기준).

  단계 번호 `s{n}` = 계획 인덱스 + 1. 독립 입장 인덱스 0~8(역할 `0,1,2` 반복, `s1`~`s9`), 쟁점 정리 인덱스 9(`s10-i1`), 토론 인덱스 10~12(`s11`~`s13`), 건너뜀 13~18, 최종 인덱스 19(`s20-i1`). 호출 14회. 2명이면 독립 0~5(`s1`~`s6`), 쟁점 정리 6(`s7`), 토론 7·8(`s8`·`s9`), 건너뜀 9~12, 최종 13(`s14`), 호출 10회.

  | 테스트 | 옛 값 → 새 값 |
  |---|---|
  | `test_step_plan_follows_role_count` | `steps_for(2)` 단계 이름은 `['independent'] * 6 + ['issues'] + ['debate'] * 6 + ['final']`, `len(steps_for(3)) == 20`, `phases_for(2) == {'discussion': (0, 7), 'review': (7, 13), 'proposal': (13, 14)}` |
  | `test_three_roles_full_flow_and_duplicate_cursor` | 호출 8회 → 14회, `len(run.steps)` 8 → 20, 중복 커서는 `'7'` → `'19'`, 호출 수 8 → 14 |
  | `test_two_roles_run_six_steps` (이름을 `..._fourteen_steps`로) | `len(run.steps)` 6 → 14, 토론 ID `s4-i1`·`s5-i1` → `s8-i1`·`s9-i1`, 완료 뒤 중복 커서 `'6'` → `'14'` |
  | `test_role_agents_do_not_learn_user_choice` | 호출 8 → 14회. 입력과 짝지을 계획은 `[e for e, s in zip(steps_for(3), run.steps) if not s.get('skipped')]`. `sent[3]['history'][0]['speaker']`는 `sent[9]['history'][0]['speaker'] == '임차인'`으로 |
  | `test_debate_targets_exclude_own_statement_and_are_schema_enums` | `run_steps(run, 11)`, 호출 인덱스 4 → 10, 허용 ID `['s2-i1','s3-i1','s4-i1']` → `['s2-i1','s3-i1','s5-i1','s6-i1','s8-i1','s9-i1','s10-i1']` (스키마 enum도 같다) |
  | `test_independent_may_be_empty_but_later_stages_may_not` | 독립 입장 3회 뒤 `len(run.steps) == 9`(남은 6턴 건너뜀), 쟁점 정리 커서 `'3'` → `'9'`, 오류 뒤 길이 3 → 9 |
  | `test_debate_input_lists_claims_and_requires_answering_them` | `run_steps(run, 11)`, `assigned_claims == [{'issue_id': 's10-i1', 'claim_id': 's2-i1'}]`, 항목 `target_ids` `['s4-i1']` → `['s10-i1']`, 커서 `'5'` → `'11'`, 길이 5 → 11, 오류에 `s1-i1` |
  | `test_debate_must_answer_every_issue` | `run_steps(run, 10)`, `target_ids` `['s2-i1']`, 커서 `'4'` → `'10'`, 길이 4 → 10, 오류에 `s4-i1` → `s10-i1` |
  | `test_json_progress_runs_all_steps_and_rejects_stale_cursor` | 14번 반복하며 `cursor = result.json()['cursor']`로 다음 커서를 잡고, 새 커서가 20 미만이면 이전 커서 재전송이 409, 마지막은 커서 `'20'`으로 `complete`, 호출 수 8 → 14 |
  | `test_five_pages_show_their_own_steps` | 3쪽에서 `s4-i1` 포함 → `s10-i1` 포함, `s5-i1` 미포함 → `s11-i1` 미포함. 4쪽 `s5-i1` → `s11-i1` 포함. 5쪽 `s8-i1` → `s20-i1`, `s5-i1` 미포함 → `s11-i1` 미포함 |
  | `test_cautions_sort_by_priority_and_only_high_opens` | `run_steps(run, 13)`, `target_ids` `['s5-i1']` → `['s11-i1']`, 최종 커서 `'7'` → `'19'` |
  | `test_phase_boundaries_and_locked_next_page` | `run_steps(run, 4)` → `10`, `data-end="7"` → `data-end="19"` |
  | 서버 자료 테스트 `test_role_research_stays_private_until_issues` | 이어 보내는 커서 `1,2,3` → `1`~`9`, 쟁점 정리 호출은 `seen[2]` → `seen[8]` |
  | `test_debate_searches_only_when_the_model_asks` | `run_steps_with_tools(run, 4)` → `10`, 커서 `'4'` → `'10'` |
  | `test_final_card_and_letter_show_server_evidence` | `for stage in (-1, -2)` → `(-1, 12)` |
  | `test_evaluate_saves_a_time_limited_run_and_leaves_no_row` | `len(saved['steps'])` 8 → 20 |
  | `LanguageTests.test_english_progress_labels_and_letters` | `self.run_steps(run, 8)` → `self.run_to_end(run)` |

  그 밖에 `run_steps(run, k)`로 "어느 단계까지"를 뜻하는 테스트는 같은 대응을 쓴다: 옛 호출 수 `k`가 1~3이면 그대로, 4 → 10, 5 → 11, 6 → 12, 7 → 13, 8 → 14. 커서가 `'0'`~`'2'`인 테스트는 바꾸지 않는다.
- [ ] **Step 9: 전체 테스트가 통과하는지 확인한다.** 기대: 모든 테스트 OK(기존 74개 + 새 테스트).

### Task 2: 독립 입장 턴은 자기 의견만 보고, 검색은 첫 턴에 먼저

**Files:**
- Modify: `server/agents/memory/context.py`, `server/agents/runner.py` (`generate`, `agent_loop`, `advance`, `SEARCH_FIRST` 삭제), `server/tests.py`

**Interfaces:**
- Consumes: Task 1의 `advance`, `history`.
- Produces: `history(run, stage: str, role: int | None = None) -> list[dict]`. 독립 입장이면 `role`의 단계만(건너뛴 단계 제외). `generate(run, stage, data, schema, check, research=None, search_first=False)`와 `agent_loop(run, stage, payload, key, research, search_first)`는 `search_first`가 참일 때만 첫 라운드에 `tool_choice: required`를 보낸다. `advance`는 `search_first = stage == 'final' or (stage == 'independent' and not context)`로 정한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다.**
  - `test_independent_turn_sees_only_its_own_earlier_opinions`(`ReviewFlowTests`): `run_steps(run, 5)` 뒤 `sent`는 호출 입력 목록. `sent[0]['history'] == []`, `[h['speaker'] for h in sent[3]['history']] == ['임차인']`, `[h['speaker'] for h in sent[4]['history']] == ['임대인']`, 그리고 `for i, data in enumerate(sent): {h['role'] for h in data['history']} <= {i % 3}`.
  - `test_only_a_roles_first_turn_must_search`(서버 자료 테스트 클래스, `add_source`·`selected_run`을 쓰는 쪽): `add_source()` 뒤 `run_steps_with_tools(run, 3)`, 이어 커서 `'3'`(역할 0의 두 번째 턴)의 호출 페이로드에 `tools`는 있고 `tool_choice`는 없다. 기존 `test_agent_searches_then_answers_with_a_verified_snapshot`의 첫 턴 `tool_choice == 'required'` 단언은 그대로다.
- [ ] **Step 2: 실패를 확인한다.** 두 테스트 FAIL.
- [ ] **Step 3: `history`, `generate`, `agent_loop`, `advance`를 위 Interfaces대로 구현한다.** `SEARCH_FIRST` 상수는 지운다.
- [ ] **Step 4: 전체 테스트가 통과하는지 확인한다.**

### Task 3: 토론 턴은 쟁점 하나만 받는다

**Files:**
- Modify: `server/agents/runner.py` (`stage_input`, `advance`), `server/tests.py`

**Interfaces:**
- Consumes: Task 1의 `turn_of`.
- Produces: `stage_input(run, stage, role, context, targets, turn=0) -> dict`. 토론이면 `data['assigned_claims'] = [assigned_claims(context, role)[turn]]`. `advance`는 `turn_of(len(run.steps), count)`를 넘긴다.

- [ ] **Step 1: 실패하는 테스트를 쓴다.** `test_debate_turn_gets_one_issue_and_rounds_follow_issue_count`: 쟁점 정리에는 항목 2개(`ITEMS['issues']`에 `issue`만 `쟁점 1`·`쟁점 2`로, `citation: CITATION`, `target_ids`는 입력의 `allowed_target_ids`)를 돌려주고 나머지는 `report_response`인 `reply`로 `run_to_end`. 토론 호출 입력의 `assigned_claims` 길이는 모두 1이고, 그 `issue_id` 순서는 `['s10-i1'] * 3 + ['s10-i2'] * 3`. 모델 호출 17회, `len(run.steps) == 20`, `[s.get('skipped', False) for s in run.steps[16:19]] == [True] * 3`.
- [ ] **Step 2: 실패를 확인한다.**
- [ ] **Step 3: `stage_input`과 `advance`를 구현한다.**
- [ ] **Step 4: 전체 테스트가 통과하는지 확인한다.** Task 1 표의 `assigned_claims` 단언은 쟁점 1개라 그대로 통과해야 한다.

### Task 4: 한 턴 한 항목, 쟁점 최대 3개, 프롬프트

**Files:**
- Modify: `server/agents/validation.py` (`validate_report`), `prompts/independent.md`, `prompts/issues.md`, `prompts/debate.md`, `locale/en/LC_MESSAGES/django.po`, `server/tests.py`

**Interfaces:**
- Consumes: `planning.TURNS`.
- Produces: `validate_report`가 독립 입장·토론 단계의 `items`가 2개 이상이면 `ValueError(gettext('한 차례에는 항목을 하나만 작성하세요.'))`, 쟁점 정리 단계의 `items`가 `TURNS`개를 넘으면 `ValueError(gettext('쟁점은 최대 %(n)s개까지 고르세요.') % {'n': TURNS})`를 낸다.

- [ ] **Step 1: 실패하는 테스트를 쓴다.**
  - `test_one_item_per_turn_and_at_most_three_issues`: 독립 입장에 항목 2개를 두 번 연속(재시도 포함) 돌려주면 `run.error`에 `하나만`이 있고 `len(run.steps) == 0`. 같은 방식으로 쟁점 정리 항목 4개는 `최대 3개`가 오류에 있고 단계는 쌓이지 않는다. 토론 항목 2개도 `하나만`.
  - `test_english_turn_errors`: 영어 세션으로 같은 검증 오류가 `Write only one item per turn.`, `Choose at most 3 issues.`로 나온다.
  - `test_prompts_ask_for_one_item_at_a_time`: `prompts/independent.md`에 `더 다룰 쟁점이 없으면`이 있고 `최대 5개`는 없다. `prompts/issues.md`에 `최대 3개`가 있다.
- [ ] **Step 2: 실패를 확인한다.**
- [ ] **Step 3: `validate_report`에 검사를 더한다.** 기존 재시도 경로를 그대로 쓴다.
- [ ] **Step 4: 프롬프트를 고친다.**
  - `prompts/independent.md`의 "최대 5개이며, 없으면 items를 비우고 summary에 이유를 적는다." 문장을 지우고 아래 문단을 더한다: "이번 차례에는 쟁점 하나만 골라 items에 항목 하나로 담는다. history는 이 역할이 앞서 낸 발언이며 같은 조항이나 같은 쟁점은 다시 고르지 않는다. 한 역할이 낼 수 있는 쟁점은 최대 3개이고, 더 다룰 쟁점이 없으면 items를 비우고 summary에 이유를 적는다."
  - `prompts/issues.md`의 "최대 5개"를 "최대 3개"로 바꾼다.
  - `prompts/debate.md` 첫 문장 뒤에 "이번 차례에는 assigned_claims에 쟁점 하나만 있고, 항목 하나로 답한다."를 더한다.
- [ ] **Step 5: 영어 번역을 더한다.** `.po`에 `msgid "한 차례에는 항목을 하나만 작성하세요."` → `msgstr "Write only one item per turn."`, `msgid "쟁점은 최대 %(n)s개까지 고르세요."` → `msgstr "Choose at most %(n)s issues."`(소스 참조 주석과 `#, python-format`을 붙인다). `manage.py makemessages -l en --ignore='.venv/*' --ignore='tmp/*' --ignore='output/*'`로 목록을 확인하고 `msgfmt --check -o locale/en/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.po`로 컴파일한다.
- [ ] **Step 6: 전체 테스트가 통과하는지 확인한다.**

### Task 5: 건너뛴 단계는 말풍선을 만들지 않는다

**Files:**
- Modify: `server/templates/review_steps.html` (`{% empty %}` 블록), `server/tests.py`

**Interfaces:**
- Consumes: Task 1의 `skipped` 단계 형식.
- Produces: `skipped`가 아닌데 항목이 없는 단계(모델이 "더 없음"을 낸 단계)만 `summary` 말풍선(`id="s{n}-empty"`)을 보여준다.

- [ ] **Step 1: 실패하는 테스트를 쓴다.** `test_skipped_turns_have_no_bubble_but_nothing_to_add_does`: Task 1의 "모두 더 없음" 실행에서 3쪽 응답에 `id="s1-empty"`, `id="s2-empty"`, `id="s3-empty"`는 있고 `id="s4-empty"`~`id="s9-empty"`는 없다.
- [ ] **Step 2: 실패를 확인한다.**
- [ ] **Step 3: `{% empty %}` 안의 말풍선을 `{% if not step.skipped %}...{% endif %}`로 감싼다.** 마크업과 클래스는 바꾸지 않는다.
- [ ] **Step 4: 전체 테스트가 통과하는지 확인한다.** `test_page_three_and_four_keep_their_layout`도 통과해야 한다.

### Task 6: 문서, 화면 확인, 마무리

**Files:**
- Modify: `docs/PRODUCT_PLAN.md` (12~13줄 흐름, 65줄 수용 기준), `docs/IMPLEMENTATION_STATUS.md` (구현 이력 8번, 알려진 한계)

**Interfaces:**
- Consumes: Task 1~5 전체.

- [ ] **Step 1: 문서를 고친다.** PRODUCT_PLAN: 독립 입장은 역할이 차례로 의견을 하나씩 올리고(역할당 최대 3개), 쟁점은 최대 3개이며 토론은 쟁점마다 역할이 차례로 답한다고 쓴다. IMPLEMENTATION_STATUS: 이력 8번(턴제), 한계(호출 8→최대 20회와 토큰 증가, 의견 하나짜리 호출 시간 미측정, 이전 계획으로 만든 실행은 새 계획과 맞지 않음)를 쓴다.
- [ ] **Step 2: 가짜 모델로 화면 순서를 확인한다.** 스크래치 서버를 새 코드로 띄운다. 가짜 모델은 이 계획의 가정과 같다(턴마다 항목 1개, 쟁점 1~3개, 호출 1초 지연). 새 실행 하나를 만들고 `--virtual-time-budget`을 늘려 가며 Chrome `--dump-dom`으로 3쪽의 `class="chat-message` 개수를 센다. 기대: 개수가 한 번에 1씩 늘고, 순서는 역할 `0,1,2,0,1,2,...`이며 한 번에 5개씩 늘지 않는다. 4쪽도 같은 방식으로 센다.
- [ ] **Step 3: 영어 실행으로 같은 화면을 한 번 확인한다.** 3쪽의 "입력 중" 표시와 단계 라벨이 영어이고 한글이 남지 않는지 본다.
- [ ] **Step 4: 데모 서버(8001)를 새 코드로 다시 띄운다.** 기존 프로세스를 끄고 `manage.py runserver 127.0.0.1:8001`로 시작한다. 스크래치 서버와 임시 DB 프로세스는 끈다.
- [ ] **Step 5: 사용자에게 실제 모델로 한 번 돌릴지 묻는다.** 호출 최대 20회임을 알리고, 승인하면 청년월세 공고 PDF로 끝까지 돌려 `run.calls`의 호출 시간과 토큰을 spec의 추정과 비교해 `docs/IMPLEMENTATION_STATUS.md`에 기록한다. 승인하지 않으면 미확인으로 남긴다.
- [ ] **Step 6: 전체 테스트가 통과하는지 마지막으로 확인한다.**
