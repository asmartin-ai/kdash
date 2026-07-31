import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

HOST = "127.0.0.1"
PORT = 55423
HEALTH_URL = "http://127.0.0.1:55423/health"
CHECK_INTERVAL = 30
START_GRACE = 15
LOCK_PORT = 55426  # distinct from the Python supervisor's lock (55424)
CREATE_NO_WINDOW = 0x08000000
LOG = os.path.join(os.environ["LOCALAPPDATA"], "tokdash", "serve-ts.log")

BUN = r"C:\Users\Kenja\AppData\Local\Microsoft\WinGet\Packages\Oven-sh.Bun_Microsoft.Winget.Source_8wekyb3d8bbwe\bun-windows-x64\bun.exe"
REPO = r"K:\Projects\llm-stack\kdash-ts"


def _bun_exe():
    return BUN if os.path.isfile(BUN) else "bun"


def serve_env():
    env = os.environ.copy()
    env["TOKDASH_HOST"] = "127.0.0.1"
    env["TOKDASH_PORT"] = "55423"
    env["TOKDASH_NO_RETENTION_NOTICE"] = "1"
    return env


def serve_cmd():
    return [
        _bun_exe(), "src/cli.ts", "serve",
        "--host", "127.0.0.1", "--port", "55423",
    ]


def is_healthy(url=HEALTH_URL, timeout=2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} {msg}\n")
    except Exception:
        pass


def acquire_single_instance():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((HOST, LOCK_PORT))
        sock.listen(1)
        return sock
    except Exception:
        return None


def start_serve():
    return subprocess.Popen(
        serve_cmd(),
        env=serve_env(),
        cwd=REPO,
        creationflags=CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main():
    lock = acquire_single_instance()
    if lock is None:
        log("supervisor-ts already running - exiting")
        return
    child = None
    while True:
        try:
            if not is_healthy():
                if child is not None and child.poll() is None:
                    child.terminate()
                log("health check failed - (re)starting kdash-ts serve")
                child = start_serve()
                for _ in range(START_GRACE):
                    time.sleep(1)
                    if is_healthy():
                        log("kdash-ts serve is up")
                        break
                else:
                    log("kdash-ts serve failed to become healthy")
            time.sleep(CHECK_INTERVAL)
        except Exception:
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
