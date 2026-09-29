"""Publishing to the selling sites.

Every site ALWAYS gets a copy-and-paste Listing Helper (see listings.build). On top of that:
  * Discogs  - real API listing (easy: personal token). Posted as Draft by default so it can be checked.
  * TradeMe  - real API listing via OAuth 1.0a once you have an approved TradeMe API app + tokens.
  * eBay     - real Inventory API listing once you have an eBay developer app + user token + policies.
  * Facebook / Gumtree - no public listing API, so a real browser window (Playwright) opens the
    "sell" page and fills in what it can. Pete checks it and clicks Post himself.
If a site's keys aren't set, it simply stays on the Listing Helper.
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

import httpx

from . import browser, config, discogs, listings
from .config import BROWSER_PROFILE_DIR, IMAGES_DIR
from .db import IMAGE_SLOTS

log = logging.getLogger("petesvinyl.publish")


class NotConfigured(Exception):
    """Raised when a site has no API keys; the caller falls back to the Listing Helper."""


def image_paths(rec: dict[str, Any]) -> list[Path]:
    paths = []
    for col in IMAGE_SLOTS.values():
        if rec.get(col):
            p = IMAGES_DIR / rec[col]
            if p.exists():
                paths.append(p)
    for extra in rec.get("extra_images") or []:
        p = IMAGES_DIR / (extra.get("path") or "")
        if extra.get("path") and p.exists():
            paths.append(p)
    return paths


# --------------------------------------------------------------------------- Discogs
async def publish_discogs(rec: dict[str, Any], listing: dict[str, Any]) -> dict[str, Any]:
    if not discogs.is_configured():
        raise NotConfigured("Add a Discogs token in Settings to post automatically.")
    if not rec.get("discogs_release_id"):
        raise NotConfigured("This record isn't matched to a Discogs release yet - pick one on the record's page.")
    comments = f"{listings.CONDITION_WORDS.get(rec.get('condition_media') or 'VG+', '')}. {config.get('SHIPPING_NOTE')}"
    res = await discogs.create_listing(rec, listing["price"], comments)
    status = "listed" if res["status"] == "For Sale" else "draft"
    url = f"https://www.discogs.com/sell/item/{res['listing_id']}" if res.get("listing_id") else ""
    msg = "Listed on Discogs." if status == "listed" else "Saved as a Discogs draft - open it and press 'For Sale' when happy."
    return {"status": status, "url": url, "message": msg}


# --------------------------------------------------------------------------- TradeMe
def _trademe_base() -> str:
    return "https://api.tmsandbox.co.nz/v1" if config.get_bool("TRADEME_SANDBOX") else "https://api.trademe.co.nz/v1"


def _trademe_auth() -> str:
    keys = [config.get(k) for k in ("TRADEME_CONSUMER_KEY", "TRADEME_CONSUMER_SECRET",
                                     "TRADEME_OAUTH_TOKEN", "TRADEME_OAUTH_TOKEN_SECRET")]
    if not all(keys):
        raise NotConfigured("TradeMe API keys aren't set up yet, so use the Listing Helper.")
    ck, cs, tok, ts = keys
    # TradeMe accepts OAuth 1.0a PLAINTEXT signatures over HTTPS.
    return (f'OAuth oauth_consumer_key="{ck}", oauth_token="{tok}", '
            f'oauth_signature_method="PLAINTEXT", oauth_signature="{cs}&{ts}"')


async def publish_trademe(rec: dict[str, Any], listing: dict[str, Any]) -> dict[str, Any]:
    auth = _trademe_auth()
    category = config.get("TRADEME_CATEGORY")
    if not category:
        raise NotConfigured("Set TRADEME_CATEGORY (the TradeMe vinyl category number) in Settings.")
    base = _trademe_base()
    headers = {"Authorization": auth}
    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        photo_ids = []
        for path in image_paths(rec):
            resp = await client.post(f"{base}/Photos.json", json={
                "PhotoData": base64.b64encode(path.read_bytes()).decode("ascii"),
                "FileName": path.name,
                "FileType": "JPG",
            })
            resp.raise_for_status()
            if resp.json().get("PhotoId"):
                photo_ids.append(resp.json()["PhotoId"])
        body = {
            "Category": category,
            "Title": listing["title"],
            "Description": [p for p in listing["description"].split("\n\n") if p.strip()],
            "Duration": int(config.get_float("TRADEME_DURATION_DAYS", 7)),
            "StartPrice": listing["price"],
            "ReservePrice": listing["price"],
            "BuyNowPrice": round(listing["price"] * 1.2),
            "IsNew": False,
            "PhotoIds": photo_ids,
            "Pickup": 1,  # pickup allowed
            "ShippingOptions": [{"Type": 4, "Price": 10, "Method": "Tracked courier (NZ)"}],
            "PaymentMethods": [1, 2],  # bank deposit, cash
        }
        resp = await client.post(f"{base}/Selling.json", json=body)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("Success"):
        raise RuntimeError(data.get("Description") or "TradeMe didn't accept the listing.")
    listing_id = data.get("ListingId")
    host = "www.tmsandbox.co.nz" if config.get_bool("TRADEME_SANDBOX") else "www.trademe.co.nz"
    return {"status": "listed", "url": f"https://{host}/Browse/Listing.aspx?id={listing_id}",
            "message": f"Listed on TradeMe (listing #{listing_id})."}


# --------------------------------------------------------------------------- eBay
def _ebay_hosts() -> tuple[str, str, str]:
    if config.get_bool("EBAY_SANDBOX"):
        return "https://api.sandbox.ebay.com", "https://apim.sandbox.ebay.com", "https://sandbox.ebay.com"
    return "https://api.ebay.com", "https://apim.ebay.com", "https://www.ebay.com"


EBAY_CONDITIONS = {"M": "NEW", "NM": "USED_EXCELLENT", "VG+": "USED_EXCELLENT", "VG": "USED_VERY_GOOD",
                   "G+": "USED_GOOD", "G": "USED_ACCEPTABLE", "F": "USED_ACCEPTABLE", "P": "FOR_PARTS_OR_NOT_WORKING"}


async def publish_ebay(rec: dict[str, Any], listing: dict[str, Any]) -> dict[str, Any]:
    token = config.get("EBAY_OAUTH_TOKEN")
    needed = ["EBAY_FULFILLMENT_POLICY_ID", "EBAY_PAYMENT_POLICY_ID", "EBAY_RETURN_POLICY_ID", "EBAY_LOCATION_KEY"]
    if not token or not all(config.get(k) for k in needed):
        raise NotConfigured("eBay API keys/policies aren't set up yet, so use the Listing Helper.")
    api, media, site = _ebay_hosts()
    headers = {"Authorization": f"Bearer {token}", "Content-Language": "en-US", "Accept-Language": "en-US"}
    sku = f"PETESVINYL-{rec['id']}"
    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        # 1. Upload photos to eBay picture hosting (eBay needs public image URLs).
        image_urls = []
        for path in image_paths(rec):
            resp = await client.post(f"{media}/commerce/media/v1_beta/image/create_image_from_file",
                                     files={"image": (path.name, path.read_bytes(), "image/jpeg")})
            resp.raise_for_status()
            location = resp.headers.get("Location")
            if location:
                img = await client.get(location)
                img.raise_for_status()
                if img.json().get("imageUrl"):
                    image_urls.append(img.json()["imageUrl"])
        # 2. Inventory item.
        aspects = {"Format": ["Record"], "Record Size": ['12"'], "Speed": ["33 RPM"]}
        if rec.get("artist"):
            aspects["Artist"] = [rec["artist"]]
        if rec.get("album_title"):
            aspects["Release Title"] = [rec["album_title"]]
        if rec.get("label"):
            aspects["Record Label"] = [rec["label"]]
        if rec.get("year_pressed"):
            aspects["Release Year"] = [str(rec["year_pressed"])[:4]]
        item = {
            "availability": {"shipToLocationAvailability": {"quantity": 1}},
            "condition": EBAY_CONDITIONS.get(rec.get("condition_media") or "VG+", "USED_EXCELLENT"),
            "conditionDescription": listings.CONDITION_WORDS.get(rec.get("condition_media") or "VG+", ""),
            "product": {"title": listing["title"], "description": listing["description"],
                        "imageUrls": image_urls, "aspects": aspects},
        }
        resp = await client.put(f"{api}/sell/inventory/v1/inventory_item/{sku}", json=item)
        resp.raise_for_status()
        # 3. Offer (price + policies).
        offer = {
            "sku": sku,
            "marketplaceId": config.get("EBAY_MARKETPLACE_ID"),
            "format": "FIXED_PRICE",
            "availableQuantity": 1,
            "categoryId": config.get("EBAY_CATEGORY_ID"),
            "listingDescription": listing["description"].replace("\n", "<br>"),
            "listingPolicies": {
                "fulfillmentPolicyId": config.get("EBAY_FULFILLMENT_POLICY_ID"),
                "paymentPolicyId": config.get("EBAY_PAYMENT_POLICY_ID"),
                "returnPolicyId": config.get("EBAY_RETURN_POLICY_ID"),
            },
            "merchantLocationKey": config.get("EBAY_LOCATION_KEY"),
            "pricingSummary": {"price": {"value": f"{listing['price']:.2f}", "currency": listing["currency"]}},
        }
        resp = await client.post(f"{api}/sell/inventory/v1/offer", json=offer)
        resp.raise_for_status()
        offer_id = resp.json()["offerId"]
        # 4. Publish.
        resp = await client.post(f"{api}/sell/inventory/v1/offer/{offer_id}/publish")
        resp.raise_for_status()
        listing_id = resp.json().get("listingId")
    return {"status": "listed", "url": f"{site}/itm/{listing_id}", "message": f"Listed on eBay (item {listing_id})."}


API_PUBLISHERS = {"discogs": publish_discogs, "trademe": publish_trademe, "ebay": publish_ebay}


async def publish(rec: dict[str, Any], platform: str) -> dict[str, Any]:
    """Try the site's API. Falls back to 'ready' (Listing Helper) if not configured or it fails."""
    listing = await listings.build(rec, platform)
    fn = API_PUBLISHERS.get(platform)
    if fn is None:
        return {"status": "ready", "url": "", "automatic": False, "listing": listing,
                "message": f"Your {listing['name']} listing is ready to copy and paste."}
    try:
        res = await fn(rec, listing)
        return {**res, "automatic": True, "listing": listing}
    except NotConfigured as exc:
        return {"status": "ready", "url": "", "automatic": False, "listing": listing,
                "message": f"Ready to copy and paste. ({exc})"}
    except (httpx.HTTPError, RuntimeError, KeyError, ValueError) as exc:
        detail = exc.response.text[:300] if isinstance(exc, httpx.HTTPStatusError) else str(exc)
        log.warning("Publishing to %s failed: %s", platform, detail)
        return {"status": "ready", "url": "", "automatic": False, "listing": listing,
                "message": f"Couldn't post automatically, so it's ready to copy and paste instead. ({detail})"}


# --------------------------------------------------------------------------- Browser assistant
_playwright = None
_context = None

FIELD_SELECTORS = {
    "title": ['input[name*="title" i]', 'input[id*="title" i]', 'input[aria-label*="title" i]',
              'input[placeholder*="title" i]', 'label:has-text("Title") input'],
    "price": ['input[name*="price" i]', 'input[id*="price" i]', 'input[aria-label*="price" i]',
              'input[placeholder*="price" i]', 'label:has-text("Price") input'],
    "description": ['textarea[name*="desc" i]', 'textarea[id*="desc" i]', 'textarea[aria-label*="desc" i]',
                    'label:has-text("Description") textarea', 'textarea'],
}


async def _fill_first(page, selectors: list[str], value: str) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible():
                await loc.fill(value, timeout=3000)
                return True
        except Exception:  # noqa: BLE001 - every site is different; just try the next selector
            continue
    return False


async def browser_assist(rec: dict[str, Any], platform: str) -> dict[str, Any]:
    """Open a real browser window on the site's sell page and fill in what we can.

    The browser keeps its own profile folder, so Pete only has to log in to each site once.
    """
    global _playwright, _context
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"ok": False, "message": "The browser helper isn't installed. Run Install_PetesVinyl.bat again."}
    listing = await listings.build(rec, platform)
    try:
        if _context is None:
            _playwright = await async_playwright().start()
            BROWSER_PROFILE_DIR.mkdir(exist_ok=True)
            options = dict(headless=False, viewport=None, args=["--start-maximized"])
            found = browser.find_browser()
            try:   # the same Chrome Pete already uses; fall back to the bundled Chromium if that won't start
                _context = await _playwright.chromium.launch_persistent_context(
                    str(BROWSER_PROFILE_DIR), **({"channel": found.channel} if found else {}), **options)
            except Exception:  # noqa: BLE001
                _context = await _playwright.chromium.launch_persistent_context(str(BROWSER_PROFILE_DIR), **options)
        page = await _context.new_page()
        await page.goto(listing["sell_url"], wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(4000)
        filled = []
        if await _fill_first(page, FIELD_SELECTORS["title"], listing["title"]):
            filled.append("title")
        if await _fill_first(page, FIELD_SELECTORS["price"], f"{listing['price']:.0f}"):
            filled.append("price")
        if await _fill_first(page, FIELD_SELECTORS["description"], listing["description"]):
            filled.append("description")
        photos = [str(p) for p in image_paths(rec)]
        try:
            file_input = page.locator('input[type="file"]').first
            if photos and await file_input.count():
                await file_input.set_input_files(photos, timeout=5000)
                filled.append("photos")
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        _context = None
        return {"ok": False, "message": f"Couldn't open the browser helper: {exc}"}
    if filled:
        msg = f"I've opened {listing['name']} and filled in: {', '.join(filled)}. Check it over, then press Post."
    else:
        msg = (f"I've opened {listing['name']}. If it asks you to log in, do that once, then press "
               "'Fill it in for me' again. Or use the Copy buttons.")
    return {"ok": True, "filled": filled, "message": msg}


async def shutdown_browser() -> None:
    global _playwright, _context
    try:
        if _context is not None:
            await _context.close()
        if _playwright is not None:
            await _playwright.stop()
    except Exception:  # noqa: BLE001
        pass
    _context = _playwright = None
