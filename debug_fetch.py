"""
debug_fetch.py — run this locally to see why watchlist.py couldn't find a price.

Usage:
    python debug_fetch.py "https://www.eldorado.gg/steal-a-brainrot-brainrots/oi/54fa8a06-4fe8-4e93-a907-08de80cf1bcf"

It fetches the page the same way watchlist.py does, saves the raw HTML to
debug_page.html (so you can open it in a text editor / browser dev tools),
and prints a summary of what each extraction strategy found.
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

PRICE_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{1,2})?)")


async def main(url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            status = resp.status
            html = await resp.text()

    with open("debug_page.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTTP status: {status}")
    print(f"HTML length: {len(html)} chars (saved to debug_page.html)")
    print()

    # Does it even look like a real page, or a block/captcha/redirect?
    lower = html.lower()
    for marker in ("captcha", "access denied", "cloudflare", "just a moment", "enable javascript"):
        if marker in lower:
            print(f"⚠️  Found suspicious marker in HTML: '{marker}' — page may be blocked/JS-gated.")

    print()
    print("--- Strategy 1: window.__NUXT__ / __NEXT_DATA__ ---")
    found_any_state = False
    for pattern in (r"window\.__NUXT__\s*=\s*(\{.*?\});?\s*</script>",
                    r"<script[^>]*id=\"__NEXT_DATA__\"[^>]*>(\{.*?\})</script>"):
        m = re.search(pattern, html, re.DOTALL)
        if m:
            found_any_state = True
            print(f"  Matched pattern: {pattern[:40]}...  (blob length: {len(m.group(1))})")
            try:
                json.loads(m.group(1))
                print("  -> Parsed as valid JSON.")
            except Exception as e:
                print(f"  -> JSON parse FAILED: {e}")
    if not found_any_state:
        print("  No __NUXT__ or __NEXT_DATA__ blob found in the HTML at all.")

    print()
    print("--- Strategy 2: meta price tags ---")
    m = re.search(r'(?:property|name)="(?:og:price:amount|product:price:amount)"\s+content="([\d.,]+)"', html)
    print(f"  og:price:amount / product:price:amount: {m.group(1) if m else 'NOT FOUND'}")
    m = re.search(r'(?:property|name)="og:title"\s+content="([^"]+)"', html)
    print(f"  og:title: {m.group(1) if m else 'NOT FOUND'}")

    print()
    print("--- Strategy 3: raw $ price regex scan ---")
    prices = PRICE_RE.findall(html)
    print(f"  Found {len(prices)} dollar-amount matches.")
    if prices:
        print(f"  First 10: {prices[:10]}")

    print()
    print("--- <title> tag ---")
    m = re.search(r"<title>([^<]+)</title>", html)
    print(f"  {m.group(1) if m else 'NOT FOUND'}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python debug_fetch.py <eldorado_url>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
