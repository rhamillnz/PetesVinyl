"""SQLite storage for the record collection."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from .config import DB_PATH

PLATFORMS = ["trademe", "discogs", "ebay", "facebook", "gumtree"]
IMAGE_SLOTS = {
    "front": "front_cover_path",
    "back": "back_cover_path",
    "disc_a": "disc_a_path",
    "disc_b": "disc_b_path",
}

# (column, SQL type/default). New columns added here are auto-migrated on start-up.
COLUMNS: list[tuple[str, str]] = [
    ("artist", "TEXT DEFAULT ''"),
    ("album_title", "TEXT DEFAULT ''"),
    ("year_pressed", "TEXT DEFAULT ''"),
    ("original_year", "TEXT DEFAULT ''"),
    ("pressing_location", "TEXT DEFAULT ''"),
    ("label", "TEXT DEFAULT ''"),
    ("catalog_number", "TEXT DEFAULT ''"),
    ("barcode", "TEXT DEFAULT ''"),
    ("matrix_numbers", "TEXT DEFAULT ''"),
    ("is_first_owner", "BOOLEAN DEFAULT 1"),
    ("number_of_owners", "INTEGER DEFAULT 1"),
    ("condition_media", "TEXT DEFAULT 'VG+'"),
    ("condition_sleeve", "TEXT DEFAULT 'VG+'"),
    ("disc_count", "INTEGER DEFAULT 1"),
    ("media_scratches", "TEXT DEFAULT ''"),
    ("media_play", "TEXT DEFAULT ''"),
    ("cover_creases", "TEXT DEFAULT ''"),
    ("cover_issues", "TEXT DEFAULT '[]'"),
    ("extra_images", "TEXT DEFAULT '[]'"),
    ("notes", "TEXT DEFAULT ''"),
    ("ai_summary", "TEXT DEFAULT ''"),
    ("discogs_release_id", "TEXT DEFAULT ''"),
    ("discogs_url", "TEXT DEFAULT ''"),
    ("discogs_median", "REAL"),
    ("ebay_sold_average", "REAL"),
    ("popsike_median", "REAL"),
    ("ai_estimate", "REAL"),
    ("estimated_value", "REAL"),
    ("suggested_price", "REAL"),
    ("valuation_notes", "TEXT DEFAULT ''"),
    ("valued_at", "TEXT"),
    ("recommended_platforms", "TEXT DEFAULT '[]'"),
    ("front_cover_path", "TEXT DEFAULT ''"),
    ("back_cover_path", "TEXT DEFAULT ''"),
    ("disc_a_path", "TEXT DEFAULT ''"),
    ("disc_b_path", "TEXT DEFAULT ''"),
    ("trademe_status", "TEXT DEFAULT 'not_listed'"),
    ("discogs_status", "TEXT DEFAULT 'not_listed'"),
    ("ebay_status", "TEXT DEFAULT 'not_listed'"),
    ("facebook_status", "TEXT DEFAULT 'not_listed'"),
    ("gumtree_status", "TEXT DEFAULT 'not_listed'"),
    ("listing_links", "TEXT DEFAULT '{}'"),
    ("sold_price", "REAL"),
    ("sold_platform", "TEXT DEFAULT ''"),
    ("sold_at", "TEXT"),
    ("created_at", "TEXT"),
    ("updated_at", "TEXT"),
]
COLUMN_NAMES = {name for name, _ in COLUMNS}
JSON_COLUMNS = {"recommended_platforms", "listing_links", "cover_issues", "extra_images"}

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            init(_conn)
        return _conn


def init(conn: sqlite3.Connection) -> None:
    cols = ",\n".join(f"{name} {kind}" for name, kind in COLUMNS)
    conn.execute(f"CREATE TABLE IF NOT EXISTS records (id INTEGER PRIMARY KEY AUTOINCREMENT,\n{cols})")
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(records)")}
    for name, kind in COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE records ADD COLUMN {name} {kind}")
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("""CREATE TABLE IF NOT EXISTS backup_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, ok INTEGER, kind TEXT, message TEXT,
        folder TEXT, records INTEGER, photos INTEGER)""")
    conn.commit()


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    rec = dict(row)
    for col in JSON_COLUMNS:
        try:
            rec[col] = json.loads(rec.get(col) or ("{}" if col == "listing_links" else "[]"))
        except (TypeError, ValueError):
            rec[col] = {} if col == "listing_links" else []
    rec["is_first_owner"] = bool(rec.get("is_first_owner"))
    rec["state"] = record_state(rec)
    rec["images"] = {slot: _image_url(rec.get(col)) for slot, col in IMAGE_SLOTS.items()}
    rec["extras"] = [{"key": e.get("key"), "label": e.get("label") or "Extra photo", "url": _image_url(e.get("path"))}
                     for e in rec.get("extra_images") or [] if e.get("path")]
    rec["disc_count"] = rec.get("disc_count") or 1
    return rec


def _image_url(path: str | None) -> str:
    return f"/images/{path}" if path else ""


def record_state(rec: dict[str, Any]) -> str:
    if rec.get("sold_at"):
        return "sold"
    if any(rec.get(f"{p}_status") == "listed" for p in PLATFORMS):
        return "for_sale"
    if any(rec.get(f"{p}_status") in ("ready", "draft") for p in PLATFORMS):
        return "ready"
    return "collection"


def create_record(fields: dict[str, Any]) -> int:
    fields = _clean(fields)
    fields["created_at"] = fields["updated_at"] = now()
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    with _lock:
        conn = connect()
        cur = conn.execute(f"INSERT INTO records ({cols}) VALUES ({marks})", list(fields.values()))
        conn.commit()
        return int(cur.lastrowid)


def update_record(record_id: int, fields: dict[str, Any]) -> None:
    fields = _clean(fields)
    if not fields:
        return
    fields["updated_at"] = now()
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _lock:
        conn = connect()
        conn.execute(f"UPDATE records SET {sets} WHERE id = ?", [*fields.values(), record_id])
        conn.commit()


def _clean(fields: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for key, value in fields.items():
        if key not in COLUMN_NAMES:
            continue
        if key in JSON_COLUMNS and not isinstance(value, str):
            value = json.dumps(value)
        if key == "is_first_owner":
            value = 1 if value else 0
        out[key] = value
    return out


def get_record(record_id: int) -> dict[str, Any] | None:
    with _lock:
        row = connect().execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_records(search: str = "", state: str = "") -> list[dict[str, Any]]:
    sql = "SELECT * FROM records"
    params: list[Any] = []
    if search:
        like = f"%{search}%"
        sql += " WHERE artist LIKE ? OR album_title LIKE ? OR label LIKE ? OR catalog_number LIKE ?"
        params = [like, like, like, like]
    sql += " ORDER BY COALESCE(updated_at, created_at) DESC"
    with _lock:
        rows = connect().execute(sql, params).fetchall()
    records = [_row_to_dict(r) for r in rows]
    if state:
        records = [r for r in records if r["state"] == state]
    return records


def delete_record(record_id: int) -> None:
    with _lock:
        conn = connect()
        conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
        conn.commit()


def stats() -> dict[str, Any]:
    records = list_records()
    unsold = [r for r in records if r["state"] != "sold"]
    return {
        "total": len(records),
        "collection": sum(1 for r in records if r["state"] in ("collection", "ready")),
        "for_sale": sum(1 for r in records if r["state"] == "for_sale"),
        "sold": sum(1 for r in records if r["state"] == "sold"),
        "collection_value": round(sum(r["suggested_price"] or 0 for r in unsold), 2),
        "sold_total": round(sum(r["sold_price"] or 0 for r in records if r["state"] == "sold"), 2),
    }


def get_setting(key: str) -> str | None:
    with _lock:
        row = connect().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with _lock:
        conn = connect()
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()


def add_backup_log(ok: bool, kind: str, message: str, folder: str = "", records: int = 0, photos: int = 0) -> None:
    with _lock:
        conn = connect()
        conn.execute("INSERT INTO backup_log (at, ok, kind, message, folder, records, photos) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (now(), 1 if ok else 0, kind, message, folder, records, photos))
        conn.execute("DELETE FROM backup_log WHERE id NOT IN (SELECT id FROM backup_log ORDER BY id DESC LIMIT 500)")
        conn.commit()


def backup_history(limit: int = 100) -> list[dict[str, Any]]:
    with _lock:
        rows = connect().execute("SELECT * FROM backup_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{**dict(r), "ok": bool(r["ok"])} for r in rows]
