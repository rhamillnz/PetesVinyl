"""A fingerprint of the app's Python code, so a running server can tell it is out of date.

The server records the fingerprint of the code it STARTED with; the launcher (run.py) and the web page compare
that with what is on disk now. If they differ, the app was updated but is still running the old code.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def code_fingerprint() -> str:
    h = hashlib.sha1()
    for path in sorted([BASE / "main.py", *(BASE / "petesvinyl").glob("*.py")]):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:12]


STARTED_WITH = code_fingerprint()
