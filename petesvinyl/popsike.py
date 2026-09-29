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
PROFILE_DIR = BASE_DIR / "popsike_profile"
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
async def fetch_page_text(url: str) -> str:
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
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)
            return await page.inner_text("body")
        finally:
            await ctx.close()


EXTRACT_PROMPT = """Below is the text of a Popsike search results page (a archive of finished eBay auctions) for: "{query}".
List the SOLD auction results that are for THIS record: {artist} - {album} (vinyl LP). Skip other albums, CDs and unrelated items.
Reply with ONLY a JSON object:
{{"results": [{{"title": "", "price": 0.0, "currency": "USD", "date": "", "condition": ""}}],
  "login_needed": false, "note": "one short sentence about what the page showed"}}
Use the final sold price shown, and the currency symbol/code shown (USD if it says $). If the page asks the visitor to
log in, sets login_needed to true. If there are no matching results, return an empty list.

PAGE TEXT:
{text}"""

PRICE_RE = re.compile(r"(US\s?\$|A\$|NZ\$|\$|£|€|USD|GBP|EUR)\s?([\d][\d,]*(?:\.\d{1,2})?)")
SYMBOL_CUR = {"$": "USD", "US$": "USD", "US $": "USD", "A$": "AUD", "NZ$": "NZD", "£": "GBP", "€": "EUR"}


def _fallback_parse(text: str, rec: dict[str, Any]) -> list[dict[str, Any]]:
    """No AI available: take prices from lines that mention the album title."""
    words = [w for w in re.findall(r"[a-z0-9]+", (rec.get("album_title") or "").lower()) if len(w) > 3]
    out = []
    for line in text.splitlines():
        low = line.lower()
        if words and not any(w in low for w in words):
            continue
        for sym, amount in PRICE_RE.findall(line):
            cur = SYMBOL_CUR.get(sym.replace(" ", ""), sym.upper()) if sym not in SYMBOL_CUR else SYMBOL_CUR[sym]
            try:
                out.append({"title": line.strip()[:80], "price": float(amount.replace(",", "")), "currency": cur})
            except ValueError:
                continue
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
            text = await fetch_page_text(url)
        except Exception as exc:  # noqa: BLE001 - a browser problem must never break a price check
            activity.record("Popsike", f"Loading results for {query}", False, f"Couldn't open the page: {exc}")
            result["note"] = "Couldn't open Popsike."
            return result
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
                query=query, artist=rec.get("artist") or "", album=rec.get("album_title") or "", text=text[:14000])}],
                web_search=False, max_tokens=2500)
            rows = [r for r in data.get("results") or [] if isinstance(r, dict) and r.get("price")]
            result["note"] = data.get("note") or ""
            if data.get("login_needed"):
                result["note"] = "Popsike wants a login: Settings -> Connect Popsike."
        except (ai.AIUnavailable, ValueError) as exc:
            result["note"] = f"Couldn't read the page with the AI: {exc}"
    if not rows and not ai.is_configured():
        rows = _fallback_parse(text, rec)
    prices = []
    for r in rows:
        try:
            converted = await currency.convert(float(r["price"]), str(r.get("currency") or "USD"), home)
        except (TypeError, ValueError):
            continue
        if converted and 1 <= converted <= 20000:
            prices.append(converted)
    if prices:
        result["median"] = statistics.median(prices)
        result["count"] = len(prices)
    activity.record("Popsike", f"Sold auctions for {query}", bool(prices),
                    f"{len(prices)} sale prices found" + (f", middle price {home} {result['median']:.0f}" if prices else "")
                    + (f". {result['note']}" if result["note"] else ""))
    return result
