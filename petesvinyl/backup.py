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

from . import config, db
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


def run_backup() -> dict[str, Any]:
    folder = backup_folder()
    if folder is None:
        msg = ("Google Drive isn't set up on this computer yet. Install 'Google Drive for Desktop', "
               "sign in, then press Back Up again.")
        db.set_setting("LAST_BACKUP_RESULT", msg)
        return {"ok": False, "message": msg}
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "history").mkdir(exist_ok=True)
        target = folder / "vinyl_collection.db"
        tmp = folder / "vinyl_collection.db.tmp"
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(tmp)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        os.replace(tmp, target)
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

        when = datetime.now().strftime("%d %b %Y, %I:%M %p")
        msg = f"Backed up to Google Drive ({copied} new photos)."
        db.set_setting("LAST_BACKUP", when)
        db.set_setting("LAST_BACKUP_RESULT", msg)
        return {"ok": True, "message": msg, "folder": str(folder), "when": when}
    except OSError as exc:
        log.exception("Backup failed")
        msg = f"Backup didn't work: {exc}"
        db.set_setting("LAST_BACKUP_RESULT", msg)
        return {"ok": False, "message": msg}
