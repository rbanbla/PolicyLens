"""One-command local PolicyLens server control; no external tunnel."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".local" / "server.pid"
LOG = ROOT / ".local" / "server.log"
START = ROOT / "start.sh"
URL = "http://127.0.0.1:8000/"


def command(pid):
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


def managed_pid():
    try:
        pid = int(STATE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    return pid if str(START) in command(pid) else None


def ready():
    try:
        with urlopen(URL + "health/", timeout=2) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def start():
    pid = managed_pid()
    if pid:
        print(f"이미 실행 중입니다: {URL} (PID {pid})")
        return 0
    if ready():
        print(f"포트 8000에서 다른 서버가 실행 중입니다: {URL}")
        print("기존 서버를 종료한 뒤 다시 실행해 주세요.")
        return 1
    STATE.parent.mkdir(exist_ok=True)
    os.chmod(STATE.parent, 0o700)
    environment = os.environ.copy()
    for name in ("POLICYLENS_PUBLIC_ORIGIN", "POLICYLENS_DEMO_PASSWORD",
                 "POLICYLENS_DEMO_USER", "POLICYLENS_SERVE_MODE"):
        environment.pop(name, None)
    environment["POLICYLENS_PORT"] = "8000"
    with LOG.open("a") as output:
        process = subprocess.Popen(
            ["bash", str(START)], cwd=ROOT, env=environment,
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    STATE.write_text(f"{process.pid}\n")
    os.chmod(STATE, 0o600)
    for _ in range(60):
        if ready():
            print(f"로컬 서버 실행: {URL}")
            return 0
        if process.poll() is not None:
            STATE.unlink(missing_ok=True)
            print(f"서버 시작에 실패했습니다. 로그: {LOG}")
            return 1
        time.sleep(1)
    print(f"서버가 준비 중입니다. 상태: ./server.sh status · 로그: {LOG}")
    return 0


def stop():
    pid = managed_pid()
    if not pid:
        STATE.unlink(missing_ok=True)
        print("이 명령으로 실행한 로컬 서버가 없습니다.")
        return 0
    os.killpg(pid, signal.SIGTERM)
    for _ in range(30):
        if not command(pid):
            STATE.unlink(missing_ok=True)
            print("로컬 서버를 종료했습니다.")
            return 0
        time.sleep(1)
    print(f"서버 종료를 기다리고 있습니다. 로그: {LOG}")
    return 1


def status():
    pid = managed_pid()
    if pid:
        print(f"실행 중: {URL} (PID {pid})" if ready() else f"시작 중: PID {pid} · {LOG}")
    else:
        print("이 명령으로 실행한 로컬 서버가 없습니다.")
    return 0


if __name__ == "__main__":
    actions = {"start": start, "stop": stop, "status": status}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        print("사용법: ./server.sh start|stop|status")
        raise SystemExit(2)
    raise SystemExit(actions[sys.argv[1]]())
