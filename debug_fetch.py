"""
debug_fetch.py — run this locally to check whether watchlist.py's price fetch
still works for a given Eldorado listing link.

Usage:
    python debug_fetch.py "https://www.eldorado.gg/steal-a-brainrot-brainrots/oi/<id>"

It extracts the offer ID from the link, calls Eldorado's internal offer API
the same way watchlist.py does, and prints what it got back.
"""

import re
import sys
import json
import asyncio

import aiohttp

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

OFFER_ID_RE = re.compile(r"/oi/([0-9a-fA-F-]{36})")
API_URL_TEMPLATE = "https://www.eldorado.gg/api/v1/item-management/offers/{offer_id}?includeProduct=true"


async def main(url: str):
    match = OFFER_ID_RE.search(url)
    if not match:
        print("Couldn't find an offer ID ('/oi/<id>') in that URL.")
        return
    offer_id = match.group(1)
    api_url = API_URL_TEMPLATE.format(offer_id=offer_id)
    print(f"Offer ID: {offer_id}")
    print(f"Calling:  {api_url}")
    print()

    headers = {**HEADERS, "Accept": "application/json", "Referer": url}

    async with aiohttp.ClientSession() as session:
        async with session.get(api_url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            status = resp.status
            text = await resp.text()

    print(f"HTTP status: {status}")

    with open("debug_response.json", "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Raw response saved to debug_response.json ({len(text)} chars)")
    print()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"Response was not valid JSON: {e}")
        return

    try:
        offer = data["offer"]
        price = offer["pricePerUnitInUSD"]["amount"]
        name = offer.get("offerTitle")
        print(f"Parsed name:  {name}")
        print(f"Parsed price: ${price}")
    except (KeyError, TypeError) as e:
        print(f"JSON came back but not in the expected shape (missing {e}).")
        print("Top-level keys found:", list(data.keys()) if isinstance(data, dict) else type(data))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python debug_fetch.py <eldorado_offer_url>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
