"""Currency conversion with a free, keyless rates feed and sensible offline fallbacks."""
from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger("petesvinyl.currency")

# Rough rates per 1 USD, used only if the internet lookup fails.
FALLBACK_PER_USD = {"USD": 1.0, "NZD": 1.70, "AUD": 1.52, "GBP": 0.76, "EUR": 0.88, "CAD": 1.38}
_cache: dict[str, float] = {}
_fetched_at = 0.0


async def _rates() -> dict[str, float]:
    global _cache, _fetched_at
    if _cache and time.time() - _fetched_at < 12 * 3600:
        return _cache
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://open.er-api.com/v6/latest/USD")
        resp.raise_for_status()
        rates = resp.json().get("rates") or {}
        if rates.get("NZD"):
            _cache, _fetched_at = rates, time.time()
            return _cache
    except (httpx.HTTPError, ValueError) as exc:
        log.info("Using fallback currency rates: %s", exc)
    return FALLBACK_PER_USD


async def convert(amount: float | None, from_cur: str | None, to_cur: str) -> float | None:
    if amount is None:
        return None
    from_cur = (from_cur or "USD").upper()
    to_cur = to_cur.upper()
    if from_cur == to_cur:
        return float(amount)
    rates = await _rates()
    src = rates.get(from_cur) or FALLBACK_PER_USD.get(from_cur)
    dst = rates.get(to_cur) or FALLBACK_PER_USD.get(to_cur)
    if not src or not dst:
        return None
    return float(amount) / src * dst
