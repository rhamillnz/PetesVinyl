"""Settings: read from .env first, then overridden by anything saved in the app's Settings screen."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("PETESVINYL_DB", BASE_DIR / "vinyl_collection.db"))
IMAGES_DIR = Path(os.environ.get("PETESVINYL_IMAGES", BASE_DIR / "images"))
STATIC_DIR = BASE_DIR / "static"
LOGS_DIR = BASE_DIR / "logs"
BROWSER_PROFILE_DIR = BASE_DIR / "browser_profile"

# Every setting the app knows about, with its default. Keys marked secret are masked in the UI.
DEFAULTS: dict[str, str] = {
    # About Pete
    "SELLER_NAME": "Pete",
    "SELLER_LOCATION": "New Zealand",
    "HOME_CURRENCY": "NZD",
    "SHIPPING_NOTE": "Carefully packed in a proper record mailer. Happy to combine postage on multiple records.",
    # AI (OpenRouter)
    "OPENROUTER_API_KEY": "",
    "OPENROUTER_MODEL": "google/gemini-2.5-flash",
    "AI_WEB_SEARCH": "true",
    # Discogs
    "DISCOGS_API_TOKEN": "",
    "DISCOGS_LISTING_STATUS": "Draft",
    # TradeMe
    "TRADEME_CONSUMER_KEY": "",
    "TRADEME_CONSUMER_SECRET": "",
    "TRADEME_OAUTH_TOKEN": "",
    "TRADEME_OAUTH_TOKEN_SECRET": "",
    "TRADEME_SANDBOX": "true",
    "TRADEME_CATEGORY": "",
    "TRADEME_DURATION_DAYS": "7",
    # eBay
    "EBAY_OAUTH_TOKEN": "",
    "EBAY_SANDBOX": "true",
    "EBAY_MARKETPLACE_ID": "EBAY_US",
    "EBAY_CURRENCY": "USD",
    "EBAY_CATEGORY_ID": "176985",
    "EBAY_FULFILLMENT_POLICY_ID": "",
    "EBAY_PAYMENT_POLICY_ID": "",
    "EBAY_RETURN_POLICY_ID": "",
    "EBAY_LOCATION_KEY": "",
    # Popsike (past eBay auction results)
    "POPSIKE_ENABLED": "true",
    "POPSIKE_SEARCH_URL": "https://www.popsike.com/php/quicksearch.php?searchtext={query}",
    "POPSIKE_CONNECTED": "",
    # Which sites Pete uses at all
    "ENABLED_PLATFORMS": "trademe,discogs,ebay,facebook,gumtree",
    # Backup
    "BACKUP_FOLDER": "",
    "BACKUP_EVERY_HOURS": "6",
}

SECRET_KEYS = {
    "OPENROUTER_API_KEY",
    "DISCOGS_API_TOKEN",
    "TRADEME_CONSUMER_KEY",
    "TRADEME_CONSUMER_SECRET",
    "TRADEME_OAUTH_TOKEN",
    "TRADEME_OAUTH_TOKEN_SECRET",
    "EBAY_OAUTH_TOKEN",
}


def load_dotenv(path: Path = BASE_DIR / ".env") -> None:
    """Tiny .env reader so we don't need an extra dependency. Existing env vars win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_dotenv()


def get(key: str) -> str:
    """Look up a setting: saved-in-app value, then environment/.env, then default."""
    from . import db  # local import to avoid a cycle

    saved = db.get_setting(key)
    if saved not in (None, ""):
        return saved
    return os.environ.get(key, DEFAULTS.get(key, ""))


def get_bool(key: str) -> bool:
    return get(key).strip().lower() in {"1", "true", "yes", "on"}


def get_float(key: str, fallback: float) -> float:
    try:
        return float(get(key))
    except ValueError:
        return fallback


def all_settings(masked: bool = True) -> dict[str, str]:
    out = {}
    for key in DEFAULTS:
        value = get(key)
        if masked and key in SECRET_KEYS and value:
            value = "••••" + value[-4:]
        out[key] = value
    return out
