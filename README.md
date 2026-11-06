# PolicyLens v2

공공정책 문서에서 이해관계자를 추출하고, 역할별 입장과 토론으로 논쟁 지점을 찾아, 내 입장에서 주의할 조항과 역할별 의견서를 만드는 독립 Django 프로젝트다. 부동산, 세금, 청년 정책처럼 주제가 다른 문서를 같은 절차로 다룬다. 실제 모델 API를 사용하며 모의 응답은 테스트에서만 사용한다.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# .env에 API 키, 제공자, 모델 이름 입력
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 127.0.0.1:8001
```

영어 화면 문구는 `locale/en/LC_MESSAGES/django.po`에 있다. 문구를 고친 뒤 `.venv/bin/python manage.py makemessages -l en --ignore='.venv/*'`로 목록을 갱신하고 `msgfmt -o locale/en/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.po`로 컴파일한다.

## 사용 흐름

화면은 문서 넣기 → 핵심 요약·입장 선택 → 입장 나누기 → 쟁점 토론 → 주의 조항의 다섯 페이지다. 역할 수 N은 문서마다 2~3명이며 모델 호출은 분석 1회와 검토 `2N + 2`회로, 3명이면 9회, 2명이면 7회다. 서버 자료를 쓰면 역할과 최종 단계에 검색 호출이 더해져 3명 기준 13~16회가 된다. 실제 API 호출은 비용이 발생한다.

입장을 선택하면 3페이지의 독립 입장과 쟁점 정리가 자동 진행된다. 페이지를 넘기는 버튼을 누르면 4페이지의 쟁점 토론, 5페이지의 주의 조항 정리가 이어진다. 오류가 나면 멈추고 재시작 버튼으로 저장된 단계부터 이어간다. 세션 소유자만 검토에 접근한다.

5페이지는 수정 문구가 아니라 내 입장의 주의 조항, 확인할 것, 담당 기관에 물어볼 질문, 불확실한 부분을 보여준다. 역할별 의견서는 토론 결과를 서버가 조립하며 추가 호출이 없고 텍스트 파일로 내려받는다. 실제 제출은 사용자가 직접 한다.

## 비교 평가

5페이지의 **두 결과 비교하기**에서 **비교 결과 만들기**를 누르면 같은 문서와 입장으로 단일 프롬프트 답변을 만든다(호출 1회 추가). 두 결과를 A·B로 나란히 보고 평가를 저장하면 어느 쪽이 어떤 방식인지 공개된다. 평가 결과는 `.venv/bin/python manage.py dumpdata server.reviewrun --indent 2`로 내보낸다. 이 출력에는 문서 원문이 포함된다.

현재 입력은 PDF·TXT·붙여넣기를 지원한다. 실행 중 외부 호출은 동기식이며 개발용 SQLite 트랜잭션 안에서 진행한다.

## 서버 자료

역할 에이전트, 토론, 최종 정리는 입력 문서 밖의 공개 자료를 서버에서 찾아 근거로 쓴다. `data/reviewed/documents.jsonl`과 `data/processed/`를 준비한 뒤 `.venv/bin/python manage.py load_sources`로 적재한다. 검수를 통과한 문서만 올라가고, 적재된 자료가 없으면 문서만 읽는다.

## 평가

`.venv/bin/python manage.py evaluate <doc_id>`는 문서 하나를 서비스와 같은 파이프라인으로 실행해 `data/reviewed/runs/`에 저장한다. 문서 발행일 이전의 정책 자료만 보며, `--no-sources`를 붙이면 서버 자료 없이 실행한다. `.venv/bin/python manage.py score`는 저장된 결과가 정답 초안의 쟁점을 언급하는지 키워드로 세며 사람 채점을 대신하지 않는다.

제품 계약은 docs/PRODUCT_PLAN.md, 작업 규칙은 AGENTS.md, 화면 규칙은 docs/DESIGN.md, 검증 기록은 docs/IMPLEMENTATION_STATUS.md, 데이터 수집과 평가는 docs/DATA_PLAN.md를 따른다. `.venv/bin/python manage.py test server`로 회귀 검증을 실행한다.
