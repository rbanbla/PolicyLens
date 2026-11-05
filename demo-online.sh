#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077

if ! command -v cloudflared >/dev/null; then
    echo "cloudflared가 필요합니다. brew install cloudflared 실행 후 다시 시작해 주세요." >&2
    exit 1
fi
port="${POLICYLENS_PORT:-8015}"
if [[ ! "$port" =~ ^[0-9]{2,5}$ ]]; then
    echo "POLICYLENS_PORT는 포트 번호여야 합니다." >&2
    exit 1
fi

mkdir -p .demo
if [[ ! -s .demo/password ]]; then
    python3 -c 'import secrets; print(secrets.token_urlsafe(18))' > .demo/password
fi
password=$(cat .demo/password)
printf '사용자명: demo\n비밀번호: %s\n' "$password" > .demo/credentials.txt

cloudflared tunnel --url "http://127.0.0.1:$port" --loglevel info > .demo/cloudflared.log 2>&1 &
tunnel_pid=$!
cleanup() {
    kill "$tunnel_pid" 2>/dev/null || true
    wait "$tunnel_pid" 2>/dev/null || true
}
trap cleanup EXIT

url=""
for _ in {1..60}; do
    url=$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' .demo/cloudflared.log | head -n 1 || true)
    if [[ -n "$url" ]]; then break; fi
    if ! kill -0 "$tunnel_pid" 2>/dev/null; then break; fi
    sleep 1
done
if [[ -z "$url" ]]; then
    echo "임시 HTTPS 주소를 받지 못했습니다. .demo/cloudflared.log를 확인해 주세요." >&2
    exit 1
fi

export POLICYLENS_PUBLIC_ORIGIN="$url"
export POLICYLENS_DEMO_USER=demo
export POLICYLENS_DEMO_PASSWORD="$password"
export POLICYLENS_PORT="$port"
export POLICYLENS_SERVE_MODE=gunicorn
printf '%s\n' "$url" > .demo/current-url.txt
echo "외부 접속: $url"
echo "참석자 로그인 정보: $PWD/.demo/credentials.txt"
echo "이 터미널을 닫거나 Ctrl+C를 누르면 외부 접속이 종료됩니다."
./start.sh
