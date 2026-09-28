"""OpenRouter AI helpers: read record photos and research prices on the web.

OpenRouter gives one API key for many models. Pete tops up a few dollars of credit and
the app spends a cent or two per record. Web search uses OpenRouter's "web" plugin.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from . import config

log = logging.getLogger("petesvinyl.ai")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class AIUnavailable(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(config.get("OPENROUTER_API_KEY"))


def _image_part(path: Path) -> dict[str, Any]:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}}


def extract_json(text: str) -> dict[str, Any]:
    """Models sometimes wrap JSON in prose or code fences; dig the object out."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("AI reply did not contain JSON")
    return json.loads(text[start : end + 1])


async def chat_json(content: list[dict[str, Any]], web_search: bool = False, max_tokens: int = 1500) -> dict[str, Any]:
    key = config.get("OPENROUTER_API_KEY")
    if not key:
        raise AIUnavailable("No OpenRouter API key set. Add one in Settings.")
    body: dict[str, Any] = {
        "model": config.get("OPENROUTER_MODEL"),
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    if web_search and config.get_bool("AI_WEB_SEARCH"):
        body["plugins"] = [{"id": "web", "max_results": 5}]
    headers = {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "PetesVinyl",
    }
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(OPENROUTER_URL, json=body, headers=headers)
    if resp.status_code == 402:
        raise AIUnavailable("The OpenRouter account has run out of credit. Top it up at openrouter.ai.")
    if resp.status_code >= 400:
        raise AIUnavailable(f"OpenRouter error {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError) as exc:
        raise AIUnavailable(f"Unexpected OpenRouter reply: {str(data)[:300]}") from exc
    return extract_json(text)


IDENTIFY_PROMPT = """You are an expert vinyl record appraiser helping an elderly collector in {location} catalogue his records.
Look at these photos of ONE record ({which}). Identify the exact release and pressing.
Use the web to check Discogs if you can: match catalogue numbers, label design, barcode, matrix/runout
etchings and small print (e.g. "Made in England", "Manufactured by ... NZ") to find the specific pressing.

Reply with ONLY a JSON object, no other text:
{{
  "artist": "",
  "album_title": "",
  "year_pressed": "year THIS copy was pressed (may differ from original release), e.g. 1978",
  "original_year": "year the album was first released",
  "pressing_location": "country (and plant if known) where THIS copy was pressed, e.g. New Zealand (EMI Lower Hutt)",
  "label": "",
  "catalog_number": "",
  "barcode": "digits only, or empty",
  "matrix_numbers": "",
  "is_reissue": false,
  "discogs_release_id": "numeric Discogs release id if you are confident, else empty",
  "confidence": "high | medium | low",
  "explanation": "2-3 short, friendly sentences for Pete explaining how you worked out the pressing and anything he should double-check"
}}"""


async def identify_record(images: dict[str, Path]) -> dict[str, Any]:
    names = {"front": "front cover", "back": "back cover", "disc_a": "label side A", "disc_b": "label side B"}
    parts: list[dict[str, Any]] = []
    shown = []
    for slot in ("front", "back", "disc_a", "disc_b"):
        path = images.get(slot)
        if path and path.exists():
            parts.append(_image_part(path))
            shown.append(names[slot])
    if not parts:
        raise AIUnavailable("No photos to look at yet.")
    prompt = IDENTIFY_PROMPT.format(location=config.get("SELLER_LOCATION"), which=", ".join(shown))
    return await chat_json([{"type": "text", "text": prompt}, *parts], web_search=True)


VALUE_PROMPT = """You are a vinyl record valuer. Research what this exact pressing actually SELLS for.
Search recent SOLD prices (eBay sold listings, Discogs sales history/median, Popsike) - not asking prices.

Record: {artist} - {album_title}
Pressed: {year_pressed} in {pressing_location}
Label / catalogue number: {label} {catalog_number}
Discogs release id: {discogs_release_id}
Condition: record {condition_media}, sleeve {condition_sleeve} (Goldmine grading)

Reply with ONLY a JSON object:
{{
  "ebay_sold_prices": [{{"price": 0.0, "currency": "USD", "where": "eBay US"}}],
  "discogs_median": {{"price": 0.0, "currency": "USD"}},
  "typical_price": {{"price": 0.0, "currency": "{home}"}},
  "demand": "high | medium | low",
  "reasoning": "2 short plain-English sentences for a 70 year old seller"
}}
Use 0 or empty lists where you found nothing. typical_price is what THIS copy in THIS condition should realistically sell for, in {home}."""


async def research_value(record: dict[str, Any]) -> dict[str, Any]:
    fields = {k: record.get(k) or "unknown" for k in (
        "artist", "album_title", "year_pressed", "pressing_location", "label",
        "catalog_number", "discogs_release_id", "condition_media", "condition_sleeve",
    )}
    prompt = VALUE_PROMPT.format(home=config.get("HOME_CURRENCY"), **fields)
    return await chat_json([{"type": "text", "text": prompt}], web_search=True, max_tokens=1200)
