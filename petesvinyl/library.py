"""Pete's library (records, photos, settings and keys): keeping it safe, finding old copies, and loading one.

The library lives in config.DATA_DIR (on Windows: %LOCALAPPDATA%\\PetesVinyl), outside the program folder, so
updates and reinstalls never touch it. This module also:
  * moves a library from where older versions kept it (inside the program folder) on first start,
  * makes automatic safety copies (before an update, before loading another library, and once a day),
  * searches the PC for other libraries (old program folders, Google Drive backups, safety copies),
  * loads one of them, after taking a safety copy of the current library.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config

log = logging.getLogger("petesvinyl.library")
DB_NAME = "vinyl_collection.db"
KEEP_SAFETY_COPIES = 30
SKIP_DIRS = {"appdata", "windows", "program files", "program files (x86)", "programdata", "$recycle.bin",
             "venv", ".git", "node_modules", "__pycache__", "app_profile", "edge_profile", "browser_profile",
             "popsike_profile", "images", "system volume information"}


# --------------------------------------------------------------------------- reading a library safely
def _copy_db(src: Path, dest: Path) -> None:
    """Copy a SQLite library properly, including changes still waiting in a -wal file next to it."""
    with tempfile.TemporaryDirectory() as tmp:
        # work on a private copy so the original (and its -wal/-shm files) is never modified
        staged = Path(tmp) / DB_NAME
        shutil.copy2(src, staged)
        for suffix in ("-wal", "-shm"):
            side = Path(str(src) + suffix)
            if side.exists():
                shutil.copy2(side, Path(str(staged) + suffix))
        source = sqlite3.connect(staged)
        target = sqlite3.connect(dest)
        try:
            with target:
                source.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")
        finally:
            source.close()
            target.close()


def describe(db_file: Path) -> dict[str, Any] | None:
    """How many records a library holds, and when it last changed. None if it isn't a readable library."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / DB_NAME
            _copy_db(db_file, copy)
            conn = sqlite3.connect(copy)
            try:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "records" not in tables:
                    return None
                records = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
                names = [r[0] for r in conn.execute(
                    "SELECT COALESCE(NULLIF(artist,''),'?') || ' - ' || COALESCE(NULLIF(album_title,''),'?') "
                    "FROM records ORDER BY COALESCE(updated_at, created_at) DESC LIMIT 3")]
                has_keys = False
                if "settings" in tables:
                    has_keys = bool(conn.execute("SELECT COUNT(*) FROM settings WHERE key IN "
                                                 "('OPENROUTER_API_KEY','DISCOGS_API_TOKEN') AND value != ''").fetchone()[0])
            finally:
                conn.close()
        stamp = max(p.stat().st_mtime for p in [db_file, Path(str(db_file) + "-wal")] if p.exists())
        images = db_file.parent / "images"
        photos = sum(1 for p in images.rglob("*.jpg")) if images.is_dir() else 0
        return {"path": str(db_file), "folder": str(db_file.parent), "records": records, "examples": names,
                "has_keys": has_keys, "photos": photos,
                "modified": datetime.fromtimestamp(stamp).isoformat(timespec="minutes")}
    except (OSError, sqlite3.Error) as exc:
        log.info("Not a readable library: %s (%s)", db_file, exc)
        return None


def current_summary() -> dict[str, Any]:
    info = describe(config.DB_PATH) if config.DB_PATH.exists() else None
    return {"folder": str(config.DATA_DIR), "records": info["records"] if info else 0}


# --------------------------------------------------------------------------- safety copies
def safety_copy(reason: str, min_hours: float = 0) -> Path | None:
    """Copy the current library into DATA_DIR/safety copies. Photos aren't duplicated (they're never deleted by
    loading or updating, only added to). Keeps the most recent KEEP_SAFETY_COPIES."""
    if not config.DB_PATH.exists():
        return None
    config.SAFETY_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(config.SAFETY_DIR.glob("*.db"), key=lambda p: p.stat().st_mtime)
    if min_hours and existing and time.time() - existing[-1].stat().st_mtime < min_hours * 3600:
        return None
    dest = config.SAFETY_DIR / f"{datetime.now():%Y-%m-%d %H%M%S} {reason}.db"
    try:
        _copy_db(config.DB_PATH, dest)
    except (OSError, sqlite3.Error) as exc:
        log.warning("Safety copy failed: %s", exc)
        return None
    for old in sorted(config.SAFETY_DIR.glob("*.db"), key=lambda p: p.stat().st_mtime)[:-KEEP_SAFETY_COPIES]:
        old.unlink(missing_ok=True)
    return dest


# --------------------------------------------------------------------------- moving from the old place
def migrate_legacy() -> bool:
    """Older versions kept the library inside the program folder. Copy it to the fixed data folder once.
    The old files are left where they are (nothing is ever deleted)."""
    if "PETESVINYL_DB" in os.environ or config.DB_PATH.exists():
        return False
    legacy = config.LEGACY_DIR / DB_NAME
    if not legacy.exists() or legacy.resolve() == config.DB_PATH.resolve():
        return False
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _copy_db(legacy, config.DB_PATH)
    _merge_images(config.LEGACY_DIR / "images")
    try:
        (config.LEGACY_DIR / "LIBRARY MOVED - READ ME.txt").write_text(
            "Pete's Vinyl now keeps the records, photos and settings in:\n"
            f"  {config.DATA_DIR}\n"
            "so updates and reinstalls can't lose them. The files here are an old copy and can stay.\n",
            encoding="utf-8")
    except OSError:
        pass
    log.info("Moved the library from %s to %s", legacy, config.DB_PATH)
    return True


def _merge_images(src: Path) -> int:
    """Copy photos into the library's images folder. Existing photos are never overwritten or deleted."""
    if not src.is_dir() or src.resolve() == config.IMAGES_DIR.resolve():
        return 0
    copied = 0
    for f in src.rglob("*"):
        if not f.is_file():
            continue
        dest = config.IMAGES_DIR / f.relative_to(src)
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
        copied += 1
    return copied


# --------------------------------------------------------------------------- finding libraries on this PC
def _search_roots() -> list[Path]:
    env = os.environ.get("PETESVINYL_SEARCH_ROOTS")
    if env:
        return [Path(p) for p in env.split(os.pathsep) if p]
    home = Path.home()
    roots = [config.LEGACY_DIR, config.SAFETY_DIR, home / "Downloads", home / "Desktop", home / "Documents",
             home / "OneDrive", home]
    try:
        from . import backup
        drive = backup.backup_folder()
        if drive:
            roots.insert(1, drive)
    except Exception:  # noqa: BLE001
        pass
    if os.name == "nt":
        roots += [Path(f"{d}:\\") for d in "CDEFG" if Path(f"{d}:\\").exists()]
    return roots


def find_libraries(time_limit: float = 20.0) -> list[dict[str, Any]]:
    """Look for libraries (vinyl_collection.db, and the safety copies) on this PC. Newest first."""
    started = time.time()
    seen: set[str] = set()
    found: list[Path] = []
    current = config.DB_PATH.resolve() if config.DB_PATH.exists() else None
    for root in _search_roots():
        if not root.exists():
            continue
        depth0 = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            if time.time() - started > time_limit:
                break
            here = Path(dirpath)
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")
                           and len(here.parts) - depth0 < 5]
            for name in filenames:
                if name == DB_NAME or (here == config.SAFETY_DIR and name.endswith(".db")):
                    p = (here / name).resolve()
                    if str(p).lower() not in seen and p != current:
                        seen.add(str(p).lower())
                        found.append(p)
    results = []
    for p in found:
        info = describe(p)
        if info and info["records"] > 0:            # an empty library is no use to anyone
            info["kind"] = ("safety copy" if config.SAFETY_DIR in p.parents else
                            "Google Drive backup" if "drive" in str(p).lower() else "old app folder")
            results.append(info)
    results.sort(key=lambda r: r["modified"], reverse=True)
    return results


# --------------------------------------------------------------------------- loading a library
def import_library(db_file: str) -> dict[str, Any]:
    """Make the given library the current one. The current library is safety-copied first; photos are added
    (nothing is deleted), so this can always be undone by loading the safety copy."""
    from . import db
    src = Path(db_file)
    info = describe(src) if src.exists() else None
    if not info:
        return {"ok": False, "message": "That file isn't a Pete's Vinyl library I can read."}
    before = safety_copy("before loading another library")
    db.close()
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        staged = config.DATA_DIR / (DB_NAME + ".loading")
        _copy_db(src, staged)
        for suffix in ("-wal", "-shm"):
            Path(str(config.DB_PATH) + suffix).unlink(missing_ok=True)
        os.replace(staged, config.DB_PATH)
        photos = _merge_images(src.parent / "images")
    finally:
        db.connect()
    msg = f"Loaded {info['records']} record{'s' if info['records'] != 1 else ''} from {info['folder']}"
    if photos:
        msg += f" and copied {photos} photo{'s' if photos != 1 else ''}"
    if before:
        msg += ". Your previous library was saved as a safety copy"
    return {"ok": True, "message": msg + ".", "records": info["records"]}
