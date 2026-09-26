"""
watchlist.py — Eldorado.gg price watchlist cog

Commands:
    /watchlist add link:<url>      Start tracking a listing
    /watchlist view                Show everything being tracked (first price vs current price)
    /watchlist remove link:<url>   Stop tracking a listing
    /instaeldopoll                 Force an immediate price check instead of waiting for the timer

Every 10 minutes (and whenever /instaeldopoll is run) each tracked link is re-fetched.
If the price changed since the last check, an alert is posted to ALERT_CHANNEL_ID.

--------------------------------------------------------------------------------
INTEGRATION
--------------------------------------------------------------------------------
1. Drop this file next to bot.py, config.py, database.py, etc.
2. Add to requirements.txt:
       aiohttp
3. Load it as an extension in bot.py, e.g. inside your setup_hook / on_ready
   (wherever you currently call bot.load_extension(...) for your other cogs):
       await bot.load_extension("watchlist")
4. Make sure your bot's slash commands get synced somewhere (bot.tree.sync()) —
   if you already do this for your other commands you don't need to add anything.

This ships with its own tiny SQLite database (watchlist.db, created automatically
next to this file) so it does NOT touch your existing database.py. If you'd rather
it use your existing DB layer, show me database.py and I'll wire it in instead.

--------------------------------------------------------------------------------
HOW PRICES ARE FETCHED
--------------------------------------------------------------------------------
Eldorado's listing pages render client-side (no price in the raw HTML), so instead
of scraping the page this calls the same internal API their frontend uses:
    https://www.eldorado.gg/api/v1/item-management/offers/{offer_id}?includeProduct=true
found via the browser's Network tab. This is faster and far more reliable than
HTML scraping would have been, but it's an undocumented private endpoint, so
Eldorado could change its shape or add auth requirements without notice. If a
link stops working, run debug_fetch.py's API mode (or re-check the Network tab)
to confirm the endpoint still returns the same JSON shape.
"""

import re
import json
import sqlite3
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import WATCHLIST_ALERT_CHANNEL_ID

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------

ALERT_CHANNEL_ID = WATCHLIST_ALERT_CHANNEL_ID
CHECK_INTERVAL_MINUTES = 10
DB_PATH = Path(__file__).parent / "watchlist.db"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ----------------------------------------------------------------------------
# Storage
# ----------------------------------------------------------------------------

def _init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            name TEXT,
            first_price REAL,
            last_price REAL,
            added_by INTEGER,
            added_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


async def db_add(url: str, name: str, price: float, added_by: int):
    def _run():
        conn = _db()
        conn.execute(
            "INSERT INTO watchlist (url, name, first_price, last_price, added_by, added_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (url, name, price, price, added_by, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()

    await asyncio.to_thread(_run)


async def db_remove(url: str) -> bool:
    def _run():
        conn = _db()
        cur = conn.execute("DELETE FROM watchlist WHERE url = ?", (url,))
        conn.commit()
        removed = cur.rowcount > 0
        conn.close()
        return removed

    return await asyncio.to_thread(_run)


async def db_all():
    def _run():
        conn = _db()
        rows = conn.execute("SELECT * FROM watchlist").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    return await asyncio.to_thread(_run)


async def db_update_price(url: str, new_price: float):
    def _run():
        conn = _db()
        conn.execute("UPDATE watchlist SET last_price = ? WHERE url = ?", (new_price, url))
        conn.commit()
        conn.close()

    await asyncio.to_thread(_run)


async def db_exists(url: str) -> bool:
    def _run():
        conn = _db()
        row = conn.execute("SELECT 1 FROM watchlist WHERE url = ?", (url,)).fetchone()
        conn.close()
        return row is not None

    return await asyncio.to_thread(_run)


# ----------------------------------------------------------------------------
# Fetching — Eldorado's own internal API, found via DevTools Network tab.
#
# A page like:
#   https://www.eldorado.gg/steal-a-brainrot-brainrots/oi/54fa8a06-4fe8-4e93-a907-08de80cf1bcf
# loads its data client-side from:
#   https://www.eldorado.gg/api/v1/item-management/offers/{offer_id}?includeProduct=true
# which returns clean JSON: offer.pricePerUnitInUSD.amount and offer.offerTitle.
# ----------------------------------------------------------------------------

class FetchError(Exception):
    pass


OFFER_ID_RE = re.compile(r"/oi/([0-9a-fA-F-]{36})")
API_URL_TEMPLATE = "https://www.eldorado.gg/api/v1/item-management/offers/{offer_id}?includeProduct=true"


async def fetch_listing(session: aiohttp.ClientSession, url: str):
    """Returns (price: float, name: str) for a given Eldorado listing URL,
    by calling Eldorado's internal offer API directly instead of scraping HTML."""
    match = OFFER_ID_RE.search(url)
    if not match:
        raise FetchError(
            "Couldn't find an offer ID in that link — make sure it's a direct "
            "listing URL containing '/oi/<id>', not a search/category page."
        )
    offer_id = match.group(1)
    api_url = API_URL_TEMPLATE.format(offer_id=offer_id)

    request_headers = {**HEADERS, "Accept": "application/json", "Referer": url}

    async with session.get(api_url, headers=request_headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
        if resp.status != 200:
            raise FetchError(f"HTTP {resp.status} from Eldorado's API for offer {offer_id}")
        try:
            data = await resp.json(content_type=None)
        except (aiohttp.ContentTypeError, json.JSONDecodeError) as e:
            raise FetchError(f"Unexpected (non-JSON) response from Eldorado's API: {e}")

    try:
        offer = data["offer"]
        price = float(offer["pricePerUnitInUSD"]["amount"])
        name = offer.get("offerTitle") or offer.get("description") or offer_id
    except (KeyError, TypeError, ValueError) as e:
        raise FetchError(f"Unexpected shape in Eldorado's API response: {e}")

    return price, name


# ----------------------------------------------------------------------------
# Cog
# ----------------------------------------------------------------------------

class Watchlist(commands.Cog):
    watchlist_group = app_commands.Group(name="watchlist", description="Track Eldorado.gg listing prices")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None
        _init_db()

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        self.price_check_loop.start()

    async def cog_unload(self):
        self.price_check_loop.cancel()
        if self.session:
            await self.session.close()

    def _alert_channel(self):
        return self.bot.get_channel(ALERT_CHANNEL_ID)

    async def check_all(self, *, manual: bool = False) -> int:
        """Checks every tracked link. Returns how many prices changed."""
        items = await db_all()
        changed = 0
        for item in items:
            try:
                price, _name = await fetch_listing(self.session, item["url"])
            except FetchError:
                continue

            if price != item["last_price"]:
                await db_update_price(item["url"], price)
                changed += 1
                await self._send_alert(item, price)

        return changed

    async def _send_alert(self, item: dict, new_price: float):
        channel = self._alert_channel()
        if channel is None:
            return

        old_price = item["last_price"]
        direction = "🔻 dropped" if new_price < old_price else "🔺 rose"
        embed = discord.Embed(
            title=f"{direction.split()[1].capitalize()} price alert",
            description=f"[{item['name']}]({item['url']})",
            color=discord.Color.green() if new_price < old_price else discord.Color.red(),
        )
        embed.add_field(name="First tracked at", value=f"${item['first_price']:.2f}", inline=True)
        embed.add_field(name="Previous price", value=f"${old_price:.2f}", inline=True)
        embed.add_field(name="New price", value=f"${new_price:.2f}", inline=True)
        await channel.send(content=f"{direction} for a tracked item!", embed=embed)

    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def price_check_loop(self):
        await self.check_all()

    @price_check_loop.before_loop
    async def before_price_check_loop(self):
        await self.bot.wait_until_ready()

    # -- /watchlist add ------------------------------------------------------
    @watchlist_group.command(name="add", description="Start tracking an Eldorado.gg listing link")
    @app_commands.describe(link="The Eldorado.gg listing URL to track")
    async def watchlist_add(self, interaction: discord.Interaction, link: str):
        await interaction.response.defer(thinking=True)

        if not link.startswith("https://www.eldorado.gg/"):
            await interaction.followup.send("That doesn't look like an Eldorado.gg link.")
            return

        if await db_exists(link):
            await interaction.followup.send("That link is already on the watchlist.")
            return

        try:
            price, name = await fetch_listing(self.session, link)
        except FetchError as e:
            await interaction.followup.send(f"Couldn't read a price from that link: {e}")
            return

        await db_add(link, name, price, interaction.user.id)
        await interaction.followup.send(f"Added **{name}** — tracking at **${price:.2f}**.")

    # -- /watchlist remove ----------------------------------------------------
    @watchlist_group.command(name="remove", description="Stop tracking an Eldorado.gg listing link")
    @app_commands.describe(link="The Eldorado.gg listing URL to remove")
    async def watchlist_remove(self, interaction: discord.Interaction, link: str):
        removed = await db_remove(link)
        if removed:
            await interaction.response.send_message(f"Removed {link} from the watchlist.")
        else:
            await interaction.response.send_message("That link wasn't on the watchlist.")

    # -- /watchlist view ------------------------------------------------------
    @watchlist_group.command(name="view", description="Show everything on the watchlist")
    async def watchlist_view(self, interaction: discord.Interaction):
        items = await db_all()
        if not items:
            await interaction.response.send_message("The watchlist is empty.")
            return

        embed = discord.Embed(title="Eldorado Price Watchlist", color=discord.Color.blurple())
        for item in items:
            delta = item["last_price"] - item["first_price"]
            arrow = "→" if delta == 0 else ("↓" if delta < 0 else "↑")
            embed.add_field(
                name=item["name"][:100],
                value=(
                    f"[Link]({item['url']})\n"
                    f"First: ${item['first_price']:.2f}  {arrow}  Now: ${item['last_price']:.2f}"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    # -- /instaeldopoll ---------------------------------------------------------
    @app_commands.command(name="instaeldopoll", description="Immediately re-check all watchlist prices")
    async def instaeldopoll(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        changed = await self.check_all(manual=True)
        if changed:
            await interaction.followup.send(f"Poll complete — {changed} item(s) changed price. Check the alerts channel.")
        else:
            await interaction.followup.send("Poll complete — no price changes.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Watchlist(bot))
