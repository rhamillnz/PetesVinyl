"""Work out what a record is worth by combining every price source we can reach.

Sources, best first:
  1. Discogs API       - suggested price for this exact pressing + condition (needs DISCOGS_API_TOKEN)
  2. eBay sold listings - best-effort scrape of completed sales (eBay sometimes blocks this)
  3. AI web research   - OpenRouter model searches sold prices on the web (needs OPENROUTER_API_KEY)
  4. Heuristic         - rough fallback by age/condition so Pete always gets a number
"""
from __future__ import annotations

import logging
import math
import re
import statistics
from typing import Any
from urllib.parse import quote_plus

import httpx

from . import activity, ai, config, currency, discogs

log = logging.getLogger("petesvinyl.valuation")

CONDITION_FACTOR = {"M": 1.3, "NM": 1.15, "VG+": 1.0, "VG": 0.65, "G+": 0.4, "G": 0.25, "F": 0.12, "P": 0.08}
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
PRICE_RE = re.compile(r'class="s-(?:item|card)__price[^"]*"[^>]*>(?:\s*<span[^>]*>)?\s*(?:US\s*)?\$([\d,]+\.\d{2})')


async def ebay_sold_prices(query: str) -> list[float]:
    """Scrape recent SOLD prices (USD) from eBay.com search results. Returns [] if blocked."""
    url = (
        "https://www.ebay.com/sch/i.html?_nkw="
        + quote_plus(query)
        + "&_sacat=176985&LH_Sold=1&LH_Complete=1&_ipg=60"
    )
    try:
        async with httpx.AsyncClient(timeout=20, headers=BROWSER_HEADERS, follow_redirects=True) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            activity.record("eBay", "Sold-listings lookup", False, f"eBay refused ({resp.status_code}); using other sources")
            return []
        prices = [float(p.replace(",", "")) for p in PRICE_RE.findall(resp.text)]
        # eBay's first card is often a placeholder; drop silly outliers too.
        prices = [p for p in prices[1:] if 1 <= p <= 5000][:20]
        activity.record("eBay", f"Sold-listings lookup: {query}", bool(prices), f"{len(prices)} sale prices found")
        return prices
    except httpx.HTTPError as exc:
        log.info("eBay sold scrape failed: %s", exc)
        return []


def heuristic_value(record: dict[str, Any]) -> float:
    """Very rough baseline (NZD) when no market data is available."""
    base = 20.0
    try:
        year = int(str(record.get("year_pressed") or record.get("original_year") or "")[:4])
        if year < 1965:
            base = 35
        elif year < 1980:
            base = 28
        elif year < 1995:
            base = 22
        else:
            base = 30  # modern pressings are usually pricier new
    except ValueError:
        pass
    return base * CONDITION_FACTOR.get(record.get("condition_media") or "VG+", 1.0)


def nice_price(value: float) -> float:
    """Round to a price that looks natural on a listing: 9, 14, 19, 24, 29, 35, 45, 59, 79, 99, 149..."""
    if value <= 0:
        return 0
    if value < 10:
        return max(5.0, math.ceil(value))
    if value < 50:
        return float(math.ceil(value / 5) * 5 - 1)
    if value < 200:
        return float(math.ceil(value / 10) * 10 - 1)
    return float(math.ceil(value / 25) * 25)


async def estimate(record: dict[str, Any]) -> dict[str, Any]:
    home = config.get("HOME_CURRENCY")
    condition = record.get("condition_media") or "VG+"
    sources: list[dict[str, Any]] = []
    notes: list[str] = []

    discogs_value = None
    if not record.get("discogs_release_id"):
        activity.record("Valuation", "No Discogs pressing chosen for this record, so no Discogs price",
                        False, "Pick the matching pressing on the Check details screen")
    if record.get("discogs_release_id") and discogs.is_configured():
        mv = await discogs.market_value(str(record["discogs_release_id"]), condition)
        amount = mv.get("suggested") or mv.get("lowest")
        activity.record("Valuation", "Discogs price data", bool(amount), str(mv))
        discogs_value = await currency.convert(amount, mv.get("currency") or home, home)
        if discogs_value:
            what = "suggested price" if mv.get("suggested") else "cheapest copy for sale"
            sources.append({"name": "Discogs", "value": discogs_value, "weight": 3})
            notes.append(f"Discogs {what}: {home} {discogs_value:.0f}" +
                         (f" ({mv['num_for_sale']} copies for sale)" if mv.get("num_for_sale") else ""))

    query = " ".join(filter(None, [record.get("artist"), record.get("album_title"), record.get("catalog_number")]))
    ebay_avg = None
    if query.strip():
        prices = await ebay_sold_prices(query + " vinyl")
        if len(prices) >= 3:
            ebay_avg = await currency.convert(statistics.median(prices), "USD", home)
            sources.append({"name": "eBay sold", "value": ebay_avg, "weight": 2})
            notes.append(f"eBay: {len(prices)} recent sales, middle price {home} {ebay_avg:.0f}")

    ai_value = None
    ai_reason = ""
    # The AI web search costs real money (about 2c a time), so only use it when Discogs and eBay
    # gave us nothing to go on.
    if ai.is_configured() and query.strip() and not sources:
        try:
            res = await ai.research_value(record)
            typical = res.get("typical_price") or {}
            if typical.get("price"):
                ai_value = await currency.convert(float(typical["price"]), typical.get("currency") or home, home)
            if not discogs_value:
                dm = res.get("discogs_median") or {}
                if dm.get("price"):
                    discogs_value = await currency.convert(float(dm["price"]), dm.get("currency"), home)
                    if discogs_value:
                        sources.append({"name": "Discogs (web)", "value": discogs_value, "weight": 2})
            if not ebay_avg:
                sold = [p for p in res.get("ebay_sold_prices") or [] if p.get("price")]
                converted = [await currency.convert(float(p["price"]), p.get("currency"), home) for p in sold]
                converted = [c for c in converted if c]
                if converted:
                    ebay_avg = statistics.mean(converted)
                    sources.append({"name": "eBay sold (web)", "value": ebay_avg, "weight": 2})
            if ai_value:
                sources.append({"name": "AI research", "value": ai_value, "weight": 2})
            ai_reason = res.get("reasoning", "")
        except (ai.AIUnavailable, ValueError) as exc:
            notes.append(f"AI price check skipped: {exc}")

    if sources:
        total_weight = sum(s["weight"] for s in sources)
        market = sum(s["value"] * s["weight"] for s in sources) / total_weight
        confidence = "good" if len(sources) >= 2 else "fair"
    else:
        market = heuristic_value(record)
        confidence = "rough guess"
        notes.append("No market data found, so this is a rough guess. Add a Discogs token or OpenRouter key in Settings for real prices.")

    suggested = nice_price(market * 1.1)  # list a little above market to leave room for offers
    if ai_reason:
        notes.insert(0, ai_reason)

    return {
        "currency": home,
        "discogs_median": round(discogs_value, 2) if discogs_value else None,
        "ebay_sold_average": round(ebay_avg, 2) if ebay_avg else None,
        "ai_estimate": round(ai_value, 2) if ai_value else None,
        "estimated_value": round(market, 2),
        "suggested_price": suggested,
        "confidence": confidence,
        "sources": [s["name"] for s in sources],
        "notes": notes,
    }
