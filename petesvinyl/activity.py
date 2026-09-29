"""A plain-English activity log of every outside call the app makes (Discogs, OpenRouter, eBay...).

Shown in the app at Settings -> "What has the app been doing?" and saved to logs/activity.log.
Secrets are never written: URLs are logged without tokens and the AI's replies are trimmed.
"""
from __future__ import annotations

import collections
import threading
from datetime import datetime

from .config import LOGS_DIR

_events: collections.deque = collections.deque(maxlen=300)
_lock = threading.Lock()


def record(source: str, what: str, ok: bool = True, detail: str = "") -> None:
    ev = {"time": datetime.now().strftime("%d %b %H:%M:%S"), "source": source, "what": what,
          "ok": ok, "detail": detail[:1500]}
    with _lock:
        _events.appendleft(ev)
        try:
            LOGS_DIR.mkdir(exist_ok=True)
            with open(LOGS_DIR / "activity.log", "a", encoding="utf-8") as fh:
                fh.write(f"{ev['time']} [{source}] {'OK ' if ok else 'FAIL '}{what}"
                         + (f" | {ev['detail']}" if ev["detail"] else "") + "\n")
        except OSError:
            pass


def recent() -> list[dict]:
    with _lock:
        return list(_events)
