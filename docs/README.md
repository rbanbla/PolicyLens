# PolicyLens 문서 지도

처음이면 [프로젝트 README](../README.md) → [작업환경 구조](PROJECT_STRUCTURE.md) → [실행·데이터 명세](specs/DATA_CONNECTION.md) 순서로 읽는다. 내용이 충돌하면 **코드 → DATA_CONNECTION → 나머지 문서** 순으로 우선한다.

| 알고 싶은 것 | 문서 | 성격 |
| --- | --- | --- |
| 폴더와 코드 레이어, 갱신 명령 | [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | 현행 |
| 연구 질문, 단계별 진행 상태 | [ROADMAP.md](ROADMAP.md) (구 `agend.md`) | 진행 기록. 날짜별 절은 당시 상태 |
| 데이터 연결, A/B 실행, 저장, 한계 | [specs/DATA_CONNECTION.md](specs/DATA_CONNECTION.md) | 현행 기준 문서 |
| 문서 전체에서 쟁점을 찾는 계약 | [specs/ISSUE_DISCOVERY.md](specs/ISSUE_DISCOVERY.md) | 설계 |
| 토론 11단계의 선행연구 근거 | [specs/DEBATE_PROTOCOL.md](specs/DEBATE_PROTOCOL.md) | 설계 |
| 시연 진행 | [ops/DEMO.md](ops/DEMO.md) | 운영 |
| 무료 임시 외부 접속(Quick Tunnel) | [ops/LOCAL_ONLINE_DEMO.md](ops/LOCAL_ONLINE_DEMO.md) | 운영 |
| 상시 서버(Render)와 배포 전 과제 | [ops/DEPLOYMENT.md](ops/DEPLOYMENT.md) | 운영 |
| 실제 모델 호출 결과 | [validation/LIVE_VALIDATION.md](../validation/LIVE_VALIDATION.md) | 검증 증거 |
| 외부 호출 전 전송 내용 확인본 | [validation/REMOTE_RUN_PREVIEW.md](../validation/REMOTE_RUN_PREVIEW.md) | 검증 증거 |
| A 조건 입력 규격과 프롬프트 | [study/README.md](../study/README.md) | 2026-11-03 기록 |
| 첫 화면 미리보기 이미지 제작 | [design/stageshow/README.md](../design/stageshow/README.md) · [design/REHEARSAL.md](../design/REHEARSAL.md) | 디자인 자산 |

`data/b/README.md`와 `data/b/review/RECONCILIATION.md`는 Git에서 제외된 로컬 자료 폴더에 있다. 기획 배경 보고서는 상위 작업공간의 `output/report/`에 있다.
