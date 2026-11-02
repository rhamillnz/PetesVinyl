"""Wrap up records for Cordy's (John Cordy Ltd, Auckland), so Pete can hand over photos and descriptions in one go.

We don't yet know how Cordy's want to receive the files, so there are three styles to choose from. The wording follows
their past record sales (six between Sept 2022 and Sept 2025): lot titles like ATOMIC ROOSTER 'HOME TO ROOST' CRD2, and
lot details of format, released, label, catalogue number, Discogs release ID, artist and title.

Cordy's choose their own lot numbers, so each record is identified by a reference that never changes (PV0012).
"""
from __future__ import annotations

import csv
import html
import io
import logging
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from . import browser, config, db, listings
from .config import IMAGES_DIR

log = logging.getLogger("petesvinyl.cordys")

EXPORT_DIR = config.DATA_DIR / "Cordys exports"
STYLES = {"sheet": "Spreadsheet and photos", "folders": "One folder per record", "pdf": "PDF catalogue"}
EMAIL_LIMIT = 20 * 1024 * 1024   # most email services refuse attachments much bigger than this
SMALL_PHOTO = (1600, 82)         # longest side in pixels, JPEG quality: sharp on screen, a few hundred KB each
PDF_PHOTO = (1000, 72)
SLOT_NAMES = {"front": "Front cover", "back": "Back cover", "disc_a": "Side A label", "disc_b": "Side B label"}


class CordysError(Exception):
    """Something Pete should be told about, in plain words."""


# --------------------------------------------------------------------------- wording
def ref(rec: dict[str, Any]) -> str:
    return f"PV{int(rec['id']):04d}"


def format_name(rec: dict[str, Any]) -> str:
    n = int(rec.get("disc_count") or 1)
    return "LP" if n == 1 else f"{n}xLP"


def lot_title(rec: dict[str, Any]) -> str:
    """Their newest style: THE BAND 'ROCK OF AGES' 2 LP MFSL 2-348."""
    artist = (rec.get("artist") or "Unknown artist").upper()
    title = (rec.get("album_title") or "Untitled").upper()
    discs = int(rec.get("disc_count") or 1)
    bits = [f"{artist} '{title}'", f"{discs} LP" if discs > 1 else "", rec.get("catalog_number") or ""]
    return " ".join(b for b in bits if b)


def owner_line(rec: dict[str, Any]) -> str:
    owners = rec.get("number_of_owners") or 1
    return "One owner from new." if rec.get("is_first_owner") or owners == 1 else f"This copy has had {owners} owners."


def description(rec: dict[str, Any]) -> str:
    """The listing wording without the parts meant for private sales (postage, thanks for looking, and so on)."""
    lines = [f"{rec.get('artist') or 'Unknown artist'} - {rec.get('album_title') or 'Untitled'}",
             f"Format: {format_name(rec)}"]
    lines += [f"{label}: {value}" for label, value in listings.detail_pairs(rec) if value]
    if rec.get("discogs_release_id"):
        lines.append(f"Discogs release: {rec['discogs_release_id']}")
    lines += ["", *listings.condition_lines(rec), owner_line(rec)]
    if rec.get("notes"):
        lines += ["", str(rec["notes"])]
    return "\n".join(lines)


def condition_notes(rec: dict[str, Any]) -> str:
    return " ".join(line.strip() for line in listings.condition_lines(rec) if line.startswith("  "))


# --------------------------------------------------------------------------- photos
def photo_list(rec: dict[str, Any]) -> list[tuple[str, Path]]:
    """Every photo of a record that's really on disk, as (name, file): the four standard ones, then the extras."""
    found = [(SLOT_NAMES[slot], rec.get(col)) for slot, col in db.IMAGE_SLOTS.items()]
    found += [(e.get("label") or "Extra photo", e.get("path")) for e in rec.get("extra_images") or []]
    return [(label, IMAGES_DIR / rel) for label, rel in found if rel and (IMAGES_DIR / rel).is_file()]


def safe_name(text: str, limit: int = 70) -> str:
    """Make text safe for a Windows file name (AC/DC can't be a folder name as it stands)."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", text)
    return re.sub(r"\s+", " ", cleaned)[:limit].strip(" .-") or "Untitled"


def shrink(src: Path, dest: Path, size: tuple[int, int]) -> None:
    """Write a smaller copy of a photo, the right way up. If it can't be read, send the original as it is."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    longest, quality = size
    try:
        with Image.open(src) as img:
            out = ImageOps.exif_transpose(img).convert("RGB")
            out.thumbnail((longest, longest), Image.Resampling.LANCZOS)
            out.save(dest, "JPEG", quality=quality, optimize=True)
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        log.warning("Couldn't shrink %s, using the original: %s", src, exc)
        shutil.copyfile(src, dest)


# --------------------------------------------------------------------------- the three styles
def _spreadsheet_cell(value: Any) -> Any:
    """Excel treats a cell starting with = + - @ as a formula, which would mangle an album called "=" or "+"."""
    return f"'{value}" if isinstance(value, str) and value[:1] in ("=", "+", "-", "@") else value


def spreadsheet(recs: list[dict[str, Any]], files: dict[int, list[str]], prices: bool) -> bytes:
    head = ["Reference", "Lot title", "Format", "Released", "Label", "Catalog #", "Release ID", "Artist", "Title",
            "Pressed in", "Record condition", "Cover condition", "Condition notes", "Owners", "Description",
            "Discogs link", "Photos", "Photo files"]
    if prices:
        head.append(f"Seller's price guide ({config.get('HOME_CURRENCY')})")
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(head)
    for rec in recs:
        release = rec.get("discogs_release_id") or ""
        row = [ref(rec), lot_title(rec), format_name(rec), rec.get("year_pressed") or rec.get("original_year") or "",
               rec.get("label") or "", rec.get("catalog_number") or "", release, rec.get("artist") or "",
               rec.get("album_title") or "", rec.get("pressing_location") or "", rec.get("condition_media") or "",
               rec.get("condition_sleeve") or "", condition_notes(rec), owner_line(rec), description(rec),
               f"https://www.discogs.com/release/{release}" if release else "", len(files[rec["id"]]),
               "; ".join(files[rec["id"]])]
        if prices:
            row.append(rec.get("suggested_price") or "")
        writer.writerow([_spreadsheet_cell(v) for v in row])
    return out.getvalue().encode("utf-8-sig")    # the marker makes Excel read accented names correctly


def read_me(style: str, count: int) -> str:
    how = {
        "sheet": "\"Cordys catalogue.csv\" opens in Excel, with one row per record. The photos are in the \"photos\" "
                 "folder, and each file name starts with the record's reference.",
        "folders": "There is one folder per record, holding its photos and a description.txt to copy from.",
    }[style]
    return (f"{count} records from {config.get('SELLER_NAME')}, {config.get('SELLER_LOCATION')}.\n\n{how}\n\n"
            "Each record has a reference like PV0012 that stays the same, so it can be matched to your lot number.\n")


def _photo_writer(tmp: Path, small: bool) -> Callable[[Path], Path]:
    if not small:
        return lambda src: src
    made = iter(range(1, 10 ** 9))

    def smaller(src: Path) -> Path:
        dest = tmp / f"{next(made)}.jpg"
        shrink(src, dest, SMALL_PHOTO)
        return dest
    return smaller


def write_sheet_zip(recs: list[dict[str, Any]], path: Path, small: bool, prices: bool) -> int:
    photos = 0
    files: dict[int, list[str]] = {}
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        prepare = _photo_writer(Path(tmp), small)
        for rec in recs:
            files[rec["id"]] = []
            for n, (label, src) in enumerate(photo_list(rec), 1):
                name = f"{ref(rec)}-{n} {safe_name(label, 40)}.jpg"
                done = prepare(src)
                z.write(done, f"photos/{name}")
                if small:
                    done.unlink()
                files[rec["id"]].append(name)
                photos += 1
        z.writestr("Cordys catalogue.csv", spreadsheet(recs, files, prices), zipfile.ZIP_DEFLATED)
        z.writestr("READ ME.txt", read_me("sheet", len(recs)), zipfile.ZIP_DEFLATED)
    return photos


def write_folders_zip(recs: list[dict[str, Any]], path: Path, small: bool, prices: bool) -> int:
    photos = 0
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        prepare = _photo_writer(Path(tmp), small)
        for rec in recs:
            folder = f"{ref(rec)} {safe_name((rec.get('artist') or 'Unknown artist') + ' - ' + (rec.get('album_title') or 'Untitled'))}"
            text = f"{ref(rec)}\n{lot_title(rec)}\n\n{description(rec)}\n"
            if prices and rec.get("suggested_price"):
                text += f"\nSeller's price guide: {config.get('HOME_CURRENCY')} {rec['suggested_price']:.0f}\n"
            z.writestr(f"{folder}/description.txt", text.encode("utf-8-sig"), zipfile.ZIP_DEFLATED)
            for n, (label, src) in enumerate(photo_list(rec), 1):
                done = prepare(src)
                z.write(done, f"{folder}/{ref(rec)}-{n} {safe_name(label, 40)}.jpg")
                if small:
                    done.unlink()
                photos += 1
        z.writestr("READ ME.txt", read_me("folders", len(recs)), zipfile.ZIP_DEFLATED)
    return photos


PDF_STYLE = """
@page { size: A4; margin: 14mm; }
* { box-sizing: border-box; }
body { font-family: Georgia, 'Times New Roman', serif; color: #1c1c1c; font-size: 11pt; line-height: 1.35; margin: 0; }
.cover { height: 250mm; display: flex; flex-direction: column; justify-content: center; text-align: center; }
.cover h1 { font-size: 30pt; font-weight: 400; letter-spacing: 1px; margin: 0 0 8mm; }
.cover p { margin: 2mm 0; font-size: 13pt; color: #444; }
.index { break-before: page; }
h2 { font-size: 15pt; font-weight: 400; margin: 0 0 4mm; }
table { width: 100%; border-collapse: collapse; }
.index th, .index td { text-align: left; padding: 1.2mm 2mm; border-bottom: .25mm solid #ccc; font-size: 9.5pt; vertical-align: top; }
.lot { break-before: page; }
.ref { font: 700 9pt Arial, sans-serif; letter-spacing: 1px; color: #666; }
.lot h2 { font-size: 16pt; font-weight: 700; margin: 1mm 0 4mm; border-bottom: .5mm solid #1c1c1c; padding-bottom: 2mm; }
.facts th { text-align: left; font-weight: 400; color: #666; width: 34mm; padding: .5mm 0; vertical-align: top; }
.facts td { padding: .5mm 0; }
.cond { margin: 3mm 0 4mm; white-space: pre-line; }
.photos { display: grid; grid-template-columns: repeat(3, 1fr); gap: 3mm; }
figure { margin: 0; break-inside: avoid; }
figure img { width: 100%; height: 56mm; object-fit: contain; background: #f2f2f2; display: block; }
figcaption { font: 8pt Arial, sans-serif; color: #666; padding-top: 1mm; }
"""


def pdf_html(recs: list[dict[str, Any]], pictures: dict[int, list[tuple[str, str]]], prices: bool) -> str:
    e = html.escape
    index = "".join(f"<tr><td>{ref(r)}</td><td>{e(r.get('artist') or 'Unknown artist')}</td>"
                    f"<td>{e(r.get('album_title') or 'Untitled')}</td><td>{e(format_name(r))}</td>"
                    f"<td>{e(r.get('catalog_number') or '')}</td></tr>" for r in recs)
    lots = []
    for rec in recs:
        facts = [("Format", format_name(rec)), *listings.detail_pairs(rec),
                 ("Discogs release", rec.get("discogs_release_id"))]
        if prices and rec.get("suggested_price"):
            facts.append(("Seller's price guide", f"{config.get('HOME_CURRENCY')} {rec['suggested_price']:.0f}"))
        rows = "".join(f"<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>" for k, v in facts if v)
        extra = "\n".join([*listings.condition_lines(rec), owner_line(rec), str(rec.get("notes") or "")]).strip()
        figures = "".join(f'<figure><img src="{e(src)}" alt=""><figcaption>{e(label)}</figcaption></figure>'
                          for label, src in pictures[rec["id"]])
        lots.append(f'<section class="lot"><div class="ref">{ref(rec)}</div><h2>{e(lot_title(rec))}</h2>'
                    f'<table class="facts">{rows}</table><p class="cond">{e(extra)}</p><div class="photos">{figures}</div></section>')
    when = datetime.now().strftime("%d %B %Y").lstrip("0")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Record collection</title>'
            f"<style>{PDF_STYLE}</style></head><body>"
            f'<div class="cover"><h1>Record Collection</h1><p>{len(recs)} records from {e(config.get("SELLER_NAME"))}, '
            f'{e(config.get("SELLER_LOCATION"))}</p><p>Prepared for Cordy\'s, {when}</p></div>'
            f'<div class="index"><h2>List of records</h2><table><tr><th>Ref</th><th>Artist</th><th>Title</th><th>Format</th>'
            f"<th>Catalog #</th></tr>{index}</table></div>{''.join(lots)}</body></html>")


def write_pdf(recs: list[dict[str, Any]], path: Path, small: bool, prices: bool) -> int:
    """Lay the catalogue out as a web page, then have Chrome (or Edge) print it to a PDF. Always uses small photos."""
    found = browser.find_browser()
    if found is None:
        raise CordysError("The PDF needs Google Chrome or Microsoft Edge on this computer. Please use one of the other styles.")
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        pictures: dict[int, list[tuple[str, str]]] = {}
        photos = 0
        for rec in recs:
            pictures[rec["id"]] = []
            for label, src in photo_list(rec):
                photos += 1
                dest = folder / f"{photos}.jpg"
                shrink(src, dest, PDF_PHOTO)
                pictures[rec["id"]].append((label, dest.name))
        page_file = folder / "catalogue.html"
        page_file.write_text(pdf_html(recs, pictures, prices), encoding="utf-8")
        try:
            with sync_playwright() as pw:
                chrome = pw.chromium.launch(headless=True, executable_path=found.path)
                try:
                    page = chrome.new_page()
                    page.goto(page_file.as_uri(), wait_until="load", timeout=600_000)
                    page.pdf(path=str(path), format="A4", print_background=True)
                finally:
                    chrome.close()
        except PlaywrightError as exc:
            log.warning("PDF failed: %s", exc)
            raise CordysError(f"{found.name} couldn't make the PDF. Please try again, or use one of the other styles.") from exc
    return photos


WRITERS = {"sheet": (write_sheet_zip, "zip"), "folders": (write_folders_zip, "zip"), "pdf": (write_pdf, "pdf")}


# --------------------------------------------------------------------------- putting it together
def _sort_key(rec: dict[str, Any]) -> tuple[bool, str, str]:
    clean = lambda text: re.sub(r"^(the|a|an)\s+", "", (text or "").strip().lower())   # noqa: E731 - as on the home page
    return (not clean(rec.get("artist")), clean(rec.get("artist")), clean(rec.get("album_title")))


def _warnings(recs: Iterable[dict[str, Any]]) -> list[str]:
    out = []
    for rec in recs:
        name = f"{ref(rec)} {rec.get('artist') or 'Unknown artist'} - {rec.get('album_title') or 'Untitled'}"
        if not photo_list(rec):
            out.append(f"{name} has no photos.")
        if not rec.get("artist") or not rec.get("album_title"):
            out.append(f"{name} is missing its artist or title.")
    return out


def build(record_ids: list[int], style: str, small: bool = True, prices: bool = False) -> dict[str, Any]:
    if style not in WRITERS:
        raise CordysError("Please choose one of the three styles.")
    recs = [r for r in (db.get_record(i) for i in dict.fromkeys(record_ids)) if r]
    if not recs:
        raise CordysError("Please tick at least one record first.")
    recs.sort(key=_sort_key)
    writer, ext = WRITERS[style]
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H%M%S")
    final = EXPORT_DIR / f"Cordys - {STYLES[style]} - {len(recs)} records - {stamp}.{ext}"
    part = final.with_suffix(f".part.{ext}")     # so a half-finished file never looks like a finished one
    try:
        photos = writer(recs, part, small, prices)
        part.replace(final)
    finally:
        part.unlink(missing_ok=True)
    size = final.stat().st_size
    return {"ok": True, "file": final.name, "folder": str(EXPORT_DIR), "records": len(recs), "photos": photos,
            "size": size, "fits_email": size <= EMAIL_LIMIT, "warnings": _warnings(recs),
            "record_ids": [r["id"] for r in recs]}


def export_path(name: str) -> Path | None:
    """The finished export with this name. Anything outside the exports folder is refused."""
    path = (EXPORT_DIR / name).resolve()
    return path if path.parent == EXPORT_DIR.resolve() and path.is_file() else None
