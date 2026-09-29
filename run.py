"""Start Pete's Vinyl quietly in the background and open it in the browser.

Used by Start_PetesVinyl.bat (via pythonw.exe, so there's no black window to accidentally close).
If the app is already running, this just opens the browser again.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent
PORT = 8000
URL = f"http://localhost:{PORT}"


def port_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def note(message: str) -> None:
    """Write to logs/server.log (pythonw has no console to print to)."""
    try:
        (BASE / "logs").mkdir(exist_ok=True)
        with open(BASE / "logs" / "server.log", "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} launcher: {message}\n")
    except OSError:
        pass


def running_version():
    """None = something is on the port but didn't answer; {} = an old copy with no version endpoint;
    otherwise the server's own report, e.g. {"stale": False}."""
    try:
        with urllib.request.urlopen(f"{URL}/api/version", timeout=3) as resp:
            return json.load(resp)
    except urllib.error.HTTPError:
        return {}   # answered, but doesn't know /api/version: it is an older copy
    except (OSError, ValueError):
        return None


def stop_running_copy() -> None:
    """Stop whatever is listening on the port (an old copy) and close its app window."""
    if os.name == "nt":
        script = (
            f"Get-NetTCPConnection -LocalPort {PORT} -State Listen -ErrorAction SilentlyContinue | "
            "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }; "
            "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
            "Where-Object { $_.CommandLine -like '*edge_profile*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", script], creationflags=0x08000000, timeout=20)
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        subprocess.run(["fuser", "-k", f"{PORT}/tcp"], capture_output=True)
    for _ in range(40):          # wait up to ~10 s for the port to be free
        if not port_in_use():
            return
        time.sleep(0.25)


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
        status = running_version()
        if status is None or (status and not status.get("stale")):
            open_browser()          # already running the current code: just open the window
            return
        note("The running copy is out of date, so restarting it with the new code.")
        stop_running_copy()
        if port_in_use():
            note("Could not stop the old copy (it may have been started as Administrator).")
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
