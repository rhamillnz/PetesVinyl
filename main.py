"""PetesVinyl - FastAPI backend.

Run with:  uvicorn main:app --port 8000   (or double-click Start_PetesVinyl.bat on Windows)
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
import re
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from petesvinyl import popsike, version, activity, ai, backup, config, db, discogs, listings, publishers, valuation
from petesvinyl.config import IMAGES_DIR, STATIC_DIR
from petesvinyl.db import IMAGE_SLOTS, PLATFORMS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("petesvinyl")

_last_change = 0.0
_last_backup = 0.0


def mark_changed() -> None:
    global _last_change
    _last_change = time.time()


async def backup_loop() -> None:
    """Every 15 minutes, back up to Google Drive if anything changed (and at least every N hours)."""
    global _last_backup
    await asyncio.sleep(60)
    while True:
        every = config.get_float("BACKUP_EVERY_HOURS", 6) * 3600
        due = _last_change > _last_backup or time.time() - _last_backup > every
        if due and backup.backup_folder() is not None:
            _last_backup = time.time()
            result = await asyncio.to_thread(backup.run_backup, "automatic")
            log.info("Automatic backup: %s", result["message"])
        await asyncio.sleep(15 * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    db.connect()
    task = asyncio.create_task(backup_loop())
    yield
    task.cancel()
    await publishers.shutdown_browser()
    db.close()


app = FastAPI(title="PetesVinyl", lifespan=lifespan)


# --------------------------------------------------------------------------- models
class RecordFields(BaseModel):
    artist: Optional[str] = None
    album_title: Optional[str] = None
    year_pressed: Optional[str] = None
    original_year: Optional[str] = None
    pressing_location: Optional[str] = None
    label: Optional[str] = None
    catalog_number: Optional[str] = None
    barcode: Optional[str] = None
    matrix_numbers: Optional[str] = None
    is_first_owner: Optional[bool] = None
    number_of_owners: Optional[int] = Field(default=None, ge=1, le=50)
    condition_media: Optional[str] = None
    condition_sleeve: Optional[str] = None
    disc_count: Optional[int] = Field(default=None, ge=1, le=20)
    media_scratches: Optional[str] = None      # none / light / some / deep
    media_play: Optional[str] = None           # perfect / crackle / noisy / skips
    cover_creases: Optional[str] = None        # none / slight / noticeable / bad
    cover_issues: Optional[list[str]] = None   # seam_split, ring_wear, writing, stain, tear
    notes: Optional[str] = None
    discogs_release_id: Optional[str] = None
    suggested_price: Optional[float] = None


class RecordIn(RecordFields):
    # Base64 JPEG frames (data URLs are fine) keyed front / back / disc_a / disc_b.
    images: dict[str, str] = Field(default_factory=dict)
    # Names for extra photos, e.g. {"extra_1": "Disc 2 - Side A label"}
    extra_labels: dict[str, str] = Field(default_factory=dict)


class ValueRequest(BaseModel):
    artist: str = ""
    album_title: str = ""
    year_pressed: str = ""
    record_id: Optional[int] = None
    pressing_location: Optional[str] = None
    catalog_number: Optional[str] = None
    condition_media: Optional[str] = None
    discogs_release_id: Optional[str] = None


class SyndicateRequest(BaseModel):
    record_id: int
    platforms: list[str]


class StatusUpdate(BaseModel):
    platform: str
    status: str
    link: Optional[str] = None


class SoldRequest(BaseModel):
    price: float = Field(ge=0)
    platform: str = ""


class DiscogsMatch(BaseModel):
    release_id: str


# --------------------------------------------------------------------------- helpers
def _require(record_id: int) -> dict[str, Any]:
    rec = db.get_record(record_id)
    if rec is None:
        raise HTTPException(404, "Record not found")
    return rec


EXTRA_KEY = re.compile(r"^extra_\d{1,3}$")


def _save_images(record_id: int, images: dict[str, str], labels: dict[str, str] | None = None) -> dict[str, Any]:
    """Decode base64 frames and write them to images/record_<id>/<slot>_<time>.jpg.

    The four standard slots (front/back/disc_a/disc_b) map to their own columns; any number of extra
    photos (more discs, inserts, artwork, close-ups) are keyed extra_1, extra_2... and kept in extra_images.
    """
    labels = labels or {}
    folder = IMAGES_DIR / f"record_{record_id}"
    folder.mkdir(parents=True, exist_ok=True)
    existing = db.get_record(record_id) or {}
    extras = {e["key"]: dict(e) for e in existing.get("extra_images") or [] if e.get("key")}
    saved: dict[str, Any] = {}
    extras_changed = False
    for slot, data in images.items():
        is_extra = bool(EXTRA_KEY.match(slot))
        if (slot not in IMAGE_SLOTS and not is_extra) or not data:
            continue
        if "," in data[:100]:
            data = data.split(",", 1)[1]
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(400, f"Photo '{slot}' isn't valid base64") from exc
        rel = f"record_{record_id}/{slot}_{int(time.time() * 1000)}.jpg"
        (IMAGES_DIR / rel).write_bytes(raw)
        if is_extra:
            old = (extras.get(slot) or {}).get("path")
            label = (labels.get(slot) or (extras.get(slot) or {}).get("label") or "Extra photo").strip()[:80]
            extras[slot] = {"key": slot, "path": rel, "label": label}
            extras_changed = True
        else:
            old = existing.get(IMAGE_SLOTS[slot])
            saved[IMAGE_SLOTS[slot]] = rel
        if old and old != rel:
            (IMAGES_DIR / old).unlink(missing_ok=True)
    if extras_changed:
        saved["extra_images"] = sorted(extras.values(), key=lambda e: int(e["key"].split("_")[1]))
    return saved


def _image_files(rec: dict[str, Any]) -> dict[str, Path]:
    return {slot: IMAGES_DIR / rec[col] for slot, col in IMAGE_SLOTS.items() if rec.get(col)}


# --------------------------------------------------------------------------- records
@app.get("/api/version")
def app_version() -> dict[str, Any]:
    on_disk = version.code_fingerprint()
    return {"running": version.STARTED_WITH, "on_disk": on_disk, "stale": on_disk != version.STARTED_WITH}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "ai": ai.is_configured(),
        "discogs": discogs.is_configured(),
        "backup": backup.status(),
    }


@app.get("/api/records")
def list_records(q: str = "", state: str = "") -> dict[str, Any]:
    return {"records": db.list_records(q, state), "stats": db.stats()}


@app.get("/api/records/{record_id}")
def get_record(record_id: int) -> dict[str, Any]:
    return _require(record_id)


@app.post("/api/records")
def create_record(body: RecordIn) -> dict[str, Any]:
    fields = body.model_dump(exclude={"images", "extra_labels"}, exclude_none=True)
    fields.setdefault("is_first_owner", True)
    fields.setdefault("number_of_owners", 1)
    record_id = db.create_record(fields)
    if body.images:
        db.update_record(record_id, _save_images(record_id, body.images, body.extra_labels))
    mark_changed()
    return _require(record_id)


@app.put("/api/records/{record_id}")
def update_record(record_id: int, body: RecordIn) -> dict[str, Any]:
    _require(record_id)
    fields = body.model_dump(exclude={"images", "extra_labels"}, exclude_none=True)
    if fields.get("is_first_owner") and "number_of_owners" not in fields:
        fields["number_of_owners"] = 1
    if body.images:
        fields.update(_save_images(record_id, body.images, body.extra_labels))
    db.update_record(record_id, fields)
    mark_changed()
    return _require(record_id)


@app.delete("/api/records/{record_id}")
def delete_record(record_id: int) -> dict[str, Any]:
    rec = _require(record_id)
    for path in _image_files(rec).values():
        path.unlink(missing_ok=True)
    for extra in rec.get("extra_images") or []:
        (IMAGES_DIR / extra.get("path", "")).unlink(missing_ok=True)
    db.delete_record(record_id)
    mark_changed()
    return {"ok": True}


@app.delete("/api/records/{record_id}/extra/{key}")
def delete_extra_photo(record_id: int, key: str) -> dict[str, Any]:
    rec = _require(record_id)
    keep = []
    for extra in rec.get("extra_images") or []:
        if extra.get("key") == key:
            (IMAGES_DIR / extra.get("path", "")).unlink(missing_ok=True)
        else:
            keep.append(extra)
    db.update_record(record_id, {"extra_images": keep})
    mark_changed()
    return _require(record_id)


# --------------------------------------------------------------------------- identification
@app.post("/api/records/{record_id}/identify")
async def identify(record_id: int) -> dict[str, Any]:
    """Ask the AI to read the photos, then look for the exact pressing on Discogs."""
    rec = _require(record_id)
    result: dict[str, Any] = {"explanation": "", "confidence": "", "error": ""}
    if ai.is_configured():
        try:
            found = await ai.identify_record(_image_files(rec))
            result["explanation"] = found.get("explanation", "")
            result["confidence"] = found.get("confidence", "")
            updates = {k: str(v).strip() for k, v in found.items()
                       if k in db.COLUMN_NAMES and v not in (None, "", 0, False)}
            if found.get("explanation"):
                updates["ai_summary"] = found["explanation"]
            db.update_record(record_id, updates)
            rec = _require(record_id)
        except (ai.AIUnavailable, ValueError) as exc:
            result["error"] = str(exc)
    else:
        activity.record("OpenRouter", "Photo reading skipped: no OpenRouter key saved in Settings", False)
        result["error"] = "No AI key set up yet, so please type the details in (or add an OpenRouter key in Settings)."

    matches = await discogs.search(rec)
    if matches and not rec.get("discogs_release_id"):
        db.update_record(record_id, {"discogs_release_id": matches[0]["id"], "discogs_url": matches[0]["url"]})
        rec = _require(record_id)
    mark_changed()
    return {"record": rec, "ai": result, "discogs_matches": matches[:8]}


@app.get("/api/records/{record_id}/discogs-matches")
async def discogs_matches(record_id: int) -> dict[str, Any]:
    return {"matches": (await discogs.search(_require(record_id)))[:12], "configured": discogs.is_configured()}


@app.post("/api/records/{record_id}/discogs-match")
async def choose_discogs_match(record_id: int, body: DiscogsMatch) -> dict[str, Any]:
    """Pete picked the right pressing from the list - copy its details onto the record."""
    rec = _require(record_id)
    updates: dict[str, Any] = {"discogs_release_id": body.release_id}
    try:
        rel = await discogs.release(body.release_id)
        labels = rel.get("labels") or [{}]
        barcodes = [i.get("value", "") for i in rel.get("identifiers") or [] if i.get("type") == "Barcode"]
        matrix = [i.get("value", "") for i in rel.get("identifiers") or [] if i.get("type") == "Matrix / Runout"]
        updates.update({
            "artist": rec.get("artist") or ", ".join(a.get("name", "") for a in rel.get("artists") or []),
            "album_title": rec.get("album_title") or rel.get("title", ""),
            "year_pressed": str(rel.get("year") or rec.get("year_pressed") or ""),
            "pressing_location": rel.get("country") or rec.get("pressing_location") or "",
            "label": labels[0].get("name", ""),
            "catalog_number": labels[0].get("catno", ""),
            "barcode": rec.get("barcode") or (barcodes[0] if barcodes else ""),
            "matrix_numbers": rec.get("matrix_numbers") or " / ".join(matrix[:2]),
            "discogs_url": rel.get("uri", ""),
        })
    except Exception as exc:  # noqa: BLE001 - keep the chosen id even if details fail
        log.warning("Could not fetch Discogs release %s: %s", body.release_id, exc)
    db.update_record(record_id, updates)
    mark_changed()
    return _require(record_id)


# --------------------------------------------------------------------------- valuation
@app.post("/api/estimate-value")
async def estimate_value(body: ValueRequest) -> dict[str, Any]:
    rec: dict[str, Any] = {}
    if body.record_id:
        rec = dict(_require(body.record_id))
    rec.update({k: v for k, v in body.model_dump(exclude={"record_id"}).items() if v})
    result = await valuation.estimate(rec)
    result["recommended_platforms"] = listings.recommend(result["suggested_price"])
    if body.record_id:
        db.update_record(body.record_id, {
            "discogs_median": result["discogs_median"],
            "ebay_sold_average": result["ebay_sold_average"],
            "popsike_median": result["popsike_median"],
            "ai_estimate": result["ai_estimate"],
            "estimated_value": result["estimated_value"],
            "suggested_price": result["suggested_price"],
            "valuation_notes": "\n".join(result["notes"]),
            "valued_at": db.now(),
            "recommended_platforms": result["recommended_platforms"],
        })
        mark_changed()
    return result


# --------------------------------------------------------------------------- selling
@app.get("/api/platforms")
def platforms() -> dict[str, Any]:
    enabled = listings.enabled_platforms()
    return {"platforms": [{"id": pid, **meta, "enabled": pid in enabled} for pid, meta in listings.PLATFORMS.items()]}


@app.get("/api/records/{record_id}/listing/{platform}")
async def listing_helper(record_id: int, platform: str) -> dict[str, Any]:
    if platform not in listings.PLATFORMS:
        raise HTTPException(404, "Unknown site")
    return await listings.build(_require(record_id), platform)


@app.post("/api/syndicate")
async def syndicate(body: SyndicateRequest) -> dict[str, Any]:
    """'Sell it!' - post automatically where we can, prepare copy-and-paste listings everywhere else."""
    rec = _require(body.record_id)
    if not rec.get("suggested_price"):
        raise HTTPException(400, "Please check the price first.")
    results = {}
    links = dict(rec.get("listing_links") or {})
    updates: dict[str, Any] = {}
    for platform in body.platforms:
        if platform not in listings.PLATFORMS:
            continue
        res = await publishers.publish(rec, platform)
        results[platform] = res
        updates[f"{platform}_status"] = res["status"]
        if res.get("url"):
            links[platform] = res["url"]
    updates["listing_links"] = links
    db.update_record(body.record_id, updates)
    mark_changed()
    return {"results": results, "record": _require(body.record_id)}


@app.post("/api/records/{record_id}/platform-status")
def set_platform_status(record_id: int, body: StatusUpdate) -> dict[str, Any]:
    rec = _require(record_id)
    if body.platform not in PLATFORMS:
        raise HTTPException(404, "Unknown site")
    if body.status not in {"not_listed", "ready", "draft", "listed", "sold", "ended"}:
        raise HTTPException(400, "Unknown status")
    updates: dict[str, Any] = {f"{body.platform}_status": body.status}
    if body.link is not None:
        links = dict(rec.get("listing_links") or {})
        links[body.platform] = body.link
        updates["listing_links"] = links
    db.update_record(record_id, updates)
    mark_changed()
    return _require(record_id)


@app.post("/api/records/{record_id}/assist/{platform}")
async def assist(record_id: int, platform: str) -> dict[str, Any]:
    """Open a browser window on the site's sell page and fill in what we can."""
    if platform not in listings.PLATFORMS:
        raise HTTPException(404, "Unknown site")
    return await publishers.browser_assist(_require(record_id), platform)


@app.post("/api/records/{record_id}/sold")
def mark_sold(record_id: int, body: SoldRequest) -> dict[str, Any]:
    rec = _require(record_id)
    still_up = [p for p in PLATFORMS if p != body.platform and rec.get(f"{p}_status") in ("listed", "draft")]
    updates: dict[str, Any] = {"sold_price": body.price, "sold_platform": body.platform, "sold_at": db.now()}
    if body.platform in PLATFORMS:
        updates[f"{body.platform}_status"] = "sold"
    db.update_record(record_id, updates)
    mark_changed()
    return {
        "record": _require(record_id),
        "take_down": [{"platform": p, "name": listings.PLATFORMS[p]["name"],
                       "link": (rec.get("listing_links") or {}).get(p, "")} for p in still_up],
    }


@app.post("/api/records/{record_id}/unsold")
def mark_unsold(record_id: int) -> dict[str, Any]:
    rec = _require(record_id)
    updates: dict[str, Any] = {"sold_price": None, "sold_platform": "", "sold_at": None}
    if rec.get("sold_platform") in PLATFORMS:
        updates[f"{rec['sold_platform']}_status"] = "ended"
    db.update_record(record_id, updates)
    mark_changed()
    return _require(record_id)


@app.post("/api/records/{record_id}/open-folder")
def open_folder(record_id: int) -> dict[str, Any]:
    """Open the record's photo folder in Windows Explorer so Pete can drag photos into a website."""
    _require(record_id)
    folder = (IMAGES_DIR / f"record_{record_id}").resolve()
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(folder)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
        return {"ok": True, "folder": str(folder)}
    except OSError as exc:
        return {"ok": False, "folder": str(folder), "message": str(exc)}


# --------------------------------------------------------------------------- settings & backup
@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return {"settings": config.all_settings(masked=True), "secret_keys": sorted(config.SECRET_KEYS)}


@app.put("/api/settings")
def put_settings(body: dict[str, str]) -> dict[str, Any]:
    for key, value in body.items():
        if key not in config.DEFAULTS:
            continue
        value = (value or "").strip()
        if key in config.SECRET_KEYS and value.startswith("••••"):
            continue  # unchanged masked value
        db.set_setting(key, value)
    return get_settings()


@app.get("/api/backup")
def backup_status() -> dict[str, Any]:
    return backup.status()


@app.post("/api/backup")
async def backup_now() -> dict[str, Any]:
    global _last_backup
    _last_backup = time.time()
    return await asyncio.to_thread(backup.run_backup, "manual")


@app.post("/api/test-connections")
async def test_connections() -> dict[str, Any]:
    """Make one harmless, free call to each service so Pete/you can see whether the keys work."""
    import httpx
    out: dict[str, Any] = {}
    token = config.get("DISCOGS_API_TOKEN")
    if not token:
        out["discogs"] = {"ok": False, "message": "No Discogs token saved."}
        activity.record("Discogs", "Key test skipped: no token saved", False)
    else:
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get("https://api.discogs.com/oauth/identity", headers=discogs._headers())
            ok = r.status_code == 200
            who = r.json().get("username", "") if ok else r.text[:200]
            out["discogs"] = {"ok": ok, "message": f"Connected as {who}" if ok else f"Discogs said {r.status_code}: {who}"}
            activity.record("Discogs", "Key test (who am I?)", ok, out["discogs"]["message"])
        except httpx.HTTPError as exc:
            out["discogs"] = {"ok": False, "message": f"Couldn't reach Discogs: {exc}"}
            activity.record("Discogs", "Key test", False, str(exc))
    key = config.get("OPENROUTER_API_KEY")
    if not key:
        out["openrouter"] = {"ok": False, "message": "No OpenRouter key saved."}
        activity.record("OpenRouter", "Key test skipped: no key saved", False)
    else:
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get("https://openrouter.ai/api/v1/auth/key", headers={"Authorization": f"Bearer {key}"})
            ok = r.status_code == 200
            d = r.json().get("data", {}) if ok else {}
            left = d.get("limit_remaining")
            msg = ("Key works." + (f" Credit left: ${left:.2f}" if isinstance(left, (int, float)) else
                   f" Used so far: ${d.get('usage', 0):.2f}")) if ok else f"OpenRouter said {r.status_code}: {r.text[:200]}"
            out["openrouter"] = {"ok": ok, "message": msg}
            activity.record("OpenRouter", "Key test", ok, msg)
        except httpx.HTTPError as exc:
            out["openrouter"] = {"ok": False, "message": f"Couldn't reach OpenRouter: {exc}"}
            activity.record("OpenRouter", "Key test", False, str(exc))
    return out


@app.post("/api/quit")
async def quit_app() -> dict[str, Any]:
    """The big Stop button: back up, then shut the whole app down."""
    message = ""
    if backup.backup_folder() is not None:
        result = await asyncio.to_thread(backup.run_backup, "on closing")
        message = result["message"]
    await publishers.shutdown_browser()

    def _exit() -> None:
        db.close()
        (config.LOGS_DIR / "server.pid").unlink(missing_ok=True)
        if sys.platform == "win32":
            # Close the app window too: Edge was started with a private "edge_profile" folder, so this
            # only ever matches Pete's Vinyl's own window, never his normal browser.
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
                     "Where-Object { $_.CommandLine -like '*edge_profile*' } | "
                     "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
                    creationflags=0x08000000, timeout=15)  # 0x08000000 = no console window
            except (OSError, subprocess.SubprocessError):
                pass
        os._exit(0)

    threading.Timer(1.5, _exit).start()  # let the reply and the "closed" page reach the browser first
    return {"ok": True, "message": message}


@app.get("/api/records/{record_id}/price-links")
def price_links(record_id: int) -> dict[str, Any]:
    """Links Pete (or you) can open to check real sold prices by eye."""
    from urllib.parse import quote_plus
    rec = _require(record_id)
    q = quote_plus(f"{rec.get('artist') or ''} {rec.get('album_title') or ''} vinyl".strip())
    links = {
        "ebay": f"https://www.ebay.com/sch/i.html?_nkw={q}&_sacat=176985&LH_Sold=1&LH_Complete=1",
        "popsike": popsike.search_url(rec),
    }
    if rec.get("discogs_release_id"):
        links["discogs"] = f"https://www.discogs.com/release/{rec['discogs_release_id']}"
    return links


@app.get("/api/popsike/status")
def popsike_status() -> dict[str, Any]:
    return {"enabled": popsike.enabled(), "connected": popsike.is_connected(), "edge_found": popsike.find_edge() is not None}


@app.post("/api/popsike/connect")
def popsike_connect() -> dict[str, Any]:
    return popsike.open_login()


@app.post("/api/popsike/done")
def popsike_done() -> dict[str, Any]:
    return popsike.finish_login()


@app.post("/api/popsike/test")
async def popsike_test() -> dict[str, Any]:
    """Look up a well-known record so it's easy to see whether Popsike is being read properly."""
    res = await popsike.lookup({"artist": "Bob Marley", "album_title": "Exodus"})
    ok = bool(res.get("median"))
    home = config.get("HOME_CURRENCY")
    msg = (f"Working: found {res['count']} sales, middle price {home} {res['median']:.0f}." if ok
           else f"Couldn't read any prices. {res.get('note') or 'See the log page for details.'}")
    return {"ok": ok, "message": msg}


@app.get("/api/activity")
def activity_log() -> dict[str, Any]:
    return {"events": activity.recent()}


@app.get("/api/backup-log")
def backup_log() -> dict[str, Any]:
    entries = db.backup_history(100)
    return {"entries": entries, "last_ok": next((e for e in entries if e["ok"]), None), "status": backup.status()}


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    return db.stats()


# --------------------------------------------------------------------------- static files
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
