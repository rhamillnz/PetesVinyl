"""Discogs API: find the exact pressing, get price suggestions, and post marketplace listings.

Get a personal token at https://www.discogs.com/settings/developers (free, instant).
"""
from __future__ import annotations

import logging
import re
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


RELEASE_LINK = re.compile(r"(?:discogs\.com/(?:[a-z-]+/)?release/|\[r|^r(?=\d+$))(\d+)", re.I)
MASTER_LINK = re.compile(r"(?:discogs\.com/(?:[a-z-]+/)?master/|\[m)(\d+)", re.I)


def clean_artist(name: str) -> str:
    """Discogs numbers artists who share a name, e.g. 'Nirvana (2)'. Drop the number."""
    return re.sub(r"\s*\(\d+\)$", "", name or "").strip()


async def search_text(text: str, record: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """A search typed in by hand, for records the automatic search can't find.

    Accepts plain words (artist, title, label, catalogue number, in any mix), a barcode, or a Discogs web
    address / release number pasted from the Discogs site, which goes straight to that exact pressing.
    A 'master' address lists every pressing of that album.
    """
    text = (text or "").strip()
    if not text or not is_configured():
        return []
    record = record or {}
    found = RELEASE_LINK.search(text)
    if found:
        try:
            rel = await release(found.group(1))
        except httpx.HTTPError:
            return []
        labels = rel.get("labels") or [{}]
        artists = ", ".join(clean_artist(a.get("name", "")) for a in rel.get("artists") or [])
        return [{
            "id": str(rel.get("id")), "title": f"{artists} - {rel.get('title', '')}".strip(" -"),
            "year": rel.get("year"), "country": rel.get("country"), "label": labels[0].get("name", ""),
            "catno": labels[0].get("catno", ""), "thumb": rel.get("thumb") or "",
            "url": rel.get("uri", ""),
        }]
    found = MASTER_LINK.search(text)
    if found:
        try:
            data = await _get(f"/masters/{found.group(1)}/versions", {"per_page": 100})
        except httpx.HTTPError:
            return []
        versions = [v for v in data.get("versions") or [] if "Vinyl" in (v.get("major_formats") or ["Vinyl"])]
        return _rank([{**v, "year": str(v.get("released") or "")[:4], "uri": f"/release/{v.get('id')}",
                       "label": [v.get("label") or ""]} for v in versions], record)
    digits = "".join(ch for ch in text if ch.isdigit())
    attempts: list[dict[str, Any]] = []
    if len(digits) >= 10 and len(digits) >= len(text.replace(" ", "")) - 2:
        attempts.append({"barcode": digits})
    attempts += [{"q": text, "format": "Vinyl"}, {"q": text}]   # records first, then anything (odd formats)
    for params in attempts:
        params = {"type": "release", "per_page": 25, **params}
        try:
            data = await _get("/database/search", params)
        except httpx.HTTPError as exc:
            log.warning("Discogs search failed: %s", exc)
            continue
        if data.get("results"):
            return _rank(data["results"], record)
    activity.record("Discogs", "No pressings found for that typed search", False, text)
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
