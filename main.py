"""PetesVinyl - FastAPI backend.

Run with:  uvicorn main:app --port 8000   (or double-click Start_PetesVinyl.bat on Windows)
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from petesvinyl import activity, ai, backup, config, db, discogs, listings, publishers, valuation
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
            result = await asyncio.to_thread(backup.run_backup)
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
    notes: Optional[str] = None
    discogs_release_id: Optional[str] = None
    suggested_price: Optional[float] = None


class RecordIn(RecordFields):
    # Base64 JPEG frames (data URLs are fine) keyed front / back / disc_a / disc_b.
    images: dict[str, str] = Field(default_factory=dict)


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


def _save_images(record_id: int, images: dict[str, str]) -> dict[str, str]:
    """Decode base64 frames and write them to images/record_<id>/<slot>_<time>.jpg."""
    folder = IMAGES_DIR / f"record_{record_id}"
    folder.mkdir(parents=True, exist_ok=True)
    existing = db.get_record(record_id) or {}
    saved: dict[str, str] = {}
    for slot, data in images.items():
        if slot not in IMAGE_SLOTS or not data:
            continue
        if "," in data[:100]:
            data = data.split(",", 1)[1]
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(400, f"Photo '{slot}' isn't valid base64") from exc
        rel = f"record_{record_id}/{slot}_{int(time.time() * 1000)}.jpg"
        (IMAGES_DIR / rel).write_bytes(raw)
        old = existing.get(IMAGE_SLOTS[slot])
        if old and old != rel:
            (IMAGES_DIR / old).unlink(missing_ok=True)
        saved[IMAGE_SLOTS[slot]] = rel
    return saved


def _image_files(rec: dict[str, Any]) -> dict[str, Path]:
    return {slot: IMAGES_DIR / rec[col] for slot, col in IMAGE_SLOTS.items() if rec.get(col)}


# --------------------------------------------------------------------------- records
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
    fields = body.model_dump(exclude={"images"}, exclude_none=True)
    fields.setdefault("is_first_owner", True)
    fields.setdefault("number_of_owners", 1)
    record_id = db.create_record(fields)
    if body.images:
        db.update_record(record_id, _save_images(record_id, body.images))
    mark_changed()
    return _require(record_id)


@app.put("/api/records/{record_id}")
def update_record(record_id: int, body: RecordIn) -> dict[str, Any]:
    _require(record_id)
    fields = body.model_dump(exclude={"images"}, exclude_none=True)
    if fields.get("is_first_owner") and "number_of_owners" not in fields:
        fields["number_of_owners"] = 1
    if body.images:
        fields.update(_save_images(record_id, body.images))
    db.update_record(record_id, fields)
    mark_changed()
    return _require(record_id)


@app.delete("/api/records/{record_id}")
def delete_record(record_id: int) -> dict[str, Any]:
    rec = _require(record_id)
    for path in _image_files(rec).values():
        path.unlink(missing_ok=True)
    db.delete_record(record_id)
    mark_changed()
    return {"ok": True}


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
    return await asyncio.to_thread(backup.run_backup)


@app.get("/api/activity")
def activity_log() -> dict[str, Any]:
    return {"events": activity.recent()}


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
