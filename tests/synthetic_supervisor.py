"""Supervisor mínimo para los ensayos locales de Gunicorn."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def running(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0] != "Z"
    except FileNotFoundError:
        return False


def main():
    folder = Path(sys.argv[1])
    pidfile = folder / "pid"
    if sys.argv[2] == "start":
        if pidfile.exists() and running(int(pidfile.read_text())):
            return
        with (folder / "gunicorn.log").open("ab") as log:
            process = subprocess.Popen(
                sys.argv[3:], stdout=log, stderr=log,
                start_new_session=True,
            )
        pidfile.write_text(str(process.pid))
        return
    if pidfile.exists():
        pid = int(pidfile.read_text())
        if running(pid):
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 6
            while running(pid):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Gunicorn sigue en ejecución")
                time.sleep(0.05)
        pidfile.unlink()
    failure = folder / "fail-stop"
    if failure.exists():
        failure.unlink()
        raise SystemExit(7)


if __name__ == "__main__":
    main()
