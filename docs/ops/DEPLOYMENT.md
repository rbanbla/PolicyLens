# 외부 서버 설계 · Render

## 구성

브라우저 → Render HTTPS 웹 서비스(Django, Gunicorn, WhiteNoise) → Render 관리형 PostgreSQL이다. 모델 호출은 Django 서버에서만 현재 설정된 Chat Completions 호환 제공자로 나간다. 기존 `start.sh`와 `.pgdata/`는 로컬 개발용으로 유지한다. 배포 서버는 `render.yaml`과 `deploy/` 스크립트를 쓴다.

선택한 리전은 싱가포르다. 웹은 `1c-2g`(1 CPU, 2GB), DB는 `0.1c-256mb`(100개 연결)의 유료 상시 실행 플랜이다. 30명 미만의 파일럿에서 페이지 열람과 몇 개의 동시 모델 실행을 위한 시작값이다. 30명이 같은 순간 전체 26단계 토론을 실행하는 용량을 보장하는 설정은 아니며, 이 경우 별도 작업 큐와 모델 제공자 한도 확인이 필요하다. [무료 플랜의 유휴 정지와 30일 만료 DB](https://render.com/docs/free)는 당일 시연의 기본값으로 쓰지 않는다.

2026-11-05 기준 [Render 표시 가격](https://render.com/pricing)은 웹 $25/월, DB $6/월, DB 스토리지 1GB 초과분 $0.30/GB/월이다. `diskSizeGB: 5`이므로 최소 구성은 대략 $32.20/월에 모델 사용료, 사용량 초과 네트워크, 세금 등이 더해질 수 있다. 실제 결제 금액은 생성 전 Render 화면에서 확인한다.

## 데이터 경계

- `deploy/seed.json.gz`: 공개 모의 정책 1개, 출처 메타데이터 15,101개, B 근거 3,006개, 합성 프로필 40개, 검토 후보 91개. 기존 로컬 DB에서 추출한 비사용자 자료다. 최초 빈 DB에 한 번만 적재한다.
- 업로드 문서, 사용자 세션, 요약 캐시, 토론 실행 기록, 연구자 계정, API 키는 초기 데이터에 포함하지 않았다. 배포 후 사용자가 업로드한 텍스트와 실행 결과는 Render PostgreSQL에 저장된다.
- `research/` 약 5.7GB와 `data/b/`의 원본 수집 파일은 Git/Render 배포에 넣지 않는다. 현재 근거 검색은 DB의 선별된 텍스트를 사용한다. `/sources/`의 파일 상태는 **수집 당시** 원본 확인 여부다.
- 시연 종료 후 Render DB에 남은 세션과 생성 기록의 삭제 또는 DB 제거를 운영자가 결정해야 한다. 현 버전에는 자동 만료 작업이 없다.

## 생성 절차

1. `policylens/`만 **비공개 GitHub 저장소**의 루트로 올린다. `.gitignore`로 로컬 `.env`, DB, 연구 원본, 수집 원본, 가상환경을 제외한다. `render.yaml`과 `deploy/seed.json.gz`가 포함됐는지 확인한다.
2. Render에서 [New Blueprint Instance](https://render.com/docs/deploy-django)를 만들고 해당 저장소를 연결해 `render.yaml`을 적용한다. 이 단계에서 유료 웹·DB가 생성되므로 비용 확인 후 실행한다.
3. 첫 생성 화면의 비밀 환경변수에 `POLICYLENS_DEMO_PASSWORD`와 `OPENAI_API_KEY`를 입력한다. 제공자 주소 `https://llm.ai.hy.miwork.ai/v1`, 호출 방식 `chat_completions`, 요약·토론 모델 `gpt-5.6-luna`는 현재 검증된 값으로 `render.yaml`에 지정했다. 채팅에 한 번 노출된 이전 API 키는 재발급해 새 키를 설정한다.
4. 빌드에서 최소 Python 의존성과 정적 파일을 준비한다. 배포 전 명령이 DB 마이그레이션과 초기 데이터 적재를 실행한다. 같은 배포를 다시 실행해도 기존 B 근거가 있으면 초기 적재를 건너뛴다.
5. Render의 `https://...onrender.com/health/`가 `ok`를 반환하는지 확인한다. 공유 비밀번호로 첫 화면, `/policies/`, `/sources/`, `/demo/`를 확인한다. 마지막으로 개인정보가 없는 짧은 문서로 업로드와 요약 1회, 필요하면 토론 1개 단계를 검증한다.

## 설정과 접근

`DJANGO_SECRET_KEY`는 Render가 생성하고 `DATABASE_URL`은 관리형 DB의 내부 연결 문자열에서 받는다. API 키와 공유 비밀번호는 저장소에 넣지 않는다. Render에서 비밀번호가 빠지면 앱이 시작되지 않게 했고, `/health/` 이외의 동적 경로에는 Basic Auth를 적용했다. 정적 CSS·이미지는 WhiteNoise가 제공한다. Render의 HTTPS 주소를 Django 허용 호스트 및 CSRF 출처로 등록한다.

이 구성은 당일 데모와 작은 파일럿용이다. 실제 연구 참여자가 30명 가까이 동시에 26단계를 돌릴 경우에는 작업 큐·진행 상태 API, 운영자별 호출 상한, 실패 재시도 정책, 데이터 보존 기간을 추가한 후 부하와 비용을 검증해야 한다.

## 2026-11-05 사전 점검

`git archive`로 만든 깨끗한 복사본과 빈 PostgreSQL에서 Render 조건(`RENDER=true`, `requirements-deploy.txt`, Python 3.11)을 흉내 내어 `collectstatic → migrate → seed_deploy → deploy/start.sh`를 실행했다. 모두 코드 수정 없이 통과했다. 시드 재실행은 건너뛰었고 `/health/`는 인증 없이 200, 나머지 경로는 인증 없이 401, 인증 시 정상 응답했다. Render 실제 서비스나 모델 호출을 검증한 것은 아니다.

측정값: DB 28MB, 시드 적재 약 5초·최대 메모리 약 165MB, Gunicorn 프로세스 합계 약 150MB(유휴 상태). 부하 상태의 메모리는 재지 않았다. `render.yaml`의 플랜 ID는 Render 공개 스키마에 있다.

### 서버 생성 전에 확인할 것

- [ ] 모델 제공자가 Render 싱가포르 IP에서 접속을 허용하는가. 현재 호출은 이 컴퓨터에서만 검증했다.
- [ ] 40쪽 이상 실제 정책으로 요약·토론을 1회 끝까지 실행한다. 지금까지의 완주 검증은 짧은 모의 정책이고 호출 제한시간은 60초다.
- [ ] 노출됐던 API 키를 재발급했는가.

### 코드 과제

- [ ] 콘솔 로깅 추가. `DEBUG=False`에 `LOGGING`이 없어 500 오류의 스택트레이스가 서버 로그에 남지 않는다.
- [ ] 연구자 계정 생성 경로. 배포 DB의 사용자는 0명이고 절차에 생성 단계가 없어 `/admin/`, `/research/`를 쓸 수 없다.
- [ ] 세션 하나의 토론 수와 일일 호출 상한. 공유 비밀번호를 아는 사람은 모델 비용을 제한 없이 쓸 수 있다.
- [ ] 보존 기간과 삭제 작업. 업로드 본문은 세션과 DebatePair에 남고 자동 삭제가 없다. 연구 참여자를 받기 전에 정한다.
- [ ] 동시 사용 시험. `--workers 2 --threads 4`는 동시 모델 호출 8개가 상한이다. 토론은 호출마다 모델 응답이 올 때까지 DB 트랜잭션과 행 잠금을 유지하므로, 실행 중 프로세스가 죽으면 받은 응답도 롤백된다.
