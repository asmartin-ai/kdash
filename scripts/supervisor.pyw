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
LOCK_PORT = 55424
CREATE_NO_WINDOW = 0x08000000
LOG = os.path.join(os.environ["LOCALAPPDATA"], "tokdash", "serve.log")


def _python_exe():
    preferred = r"C:\Program Files\Python312\pythonw.exe"
    return preferred if os.path.isfile(preferred) else sys.executable


def serve_env():
    env = os.environ.copy()
    env["TOKDASH_USAGE_DB_WATCH"] = "1"
    env["TOKDASH_USAGE_DB_WATCH_INTERVAL"] = "60"
    env["TOKDASH_HOST"] = "127.0.0.1"
    env["TOKDASH_PORT"] = "55423"
    env["TOKDASH_NO_RETENTION_NOTICE"] = "1"
    env["TOKDASH_LITELLM_PROXY_JSONL"] = os.path.join(
        os.environ["USERPROFILE"], ".tokdash", "litellm-proxy-usage.jsonl"
    )
    return env


def serve_cmd(python_exe=None):
    exe = _python_exe() if python_exe is None else python_exe
    return [
        exe, "-m", "tokdash", "serve", "--no-open",
        "--bind", "127.0.0.1", "--port", "55423",
        "--log-level", "warning",
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
        cwd=os.environ["USERPROFILE"],
        creationflags=CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main():
    lock = acquire_single_instance()
    if lock is None:
        log("supervisor already running - exiting")
        return
    child = None
    while True:
        try:
            if not is_healthy():
                if child is not None and child.poll() is None:
                    child.terminate()
                log("health check failed - (re)starting tokdash serve")
                child = start_serve()
                for _ in range(START_GRACE):
                    time.sleep(1)
                    if is_healthy():
                        log("tokdash serve is up")
                        break
                else:
                    log("tokdash serve failed to become healthy")
            time.sleep(CHECK_INTERVAL)
        except Exception:
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
