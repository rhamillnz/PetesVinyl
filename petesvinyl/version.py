"""A fingerprint of the app's Python code, so a running server can tell it is out of date.

The server records the fingerprint of the code it STARTED with; the launcher (run.py) and the web page compare
that with what is on disk now. If they differ, the app was updated but is still running the old code.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def code_fingerprint() -> str:
    h = hashlib.sha1()
    for path in sorted([BASE / "main.py", *(BASE / "petesvinyl").glob("*.py")]):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:12]


STARTED_WITH = code_fingerprint()


def git_info() -> dict[str, str]:
    """The installed version as a short Git commit id and its date, e.g. {"commit": "92968c0", "date": "2026-10-20"}.
    Empty if this copy isn't linked to Git (installed from a ZIP) or Git isn't installed."""
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%h|%cd", "--date=short"], cwd=BASE, capture_output=True,
                             text=True, timeout=4, creationflags=0x08000000 if os.name == "nt" else 0)
        commit, _, date = out.stdout.strip().partition("|")
        return {"commit": commit, "date": date} if out.returncode == 0 and commit else {}
    except (OSError, subprocess.SubprocessError):
        return {}
