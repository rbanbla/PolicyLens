# 로컬 서버 + 외부 HTTPS 데모

## 실제 경로

다른 기기의 브라우저 → Cloudflare Quick Tunnel 임시 HTTPS 주소 → 이 컴퓨터의 `cloudflared` → `127.0.0.1:8015` Gunicorn/Django → 로컬 PostgreSQL이다. 요약·토론 실행 시 Django가 현재 설정된 `https://llm.ai.hy.miwork.ai/v1`로 모델 입력을 보낸다. 외부에 정적 HTML만 올리면 브라우저가 이 로컬 API에 안정적으로 도달할 수 없어 업로드·요약·토론은 동작하지 않는다.

Cloudflare [Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)은 계정·도메인·유료 서버 없이 임시 주소를 만든다. 주소는 재시작 때 바뀌고 가동 보장이 없다. 이 구성은 당일 데모용이다. 사용자 30명 전원이 26단계 토론을 동시에 돌리는 운영 설정은 아니다.

## 실행

1. `./demo-online.sh`를 실행한다. 스크립트가 `cloudflared`를 확인하고 임시 URL, 공유 비밀번호 파일 경로를 표시한다. 포트 8015를 사용하며 로컬 Gunicorn은 `127.0.0.1`에만 연결된다.
2. 표시된 URL을 브라우저에서 열고 `.demo/credentials.txt`에 적힌 `demo` 사용자명과 비밀번호를 입력한다. 다른 기기에서 첫 화면, `/demo/`, 짧은 모의 문서 업로드·요약·토론을 확인한다.
3. 데모가 끝나면 실행 터미널에서 Ctrl+C를 누른다. 다음 실행에는 새 임시 URL이 발급된다. 비밀번호 파일과 Cloudflare 로그는 `.demo/`에 저장되고 Git에는 포함되지 않는다.

`demo-online.sh`는 터널 주소를 얻은 뒤에 Django를 시작한다. Django는 그 주소 하나만 허용 호스트 및 CSRF 신뢰 출처로 등록하고, 공유 비밀번호 없이는 동적 경로를 열지 않는다. 쿠키는 HTTPS에서만 전송되며, 정적 CSS·이미지는 WhiteNoise가 제공한다. API 키는 로컬 `.env`에만 있다.

## 범위

- 참석자가 올린 PDF·DOCX·TXT 또는 붙여 넣은 원문, 브라우저 세션 요청, 요약·토론 응답은 Cloudflare를 경유한다. 모델 호출 입력은 별도로 현재 모델 제공자에게 전송된다.
- Django는 추출한 문서 본문과 토론 기록을 로컬 PostgreSQL에 저장한다. 자동 삭제 작업은 아직 없다. 개인정보가 없는 데모용 정책 사용을 권한다.
- 외부 접속은 컴퓨터의 전원·네트워크와 Quick Tunnel 상태에 의존한다. [Cloudflare 문서](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)의 동시 진행 요청 상한은 200개지만, 실제 처리량은 로컬 서버와 모델 제공자 한도가 결정한다.
- 공유 비밀번호는 참석자끼리 동일하다. 공개 행사에서 장기간 운영하거나 참가자별 접근 제어가 필요하면 계정·도메인 기반 터널 또는 관리형 서버로 전환한다.
