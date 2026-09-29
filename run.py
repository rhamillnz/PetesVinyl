"""Start Pete's Vinyl quietly in the background and open it in the browser.

Used by Start_PetesVinyl.bat (via pythonw.exe, so there's no black window to accidentally close).
If the app is already running, this just opens the browser again.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent
PORT = 8000
URL = f"http://localhost:{PORT}"


def port_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def open_browser() -> None:
    """Prefer Microsoft Edge in 'app mode' (no tabs or address bar - looks like a real program)."""
    edge_paths = [
        shutil.which("msedge"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in edge_paths:
        if path and os.path.exists(path):
            # Its own private profile, so the Stop button can close exactly this window and nothing else.
            subprocess.Popen([path, f"--app={URL}", "--start-maximized", f"--user-data-dir={BASE / 'edge_profile'}",
                              "--no-first-run", "--no-default-browser-check"])
            return
    webbrowser.open(URL)


def open_when_ready() -> None:
    for _ in range(60):
        if port_in_use():
            open_browser()
            return
        time.sleep(0.5)


def main() -> None:
    os.chdir(BASE)
    if port_in_use():
        open_browser()
        return
    logs = BASE / "logs"
    logs.mkdir(exist_ok=True)
    log_file = open(logs / "server.log", "a", encoding="utf-8", buffering=1)
    # pythonw has no console; send all output to a log file instead.
    sys.stdout = sys.stderr = log_file
    (logs / "server.pid").write_text(str(os.getpid()))
    threading.Thread(target=open_when_ready, daemon=True).start()

    import uvicorn
    sys.path.insert(0, str(BASE))
    uvicorn.run("main:app", host="127.0.0.1", port=PORT, log_config=None)


if __name__ == "__main__":
    main()
