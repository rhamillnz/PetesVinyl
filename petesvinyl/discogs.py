"""Discogs API: find the exact pressing, get price suggestions, and post marketplace listings.

Get a personal token at https://www.discogs.com/settings/developers (free, instant).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from . import activity, config

log = logging.getLogger("petesvinyl.discogs")
API = "https://api.discogs.com"
USER_AGENT = "PetesVinyl/1.0 +http://localhost:8000"

# Our short condition codes -> Discogs' official grading strings.
CONDITIONS = {
    "M": "Mint (M)",
    "NM": "Near Mint (NM or M-)",
    "VG+": "Very Good Plus (VG+)",
    "VG": "Very Good (VG)",
    "G+": "Good Plus (G+)",
    "G": "Good (G)",
    "F": "Fair (F)",
    "P": "Poor (P)",
}


def is_configured() -> bool:
    return bool(config.get("DISCOGS_API_TOKEN"))


def _headers() -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT}
    token = config.get("DISCOGS_API_TOKEN")
    if token:
        headers["Authorization"] = f"Discogs token={token}"
    return headers


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    shown = ", ".join(f"{k}={v}" for k, v in (params or {}).items() if k not in ("per_page", "type", "format"))
    try:
        async with httpx.AsyncClient(timeout=30, headers=_headers()) as client:
            resp = await client.get(f"{API}{path}", params=params)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        body = exc.response.text[:300] if isinstance(exc, httpx.HTTPStatusError) else str(exc)
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "no reply"
        what, detail = f"GET {path} {shown}", f"{status}: {body}"
        if "seller settings" in body:
            what = "Discogs price suggestion (needs your Discogs seller settings)"
            detail = ("Discogs only gives price suggestions once the seller settings are filled in on the Discogs "
                      "account: go to discogs.com/settings/seller and complete them. Until then the app uses the "
                      "cheapest copy for sale on Discogs instead.")
        activity.record("Discogs", what, False, detail)
        raise
    data = resp.json()
    count = len(data["results"]) if isinstance(data, dict) and "results" in data else ""
    activity.record("Discogs", f"GET {path} {shown}", True, f"{count} results" if count != "" else "OK")
    return data


async def search(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Try the most specific search first (barcode, catalogue number), then artist + title."""
    if not is_configured():
        activity.record("Discogs", "Search skipped: no Discogs token saved in Settings", False)
        return []
    attempts: list[dict[str, Any]] = []
    barcode = "".join(ch for ch in (record.get("barcode") or "") if ch.isdigit())
    if barcode:
        attempts.append({"barcode": barcode})
    if record.get("catalog_number"):
        attempts.append({"catno": record["catalog_number"], "artist": record.get("artist", "")})
    if not (record.get("artist") or record.get("album_title") or barcode):
        activity.record("Discogs", "Search skipped: no artist or album typed in yet", False)
    if record.get("artist") or record.get("album_title"):
        attempts.append({"artist": record.get("artist", ""), "release_title": record.get("album_title", "")})
    for params in attempts:
        params = {k: v for k, v in params.items() if v}
        params.update({"type": "release", "format": "Vinyl", "per_page": 15})
        try:
            data = await _get("/database/search", params)
        except httpx.HTTPError as exc:
            log.warning("Discogs search failed: %s", exc)
            continue
        results = data.get("results") or []
        if not results:
            activity.record("Discogs", "No pressings found for that search", False, str(params))
        if results:
            return _rank(results, record)
    return []


def _rank(results: list[dict[str, Any]], record: dict[str, Any]) -> list[dict[str, Any]]:
    country = (record.get("pressing_location") or "").lower()
    year = str(record.get("year_pressed") or "")[:4]

    def score(r: dict[str, Any]) -> int:
        s = 0
        if country and r.get("country") and r["country"].lower() in country:
            s += 3
        if year and str(r.get("year", "")) == year:
            s += 2
        return s

    ranked = sorted(results, key=score, reverse=True)
    return [
        {
            "id": str(r.get("id")),
            "title": r.get("title"),
            "year": r.get("year"),
            "country": r.get("country"),
            "label": ", ".join(r.get("label") or [])[:80],
            "catno": r.get("catno"),
            "thumb": r.get("thumb") or r.get("cover_image"),
            "url": f"https://www.discogs.com{r['uri']}" if r.get("uri") else "",
        }
        for r in ranked
    ]


async def release(release_id: str) -> dict[str, Any]:
    return await _get(f"/releases/{release_id}", {"curr_abbr": config.get("HOME_CURRENCY")})


async def market_value(release_id: str, condition: str) -> dict[str, Any]:
    """Returns the Discogs suggested price for this condition plus the lowest current listing."""
    out: dict[str, Any] = {"suggested": None, "lowest": None, "num_for_sale": None, "currency": None}
    if not (is_configured() and release_id):
        return out
    try:
        stats = await _get(f"/marketplace/stats/{release_id}", {"curr_abbr": config.get("HOME_CURRENCY")})
        lowest = stats.get("lowest_price") or {}
        out["lowest"] = lowest.get("value")
        out["currency"] = lowest.get("currency")
        out["num_for_sale"] = stats.get("num_for_sale")
    except httpx.HTTPError as exc:
        log.warning("Discogs stats failed: %s", exc)
    try:
        # Needs the Discogs account to have seller settings filled in; fails harmlessly otherwise.
        suggestions = await _get(f"/marketplace/price_suggestions/{release_id}")
        pick = suggestions.get(CONDITIONS.get(condition, CONDITIONS["VG+"])) or {}
        if pick.get("value"):
            out["suggested"] = pick["value"]
            out["currency"] = pick.get("currency") or out["currency"]
    except httpx.HTTPError as exc:
        log.info("Discogs price suggestions unavailable: %s", exc)
    return out


async def create_listing(record: dict[str, Any], price: float, comments: str) -> dict[str, Any]:
    body = {
        "release_id": int(record["discogs_release_id"]),
        "condition": CONDITIONS.get(record.get("condition_media") or "VG+", CONDITIONS["VG+"]),
        "sleeve_condition": CONDITIONS.get(record.get("condition_sleeve") or "VG+", CONDITIONS["VG+"]),
        "price": round(price, 2),
        "status": config.get("DISCOGS_LISTING_STATUS") or "Draft",
        "comments": comments[:255],
    }
    async with httpx.AsyncClient(timeout=30, headers=_headers()) as client:
        resp = await client.post(f"{API}/marketplace/listings", json=body)
    resp.raise_for_status()
    data = resp.json()
    return {"listing_id": data.get("listing_id"), "url": data.get("resource_url", ""), "status": body["status"]}
