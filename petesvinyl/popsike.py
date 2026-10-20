"""Popsike: an archive of past eBay auction results (best for rare records).

Popsike has no API, so this works like a person would:
  1. Pete logs in ONCE in a normal Google Chrome window (or Edge if Chrome isn't installed) (Settings -> Connect Popsike, "Log in with Google" on their site).
     The app never sees his Google password; the login just stays in the private popsike_profile folder.
  2. For each price check the app opens that same profile invisibly, loads the search results page, and reads the
     page text. The cheap AI step picks the sold prices out of the text, so it doesn't depend on Popsike's layout.
It makes one page load per price check, at human pace. If Popsike shows a challenge/CAPTCHA the app gives up and
says so; it never tries to get around one.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import statistics
import subprocess
import sys
from typing import Any
from urllib.parse import quote_plus

from . import activity, ai, browser, config, currency
from .config import BASE_DIR

log = logging.getLogger("petesvinyl.popsike")
PROFILE_DIR = config.DATA_DIR / "popsike_profile"   # kept with the library, so the login survives updates
HOME_URL = "https://www.popsike.com/"
DEFAULT_SEARCH_URL = "https://www.popsike.com/php/quicksearch.php?searchtext={query}"
_lock = asyncio.Lock()
BLOCK_WORDS = ("captcha", "verify you are human", "are you a robot", "access denied", "just a moment", "unusual traffic")


def enabled() -> bool:
    return config.get_bool("POPSIKE_ENABLED")


def is_connected() -> bool:
    return config.get("POPSIKE_CONNECTED") == "yes"


def search_query(rec: dict[str, Any]) -> str:
    return " ".join(filter(None, [(rec.get("artist") or "").strip(), (rec.get("album_title") or "").strip()]))


def search_url(rec: dict[str, Any]) -> str:
    template = config.get("POPSIKE_SEARCH_URL") or DEFAULT_SEARCH_URL
    return template.replace("{query}", quote_plus(search_query(rec)))


# --------------------------------------------------------------------------- logging in
def _kill_profile_browser() -> None:
    browser.kill_profile_windows(["popsike_profile"])


def open_login() -> dict[str, Any]:
    """Open a NORMAL browser window (not automated, so Google allows the sign-in) on Popsike with its own profile."""
    found = browser.find_browser()
    if not found:
        activity.record("Popsike", "Login window", False, "Neither Google Chrome nor Microsoft Edge was found.")
        return {"ok": False, "message": "I couldn't find Google Chrome (or Microsoft Edge) on this computer."}
    _kill_profile_browser()
    PROFILE_DIR.mkdir(exist_ok=True)
    subprocess.Popen([found.path, f"--user-data-dir={PROFILE_DIR}", "--no-first-run", "--no-default-browser-check", HOME_URL])
    activity.record("Popsike", f"Opened the Popsike login window in {found.name}", True)
    return {"ok": True, "message": "A Popsike window has opened. Log in there (you can use 'Log in with Google'), "
                                   "then come back here and press 'I've logged in'."}


def finish_login() -> dict[str, Any]:
    from . import db
    _kill_profile_browser()
    db.set_setting("POPSIKE_CONNECTED", "yes")
    activity.record("Popsike", "Marked as logged in", True, "Press 'Test Popsike' to check it can read prices.")
    return {"ok": True, "message": "Saved. Press 'Test Popsike' to check it can read prices."}


# --------------------------------------------------------------------------- reading the page
async def fetch_page_text(url: str) -> dict[str, Any]:
    """Load the page and return {text, title, url, status}. Also saves logs/popsike_last.png + popsike_last.txt
    so it is easy to see exactly what Popsike showed the app."""
    from playwright.async_api import async_playwright
    kwargs: dict[str, Any] = {"headless": True, "viewport": {"width": 1280, "height": 900},
                              "args": ["--disable-blink-features=AutomationControlled"]}
    exe = os.environ.get("PETESVINYL_BROWSER_EXE")   # used by the automated tests
    if exe:
        kwargs["executable_path"] = exe
    elif browser.find_browser():
        kwargs["channel"] = browser.find_browser().channel   # same browser that did the login, so the saved login is readable
    PROFILE_DIR.mkdir(exist_ok=True)
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(str(PROFILE_DIR), **kwargs)
        try:
            page = await ctx.new_page()
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:  # noqa: BLE001 - some pages never go fully idle; carry on with what's there
                pass
            await page.wait_for_timeout(1500)
            text = await page.inner_text("body")
            info = {"text": text, "title": await page.title(), "url": page.url, "status": resp.status if resp else None}
            try:
                config.LOGS_DIR.mkdir(exist_ok=True)
                await page.screenshot(path=str(config.LOGS_DIR / "popsike_last.png"))
                (config.LOGS_DIR / "popsike_last.txt").write_text(f"{info['url']}\n{info['title']}\n\n{text}", encoding="utf-8")
            except Exception:  # noqa: BLE001 - diagnostics are a bonus
                pass
            return info
        finally:
            await ctx.close()


EXTRACT_PROMPT = """Below is the text of a Popsike search results page (an archive of finished eBay auctions) for: "{query}".
Each listing shows a title, a sold date, and one or two prices. When two prices are shown, the first is in the seller's
own currency and the second is converted to US dollars. Count each LISTING once, and use the USD price when shown,
otherwise the price shown. Ignore the filters, menus and anything that isn't a listing.

The record being valued: {artist} - {album}, pressed {year} in {country}, label {label}, catalogue number {catno}.
List the listings that are this album on vinyl (skip CDs, cassettes, singles, other albums, bundles of several records).
For each, set "same_pressing" to true if the title suggests the same pressing (same year, country, label or
catalogue number), false if it's clearly a different one (e.g. a reissue or audiophile edition), or null if unclear.

Reply with ONLY a JSON object:
{{"results": [{{"title": "", "price": 0.0, "currency": "USD", "date": "", "same_pressing": null}}],
  "login_needed": false, "note": "one short sentence about what the page showed"}}
If the page asks the visitor to log in, set login_needed to true. If nothing matches, return an empty list.

PAGE TEXT:
{text}"""

PRICE_RE = re.compile(r"(US\s?\$|A\$|NZ\$|\$|£|€|USD|GBP|EUR)\s?([\d][\d,]*(?:\.\d{1,2})?)")
SYMBOL_CUR = {"$": "USD", "US$": "USD", "US $": "USD", "A$": "AUD", "NZ$": "NZD", "£": "GBP", "€": "EUR"}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _looks_same(title: str, rec: dict[str, Any]) -> bool | None:
    """Does a listing title mention this pressing's catalogue number or year?"""
    t = _norm(title)
    cat = _norm(rec.get("catalog_number") or "")
    if cat and len(cat) >= 4 and cat in t:
        return True
    year = (rec.get("year_pressed") or "").strip()[:4]
    if year.isdigit() and year in title:
        return True
    return None


def _fallback_parse(text: str, rec: dict[str, Any]) -> list[dict[str, Any]]:
    """No AI (or it found nothing): read the page the way it is laid out.

    Popsike shows each listing as a title line, then a date line, then one or two price lines (the seller's currency,
    then US dollars). So: start a listing at each title line that mentions the album, and collect the prices that
    follow it, up to the next title.
    """
    words = [w for w in re.findall(r"[a-z0-9]+", (rec.get("album_title") or "").lower()) if len(w) > 3]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    items: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    since_title = 0
    for line in lines:
        low = line.lower()
        prices = PRICE_RE.findall(line)
        if not prices and len(line) > 15 and (not words or any(w in low for w in words)):
            cur = {"title": line[:90], "prices": []}
            items.append(cur)
            since_title = 0
            continue
        since_title += 1
        if cur is not None and prices and since_title <= 6:
            for sym, amount in prices:
                code = SYMBOL_CUR.get(sym.replace(" ", ""), sym.upper().replace(" ", ""))
                try:
                    cur["prices"].append((code, float(amount.replace(",", ""))))
                except ValueError:
                    continue
    out = []
    for item in items:
        if not item["prices"]:
            continue
        usd = [p for p in item["prices"] if p[0] == "USD"]
        code, amount = (usd or item["prices"])[0]          # one price per listing, USD if shown
        out.append({"title": item["title"], "price": amount, "currency": code, "same_pressing": _looks_same(item["title"], rec)})
    return out[:30]


async def lookup(rec: dict[str, Any]) -> dict[str, Any]:
    """Returns {"median": float|None (home currency), "count": int, "note": str, "url": str}."""
    home = config.get("HOME_CURRENCY")
    query = search_query(rec)
    url = search_url(rec)
    result: dict[str, Any] = {"median": None, "count": 0, "note": "", "url": url}
    if not query:
        result["note"] = "No artist or album to look up."
        return result
    async with _lock:
        try:
            page_info = await fetch_page_text(url)
            text = page_info["text"]
        except Exception as exc:  # noqa: BLE001 - a browser problem must never break a price check
            activity.record("Popsike", f"Loading results for {query}", False, f"Couldn't open the page: {exc}")
            result["note"] = "Couldn't open Popsike."
            return result
    snippet = " | ".join(line.strip() for line in text.splitlines() if line.strip())[:400]
    seen = (f"Page: \"{page_info['title']}\" at {page_info['url']} (HTTP {page_info['status']}), "
            f"{len(text)} characters of text. Starts: {snippet or '(empty page)'}")
    low = text.lower()
    if any(w in low[:3000] for w in BLOCK_WORDS):
        activity.record("Popsike", f"Loading results for {query}", False,
                        "Popsike showed a check (CAPTCHA/verification). The app doesn't try to get around it. "
                        "Open Popsike yourself, complete it, then try again later.")
        result["note"] = "Popsike asked for a verification check."
        return result
    rows: list[dict[str, Any]] = []
    if ai.is_configured():
        try:
            data = await ai.chat_json([{"type": "text", "text": EXTRACT_PROMPT.format(
                query=query, artist=rec.get("artist") or "", album=rec.get("album_title") or "",
                year=rec.get("year_pressed") or "unknown", country=rec.get("pressing_location") or "unknown",
                label=rec.get("label") or "unknown", catno=rec.get("catalog_number") or "unknown",
                text=text[:14000])}], web_search=False, max_tokens=3000)
            rows = [r for r in data.get("results") or [] if isinstance(r, dict) and r.get("price")]
            result["note"] = data.get("note") or ""
            if data.get("login_needed"):
                result["note"] = "Popsike wants a login: Settings -> Connect Popsike."
        except (ai.AIUnavailable, ValueError) as exc:
            result["note"] = f"Couldn't read the page with the AI: {exc}"
    if not rows:        # no AI key, or the AI found nothing: read the page directly
        rows = _fallback_parse(text, rec)
    same = [r for r in rows if r.get("same_pressing") is True]
    chosen = same if len(same) >= 3 else rows     # favour the same pressing when there are enough of them
    if rows:
        result["note"] = (result["note"] + " " if result["note"] else "") + (
            f"{len(same)} of {len(rows)} look like the same pressing" + (", using those." if len(same) >= 3 else ", using all."))
    prices = []
    for r in chosen:
        try:
            converted = await currency.convert(float(r["price"]), str(r.get("currency") or "USD"), home)
        except (TypeError, ValueError):
            continue
        if converted and 1 <= converted <= 20000:
            prices.append(converted)
    if prices:
        result["median"] = statistics.median(prices)
        result["count"] = len(prices)
    examples = "; ".join(f"{str(r.get('title'))[:45]} {r.get('currency')} {r.get('price')}" for r in chosen[:3])
    activity.record("Popsike", f"Sold auctions for {query}", bool(prices),
                    (f"Examples: {examples}. " if examples else "") + f"{len(prices)} sale prices found" + (f", middle price {home} {result['median']:.0f}" if prices else "")
                    + (f". {result['note']}" if result["note"] else "")
                    + ("" if prices else f"\n{seen}\n(A screenshot and the page text are saved in the logs folder: "
                                          "popsike_last.png and popsike_last.txt)"))
    return result
