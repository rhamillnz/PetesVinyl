"""Build ready-to-paste listing text for each site, and pick the best sites for a record."""
from __future__ import annotations

import math
from typing import Any

from . import config, currency

PLATFORMS: dict[str, dict[str, Any]] = {
    "trademe": {
        "name": "TradeMe",
        "where": "New Zealand buyers",
        "currency": "NZD",
        "sell_url": "https://www.trademe.co.nz/a/list",
        "title_max": 80,
        "api": True,
    },
    "discogs": {
        "name": "Discogs",
        "where": "Collectors worldwide (USA, UK, Europe)",
        "currency": None,  # uses Pete's Discogs seller currency, normally NZD
        "sell_url": "https://www.discogs.com/sell/list",
        "title_max": 255,
        "api": True,
    },
    "ebay": {
        "name": "eBay",
        "where": "USA, UK and Australia",
        "currency": None,  # EBAY_CURRENCY setting
        "sell_url": "https://www.ebay.com/sl/sell",
        "title_max": 80,
        "api": True,
    },
    "facebook": {
        "name": "Facebook Marketplace",
        "where": "Local buyers near Pete",
        "currency": "NZD",
        "sell_url": "https://www.facebook.com/marketplace/create/item",
        "title_max": 100,
        "api": False,
    },
    "gumtree": {
        "name": "Gumtree",
        "where": "Australia",
        "currency": "AUD",
        "sell_url": "https://www.gumtree.com.au/p-post-ad.html",
        "title_max": 65,
        "api": False,
    },
}

CONDITION_WORDS = {
    "M": "Mint (unplayed)",
    "NM": "Near Mint - like new",
    "VG+": "Very Good Plus - light signs of play, plays great",
    "VG": "Very Good - some surface noise, plays through",
    "G+": "Good Plus - well played, noticeable noise",
    "G": "Good - heavily played",
    "F": "Fair",
    "P": "Poor",
}


COVER_GRADE_WORDS = {
    "M": "Mint", "NM": "Near Mint - like new", "VG+": "Very Good Plus - light wear",
    "VG": "Very Good - some wear", "G+": "Good Plus - noticeable wear", "G": "Good - heavy wear",
    "F": "Fair", "P": "Poor",
}


def enabled_platforms() -> list[str]:
    raw = config.get("ENABLED_PLATFORMS")
    return [p.strip() for p in raw.split(",") if p.strip() in PLATFORMS]


def recommend(value: float | None) -> list[str]:
    """Pick the best 1-4 sites for a record worth `value` in Pete's home currency."""
    v = value or 0
    if v < 15:
        picks = ["trademe", "facebook"]  # cheap records: local, low postage
    elif v < 40:
        picks = ["trademe", "discogs", "facebook"]
    elif v < 100:
        picks = ["trademe", "discogs", "ebay"]
    else:
        picks = ["discogs", "ebay", "trademe", "gumtree"]  # collectors worldwide pay most
    enabled = enabled_platforms()
    return [p for p in picks if p in enabled][:4] or enabled[:1]


def platform_currency(platform: str) -> str:
    fixed = PLATFORMS[platform]["currency"]
    if fixed:
        return fixed
    if platform == "ebay":
        return config.get("EBAY_CURRENCY") or "USD"
    return config.get("HOME_CURRENCY")


SCRATCH_WORDS = {"none": "no visible scratches", "light": "light hairline scratches only",
                 "some": "some visible scratches", "deep": "deep scratches you can feel"}
PLAY_WORDS = {"perfect": "plays perfectly, no surface noise", "crackle": "plays with slight surface crackle",
              "noisy": "plays with noticeable clicks and pops", "skips": "skips or jumps in places"}
CREASE_WORDS = {"none": "no creases", "slight": "slight creasing", "noticeable": "noticeable creases",
                "bad": "heavy creasing"}
COVER_ISSUE_WORDS = {"seam_split": "split seam", "ring_wear": "ring wear", "writing": "writing or stamp on cover",
                     "stain": "water stain or mould", "tear": "tear"}


def _sentence(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    return (parts[0][0].upper() + parts[0][1:] + (", " + ", ".join(parts[1:]) if len(parts) > 1 else "") + ".") if parts else ""


def condition_lines(rec: dict[str, Any]) -> list[str]:
    """Plain-English condition, focused on scratches / how it plays (record) and creases / damage (cover)."""
    media = CONDITION_WORDS.get(rec.get("condition_media") or "VG+", rec.get("condition_media") or "")
    cover = COVER_GRADE_WORDS.get(rec.get("condition_sleeve") or "VG+", rec.get("condition_sleeve") or "")
    lines = [f"Record condition: {media}"]
    detail = _sentence([SCRATCH_WORDS.get(rec.get("media_scratches") or "", ""), PLAY_WORDS.get(rec.get("media_play") or "", "")])
    if detail:
        lines.append(f"  {detail}")
    lines.append(f"Cover condition: {cover}")
    issues = [COVER_ISSUE_WORDS[i] for i in rec.get("cover_issues") or [] if i in COVER_ISSUE_WORDS]
    detail = _sentence([CREASE_WORDS.get(rec.get("cover_creases") or "", "")] + issues)
    if detail:
        lines.append(f"  {detail}")
    return lines


def disc_label(rec: dict[str, Any]) -> str:
    n = int(rec.get("disc_count") or 1)
    return "Vinyl LP" if n == 1 else {2: "Double LP", 3: "Triple LP"}.get(n, f"{n}xLP") + " Vinyl"


def make_title(rec: dict[str, Any], max_len: int) -> str:
    bits = [f"{rec.get('artist') or 'Unknown'} - {rec.get('album_title') or 'Untitled'}", disc_label(rec)]
    if rec.get("year_pressed"):
        bits.append(str(rec["year_pressed"]))
    if rec.get("pressing_location"):
        bits.append(str(rec["pressing_location"]).split("(")[0].strip() + " Pressing")
    if rec.get("catalog_number"):
        bits.append(str(rec["catalog_number"]))
    title = ""
    for bit in bits:
        candidate = f"{title} {bit}".strip() if title else bit
        if len(candidate) > max_len:
            break
        title = candidate
    return title[:max_len]


def make_description(rec: dict[str, Any], platform: str) -> str:
    lines = [f"{rec.get('artist') or 'Unknown artist'} - {rec.get('album_title') or 'Untitled'}", ""]
    details = [
        ("Label", rec.get("label")),
        ("Catalogue number", rec.get("catalog_number")),
        ("Pressed", rec.get("year_pressed")),
        ("Original release", rec.get("original_year") if rec.get("original_year") != rec.get("year_pressed") else ""),
        ("Pressed in", rec.get("pressing_location")),
        ("Matrix / runout", rec.get("matrix_numbers")),
        ("Barcode", rec.get("barcode")),
    ]
    for label, value in details:
        if value:
            lines.append(f"{label}: {value}")
    discs = int(rec.get("disc_count") or 1)
    if discs > 1:
        lines += ["", f"This is a {discs}-record set: all {discs} discs are included in the cover."]
    extras = [e.get("label") for e in rec.get("extra_images") or [] if e.get("label")]
    inserts = [x for x in extras if not x.lower().startswith("disc")]
    if inserts:
        lines.append("Photos also show: " + ", ".join(dict.fromkeys(inserts)) + ".")
    lines += ["", *condition_lines(rec)]
    owners = rec.get("number_of_owners") or 1
    if rec.get("is_first_owner") or owners == 1:
        lines.append("One owner from new - I bought this record myself and have looked after it.")
    else:
        lines.append(f"This copy has had {owners} owners.")
    if rec.get("notes"):
        lines += ["", str(rec["notes"])]
    lines += ["", "Photos are of the actual record(s) you will receive."]
    ship = config.get("SHIPPING_NOTE")
    if ship:
        lines += ["", ship]
    if platform in ("ebay", "discogs", "gumtree"):
        lines.append(f"Posted from {config.get('SELLER_LOCATION')} - international buyers welcome.")
    lines += ["", f"Thanks for looking! - {config.get('SELLER_NAME')}"]
    return "\n".join(lines)


def _round_listing_price(v: float) -> float:
    if v < 50:
        return float(max(5, math.ceil(v)))
    return float(math.ceil(v / 5) * 5)


async def build(rec: dict[str, Any], platform: str) -> dict[str, Any]:
    meta = PLATFORMS[platform]
    cur = platform_currency(platform)
    home_price = rec.get("suggested_price") or 0
    home = config.get("HOME_CURRENCY")
    if cur == home or not home_price:
        price = float(home_price or 0)
    else:
        price = _round_listing_price(await currency.convert(home_price, home, cur) or 0)
    tips = {
        "trademe": "Choose category: Music & instruments > Vinyl. Tick Buy Now if you'd like a quick sale.",
        "discogs": "Search the catalogue number, pick the exact pressing, then fill in condition and price.",
        "ebay": "Choose 'Ship internationally' so buyers in the USA, UK and Australia can buy.",
        "facebook": "Choose category 'Entertainment' and add your suburb so locals can find it.",
        "gumtree": "Gumtree is mainly for Australian locals - mention you post from New Zealand.",
    }
    sell_url = meta["sell_url"]
    if platform == "discogs" and rec.get("discogs_release_id"):
        sell_url = f"https://www.discogs.com/sell/post/{rec['discogs_release_id']}"
    return {
        "platform": platform,
        "name": meta["name"],
        "where": meta["where"],
        "title": make_title(rec, meta["title_max"]),
        "description": make_description(rec, platform),
        "price": price,
        "currency": cur,
        "sell_url": sell_url,
        "tip": tips.get(platform, ""),
        "status": rec.get(f"{platform}_status", "not_listed"),
        "link": (rec.get("listing_links") or {}).get(platform, ""),
    }
