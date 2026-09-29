"""Back up the collection into the Google Drive for Desktop folder.

Google Drive for Desktop shows up on Windows as a drive (usually G:) containing "My Drive".
Anything we copy there is uploaded to Pete's Google account automatically. We copy:
  * vinyl_collection.db (safe live copy using SQLite's backup API)
  * a dated copy of the database in history/ (last 30 kept) in case of accidental changes
  * every photo (only new/changed ones, so it's quick)
  * collection.csv, which opens in Google Sheets / Excel as a readable list
"""
from __future__ import annotations

import csv
import logging
import os
import shutil
import sqlite3
import string
from datetime import datetime
from pathlib import Path
from typing import Any

from . import activity, config, db
from .config import DB_PATH, IMAGES_DIR

log = logging.getLogger("petesvinyl.backup")
FOLDER_NAME = "PetesVinyl Backup"
CSV_COLUMNS = ["id", "artist", "album_title", "year_pressed", "pressing_location", "label", "catalog_number",
               "condition_media", "condition_sleeve", "number_of_owners", "estimated_value", "suggested_price",
               "state", "sold_price", "sold_platform", "sold_at"]


def find_google_drive() -> Path | None:
    candidates: list[Path] = []
    if os.name == "nt":
        for letter in string.ascii_uppercase[3:]:  # D: onwards
            candidates += [Path(f"{letter}:/My Drive"), Path(f"{letter}:/Google Drive/My Drive")]
    home = Path.home()
    candidates += [home / "Google Drive" / "My Drive", home / "Google Drive", home / "My Drive"]
    for c in candidates:
        try:
            if c.is_dir():
                return c
        except OSError:
            continue
    return None


def backup_folder() -> Path | None:
    configured = config.get("BACKUP_FOLDER")
    if configured:
        return Path(configured)
    drive = find_google_drive()
    return drive / FOLDER_NAME if drive else None


def status() -> dict[str, Any]:
    folder = backup_folder()
    return {
        "folder": str(folder) if folder else "",
        "google_drive_found": find_google_drive() is not None,
        "last_backup": db.get_setting("LAST_BACKUP") or "",
        "last_result": db.get_setting("LAST_BACKUP_RESULT") or "",
    }


def _finish(ok: bool, kind: str, msg: str, folder: str = "", records: int = 0, photos: int = 0) -> dict[str, Any]:
    """Record this attempt permanently (Backups section of the log page) and in the activity log."""
    db.set_setting("LAST_BACKUP_RESULT", msg)
    if ok:
        db.set_setting("LAST_BACKUP", datetime.now().strftime("%d %b %Y, %I:%M %p"))
    db.add_backup_log(ok, kind, msg, folder, records, photos)
    activity.record("Backup", f"{kind.capitalize()} backup", ok, msg)
    return {"ok": ok, "message": msg, "folder": folder, "records": records, "photos": photos,
            "when": datetime.now().strftime("%d %b %Y, %I:%M %p")}


def run_backup(kind: str = "manual") -> dict[str, Any]:
    """kind is 'manual' (Back Up button), 'automatic' (scheduled) or 'on closing' (Stop button)."""
    folder = backup_folder()
    if folder is None:
        return _finish(False, kind, "Google Drive wasn't found on this computer, so nothing was backed up. "
                       "Install 'Google Drive for Desktop', sign in, then press Back Up again.")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "history").mkdir(exist_ok=True)
        target = folder / "vinyl_collection.db"
        tmp = folder / "vinyl_collection.db.tmp"
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(tmp)
        with dst:
            src.backup(dst)
        n_source = src.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        src.close()
        dst.close()
        os.replace(tmp, target)

        # Check the copy really is a good one before calling it a success.
        check = sqlite3.connect(target)
        try:
            n_copy = check.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            healthy = check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            check.close()
        if not healthy or n_copy != n_source:
            return _finish(False, kind, f"The backup copy failed its check ({n_copy} of {n_source} records, "
                           f"integrity {'ok' if healthy else 'BAD'}). Try again.", str(folder), n_copy)

        stamp = datetime.now().strftime("%Y-%m-%d")
        shutil.copy2(target, folder / "history" / f"vinyl_collection_{stamp}.db")
        history = sorted((folder / "history").glob("vinyl_collection_*.db"))
        for old in history[:-30]:
            old.unlink(missing_ok=True)

        copied = 0
        if IMAGES_DIR.exists():
            for src_img in IMAGES_DIR.rglob("*"):
                if not src_img.is_file():
                    continue
                dest = folder / "images" / src_img.relative_to(IMAGES_DIR)
                if dest.exists() and dest.stat().st_size == src_img.stat().st_size:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_img, dest)
                copied += 1

        with open(folder / "collection.csv", "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for rec in db.list_records():
                writer.writerow(rec)

        msg = (f"Backed up {n_source} record{'s' if n_source != 1 else ''} and {copied} new photo"
               f"{'s' if copied != 1 else ''} to {folder}. Copy checked: all {n_copy} records present.")
        return _finish(True, kind, msg, str(folder), n_source, copied)
    except (OSError, sqlite3.Error) as exc:
        log.exception("Backup failed")
        return _finish(False, kind, f"The backup didn't work: {exc}", str(folder))
