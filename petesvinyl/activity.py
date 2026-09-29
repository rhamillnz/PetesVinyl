"""A plain-English activity log of every outside call the app makes (Discogs, OpenRouter, eBay...).

Shown in the app at Settings -> "What has the app been doing?" and saved to logs/activity.log.
Secrets are never written: URLs are logged without tokens and the AI's replies are trimmed.
"""
from __future__ import annotations

import collections
import re
import threading
from datetime import datetime

from .config import LOGS_DIR

_LINE = re.compile(r"^(\d{2} \w{3} \d\d:\d\d:\d\d) \[([^\]]+)\] (OK|FAIL) ?(.*)$")
_events: collections.deque = collections.deque(maxlen=300)
_lock = threading.Lock()


def _load_previous() -> None:
    """Show earlier activity after a restart by reading the saved log file."""
    try:
        lines = (LOGS_DIR / "activity.log").read_text(encoding="utf-8").splitlines()[-100:]
    except OSError:
        return
    for line in lines:
        m = _LINE.match(line)
        if not m:
            continue  # stray fragment from an older, multi-line log format
        time_, source, status, rest = m.groups()
        what, _, detail = rest.partition(" | ")
        _events.appendleft({"time": time_, "source": source, "what": what, "ok": status == "OK", "detail": detail})


_load_previous()


def record(source: str, what: str, ok: bool = True, detail: str = "") -> None:
    ev = {"time": datetime.now().strftime("%d %b %H:%M:%S"), "source": source, "what": what,
          "ok": ok, "detail": detail[:1500]}
    with _lock:
        _events.appendleft(ev)
        try:
            LOGS_DIR.mkdir(exist_ok=True)
            with open(LOGS_DIR / "activity.log", "a", encoding="utf-8") as fh:
                one_line = " ".join(ev["detail"].split())
                fh.write(f"{ev['time']} [{source}] {'OK ' if ok else 'FAIL '}{what}"
                         + (f" | {one_line}" if one_line else "") + "\n")
        except OSError:
            pass


def recent() -> list[dict]:
    with _lock:
        return list(_events)
