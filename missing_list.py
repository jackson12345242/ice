"""
missing_list.py — paginated "missing brainrots" tracker cog

Command:
    /missinglist    Show the missing list as a paginated embed. Items can be
                    marked received two ways:
                      - picking a name from the "Mark Received" dropdown (only
                        lists the current page's items), or
                      - clicking "Type It", typing a name in free text, and
                        confirming the closest match (uses difflib, stdlib,
                        no extra dependency) before anything is changed.
                    "Copy Full List" posts the ENTIRE still-missing list (not
                    just the current page) as a plain-text, monospaced code
                    block in a normal message (not an embed) so it's easy to
                    long-press/select and copy, especially on mobile. Visible
                    only to whoever clicked it.
                    "Search" lets you type a full or partial name, jumps the
                    embed straight to whichever page that item is on, and
                    marks it with a 👉 so it's easy to spot.

--------------------------------------------------------------------------------
INTEGRATION
--------------------------------------------------------------------------------
1. Drop this file next to bot.py, config.py, database.py, watchlist.py, etc.
2. Load it as an extension in bot.py by adding "missing_list" to INITIAL_COGS:
       INITIAL_COGS = ["wallet", "fund", "split", "payment", "help", "rules",
                        "inactivity", "watchlist", "missing_list"]
3. Nothing else to install — this only uses discord.py, which you already have.

This ships with its own tiny SQLite database (missing_list.db, created next to
this file, or on your Railway volume if RAILWAY_VOLUME_MOUNT_PATH is set — same
pattern as watchlist.py) so it does NOT touch your existing database.py.

Each server (guild) gets the full list seeded the first time /missinglist is run
there. If you ever update MISSING_LIST_ITEMS below, newly added names will get
seeded in automatically next time /missinglist runs; renaming/removing names
won't retroactively touch rows already in the DB.

Marking an item received also posts a short log line to FUND_LOG_CHANNEL_ID
(from config.py), matching the logging pattern the rest of your bot uses. If
you don't want that, delete the `_log_received(...)` call in `mark_received`.
"""

import os
import sqlite3
import asyncio
import difflib
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from config import FUND_LOG_CHANNEL_ID

# ----------------------------------------------------------------------------
# The full list, in the order you gave it. This is the order items are shown in.
# ----------------------------------------------------------------------------
MISSING_LIST_ITEMS = [
    "Tartaragno", "Boneca Ambalabu", "Cacto Hipopotamo", "Pinealotto Fruttarino",
    "Bambini Crostini", "Brri Brri Bicus Dicus Bombicus", "Ti Ti Ti Sahur",
    "Frogato Pirato", "Salamino Penguino", "Burbaloni Loliloli", "Chimpanzini Bananini",
    "Chef Crabracadabra", "Lionel Cactuseli", "Pipi Potato", "Strawberrelli Flamingelli",
    "Puffaball", "Buho de Fuego", "Orangutini Ananassini", "Rhino Toasterino",
    "Bombardiro Crocodilo", "Te Te Te Sahur", "Carloo", "Carrotini Brainini",
    "Toiletto Focaccino", "Jacko Spaventosa", "Frostino Vampiro", "Gattatino Nyanino",
    "Chihuanini Taconini", "Matteo", "Los Crocodillitos", "Espresso Signora",
    "Tipi Topi Taco", "Alessio", "Orcalero Orcala", "Urubini Flamenguini",
    "Capi Taco", "Gattito Tacoto", "Trippi Troppi Troppa Trippa", "Las Capuchinas",
    "Pineaplino", "Ballerino Lololo", "Bulbito Bandito Traktorito",
    "Los Tungtungtungcitos", "Los Bombinitos", "Bombardini Tortinii",
    "Pakrahmatmatina", "Tractoro Dinosauro", "Los Orcalitos", "Orcalita Orcala",
    "Corn Corn Corn Sahur", "Squalanana", "Lazy Ducky", "Granchiello Spiritell",
    "Tootini Shrimpini", "Los Tipi Tacos", "Frio Ninja", "Lumaca Malefica",
    "Los Gattitos", "Mastodontico Telepiedone", "Chrismasmamat", "Belula Beluga",
    "Krupuk Pagi Pagi", "Cocoa Assassino", "Tentacolo Tecnico", "Pandanini Frostini",
    "Eggdin Egg Egg Dun", "Robo Grafito", "Tenini Ballini", "Los Matteos",
    "Karkerkar Kurkur", "La Vacca Saturno Saturnita", "Bisonte Giuppitere",
    "Dul Dul Dul", "Blackhole Goat", "Chachechi", "Los Spyderinis", "La Cucaracha",
    "Los Tortus", "Los Tralaleritos", "Boatito Auratito", "Guerriro Digitale",
    "Yess my Resume", "Las Tralaleritas", "Job Job Job Sahur", "Los Karkeritos",
    "Las Vaquitas Saturnitas", "Ranito Pepito", "1x1x1x1", "Los Cucarachas",
    "Craburger", "Berryno", "Los Jobcitos", "Ski Ski Skunki", "Nooo My Hotspot",
    "Pin Pin Pengu", "Santa Hotspot", "Rexino Ramino", "Rockarino Rockara",
    "Quesadilla Crocodila", "Qamar Camelamp", "Chicleteira Bicicleteira",
    "Marino Submarino", "Burrito Bandito", "Chill Puppy", "Los Quesadillas",
    "Flipa Sandala", "Arcadopus", "Gub", "Los Nooo My Hotspotsitos",
    "Noo my Present", "Rang Ring Bus", "Los Mi Gatitos", "Strawberrita",
    "Los Chicleteiras", "Sir Mangus", "Zebrino Pianino", "67", "John Doe",
    "Donkeyturbo Express", "Los Burritos", "Los 25", "La Grande Combinasion",
    "Mariachi Corazoni", "Swag Soda", "Chimnino", "Los Combinasionas", "Bananito",
    "Nuclearo Dinossauro", "Los 67", "Noodle Noodle Poodle", "Tralaledon",
    "Lavamanta", "Globa Steppa", "Los Puggies", "Los Mariachis", "Los Primos",
    "Eviledon", "Noo my Examen", "Noo my Resume", "Abyssaloco", "Coco and Mango",
    "Ketupat Kepat", "Tictac Sahur", "Orcaledon", "Ketchuru and Musturu",
    "Rico Dinero", "Garama and Madundung", "Lionello Casarello", "Grabatron",
    "Spaghetti Tualetti", "Ventoliero Pavonero", "Guest 666", "Sammyni Fattini",
    "Rubrikiko", "La Ginger Sekolah", "Cangurato Gelato", "Sammyni Spookyni",
    "Yetimatic", "La Food Combinasion", "Cash or Card", "Los Sekolahs",
    "Draculino", "Pizza and Ranch", "Los Amigos", "Reinito Sleighito",
    "Burguro And Fryuro", "Hydra Serpent", "Capitano Moby", "Celestial Pegasus",
    "Dragon Cannelloni", "Plant Bros", "Phoenix",
]

PAGE_SIZE = 20  # also the max dropdown options per page (Discord's select cap is 25)

DATA_DIR = Path(os.getenv("RAILWAY_VOLUME_MOUNT_PATH", str(Path(__file__).parent)))
DB_PATH = DATA_DIR / "missing_list.db"


# ----------------------------------------------------------------------------
# Storage
# ----------------------------------------------------------------------------

def _init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS missing_items (
            guild_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'missing',
            received_by INTEGER,
            received_at TEXT,
            PRIMARY KEY (guild_id, item_name)
        )
        """
    )
    conn.commit()
    conn.close()


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


async def db_seed_if_needed(guild_id: int):
    def _run():
        conn = _db()
        existing = {
            r["item_name"]
            for r in conn.execute(
                "SELECT item_name FROM missing_items WHERE guild_id = ?", (guild_id,)
            ).fetchall()
        }
        new_rows = [
            (guild_id, name, "missing", None, None)
            for name in MISSING_LIST_ITEMS
            if name not in existing
        ]
        if new_rows:
            conn.executemany(
                "INSERT INTO missing_items (guild_id, item_name, status, received_by, received_at) "
                "VALUES (?, ?, ?, ?, ?)",
                new_rows,
            )
            conn.commit()
        conn.close()

    await asyncio.to_thread(_run)


async def db_get_missing(guild_id: int) -> list[str]:
    def _run():
        conn = _db()
        rows = conn.execute(
            "SELECT item_name FROM missing_items WHERE guild_id = ? AND status = 'missing'",
            (guild_id,),
        ).fetchall()
        conn.close()
        return {r["item_name"] for r in rows}

    still_missing = await asyncio.to_thread(_run)
    # Keep the original, stable display order rather than DB/insert order.
    return [name for name in MISSING_LIST_ITEMS if name in still_missing]


async def db_mark_received(guild_id: int, item_name: str, user_id: int) -> bool:
    def _run():
        conn = _db()
        cur = conn.execute(
            "UPDATE missing_items SET status = 'received', received_by = ?, received_at = ? "
            "WHERE guild_id = ? AND item_name = ? AND status = 'missing'",
            (user_id, datetime.now(timezone.utc).isoformat(), guild_id, item_name),
        )
        conn.commit()
        updated = cur.rowcount > 0
        conn.close()
        return updated

    return await asyncio.to_thread(_run)


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------

def _build_embed(
    missing: list[str], page: int, total_pages: int, highlight: str | None = None
) -> discord.Embed:
    start = page * PAGE_SIZE
    page_items = missing[start : start + PAGE_SIZE]

    embed = discord.Embed(
        title="Missing Brainrots",
        color=discord.Color.blurple(),
    )
    if page_items:
        lines = []
        for i, name in enumerate(page_items):
            marker = "👉 " if name == highlight else "   "
            lines.append(f"{marker}{start + i + 1}. {name}")
        embed.description = "```\n" + "\n".join(lines) + "\n```"
    else:
        embed.description = "Nothing missing — everything's been received! 🎉"

    embed.set_footer(
        text=f"Page {page + 1}/{max(total_pages, 1)} • {len(missing)} still missing"
    )
    return embed


# Plain messages (not embeds) are what's actually easy to long-press/select and
# copy on mobile Discord. Discord caps message content at 2000 characters; leave
# headroom for the ``` fences so a single chunk never gets rejected as too long.
_COPY_CHUNK_CHAR_LIMIT = 1900


def _build_copy_chunks(missing: list[str]) -> list[str]:
    """Splits the full missing list into one or more code-block strings, each
    comfortably under the embed description limit, without cutting a line in half."""
    if not missing:
        return []

    lines = [f"{i + 1}. {name}" for i, name in enumerate(missing)]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        # +1 for the newline that will join this line to the chunk
        if current and current_len + len(line) + 1 > _COPY_CHUNK_CHAR_LIMIT:
            chunks.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


class MissingListView(discord.ui.View):
    def __init__(self, cog: "MissingList", guild_id: int, page: int, missing: list[str]):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.page = page
        self.missing = missing
        self.total_pages = max((len(missing) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
        self.message: discord.Message | None = None  # set by the command after sending
        self.highlight: str | None = None  # name to mark with 👉 on its page, if any
        self._build_items()

    def _build_items(self):
        self.clear_items()

        prev_button = discord.ui.Button(
            label="◀ Previous", style=discord.ButtonStyle.secondary, disabled=self.page <= 0
        )
        prev_button.callback = self.go_previous
        self.add_item(prev_button)

        next_button = discord.ui.Button(
            label="Next ▶",
            style=discord.ButtonStyle.secondary,
            disabled=self.page >= self.total_pages - 1,
        )
        next_button.callback = self.go_next
        self.add_item(next_button)

        type_button = discord.ui.Button(label="⌨️ Type It", style=discord.ButtonStyle.primary)
        type_button.callback = self.open_type_modal
        self.add_item(type_button)

        copy_button = discord.ui.Button(label="📋 Copy Full List", style=discord.ButtonStyle.secondary)
        copy_button.callback = self.copy_full_list
        self.add_item(copy_button)

        search_button = discord.ui.Button(label="🔍 Search", style=discord.ButtonStyle.primary)
        search_button.callback = self.open_search_modal
        self.add_item(search_button)

        start = self.page * PAGE_SIZE
        page_items = self.missing[start : start + PAGE_SIZE]
        if page_items:
            select = discord.ui.Select(
                placeholder="Mark Received ⬇",
                options=[
                    discord.SelectOption(label=name[:100], value=name) for name in page_items
                ],
            )
            select.callback = self.mark_received
            self.add_item(select)

    async def _refresh(self, interaction: discord.Interaction):
        self.missing = await db_get_missing(self.guild_id)
        self.total_pages = max((len(self.missing) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
        self.page = max(0, min(self.page, self.total_pages - 1))
        self._build_items()
        embed = _build_embed(self.missing, self.page, self.total_pages, self.highlight)
        await interaction.response.edit_message(embed=embed, view=self)

    async def refresh_message_external(self):
        """Re-render the original /missinglist message from an interaction that
        isn't attached to it (e.g. a confirmation or search result from a modal)."""
        if self.message is None:
            return
        self.missing = await db_get_missing(self.guild_id)
        self.total_pages = max((len(self.missing) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
        self.page = max(0, min(self.page, self.total_pages - 1))
        self._build_items()
        embed = _build_embed(self.missing, self.page, self.total_pages, self.highlight)
        try:
            await self.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass

    async def go_previous(self, interaction: discord.Interaction):
        self.highlight = None
        self.page = max(0, self.page - 1)
        await self._refresh(interaction)

    async def go_next(self, interaction: discord.Interaction):
        self.highlight = None
        self.page = min(self.total_pages - 1, self.page + 1)
        await self._refresh(interaction)

    async def mark_received(self, interaction: discord.Interaction):
        self.highlight = None
        select = interaction.data.get("values", [])
        if not select:
            await self._refresh(interaction)
            return
        item_name = select[0]
        updated = await db_mark_received(self.guild_id, item_name, interaction.user.id)
        if updated:
            await self.cog.log_received(interaction, item_name)
        await self._refresh(interaction)

    async def open_type_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TypeReceivedModal(self))

    async def open_search_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SearchModal(self))

    async def copy_full_list(self, interaction: discord.Interaction):
        missing = await db_get_missing(self.guild_id)
        chunks = _build_copy_chunks(missing)

        if not chunks:
            await interaction.response.send_message(
                "Nothing is missing anymore — the list is empty!", ephemeral=True
            )
            return

        # Plain message content (not an embed) so it's trivially selectable/copyable,
        # including on mobile, where text inside embeds is often hard to select.
        header = f"**Full Missing List ({len(missing)} items)**"
        if len(chunks) > 1:
            header += f" — part 1/{len(chunks)}"
        await interaction.response.send_message(
            content=f"{header}\n```\n{chunks[0]}\n```", ephemeral=True
        )

        for i, chunk in enumerate(chunks[1:], start=2):
            part_header = f"**Full Missing List** — part {i}/{len(chunks)}"
            await interaction.followup.send(
                content=f"{part_header}\n```\n{chunk}\n```", ephemeral=True
            )


class TypeReceivedModal(discord.ui.Modal, title="Mark Received"):
    def __init__(self, parent_view: MissingListView):
        super().__init__()
        self.parent_view = parent_view
        self.name_input = discord.ui.TextInput(
            label="Brainrot name",
            placeholder="Type the name, even if you're not 100% sure of spelling...",
            required=True,
            max_length=100,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        typed = self.name_input.value.strip()
        missing = await db_get_missing(self.parent_view.guild_id)
        if not missing:
            await interaction.response.send_message(
                "Nothing is missing anymore — the list is empty!", ephemeral=True
            )
            return

        match = difflib.get_close_matches(typed, missing, n=1, cutoff=0.0)
        best = match[0] if match else missing[0]

        embed = discord.Embed(
            title="Confirm Match",
            description=(
                f"The brainrot you are marking received is this:\n\n**{best}**\n\n"
                f"Confirm if this is right!"
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"You typed: {typed}")
        await interaction.response.send_message(
            embed=embed, view=ConfirmReceivedView(self.parent_view, best), ephemeral=True
        )


class SearchModal(discord.ui.Modal, title="Search Missing List"):
    def __init__(self, parent_view: MissingListView):
        super().__init__()
        self.parent_view = parent_view
        self.query_input = discord.ui.TextInput(
            label="Brainrot name",
            placeholder="Type all or part of a name...",
            required=True,
            max_length=100,
        )
        self.add_item(self.query_input)

    async def on_submit(self, interaction: discord.Interaction):
        query = self.query_input.value.strip()
        missing = await db_get_missing(self.parent_view.guild_id)
        if not missing:
            await interaction.response.send_message(
                "Nothing is missing anymore — the list is empty!", ephemeral=True
            )
            return

        # Prefer a plain substring match (handles partial names cleanly); fall
        # back to fuzzy matching for typos, same approach as "Type It".
        lowered = query.lower()
        substring_matches = [name for name in missing if lowered in name.lower()]
        if substring_matches:
            best = substring_matches[0]
        else:
            close = difflib.get_close_matches(query, missing, n=1, cutoff=0.0)
            best = close[0] if close else missing[0]

        index = missing.index(best)
        page = index // PAGE_SIZE

        self.parent_view.page = page
        self.parent_view.highlight = best
        await self.parent_view.refresh_message_external()

        await interaction.response.send_message(
            f"Found **{best}** — jumped to page {page + 1}.", ephemeral=True
        )


class ConfirmReceivedView(discord.ui.View):
    def __init__(self, parent_view: MissingListView, item_name: str):
        super().__init__(timeout=60)
        self.parent_view = parent_view
        self.item_name = item_name

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        updated = await db_mark_received(
            self.parent_view.guild_id, self.item_name, interaction.user.id
        )
        if updated:
            await self.parent_view.cog.log_received(interaction, self.item_name)
            self.parent_view.highlight = None
            await interaction.response.edit_message(
                content=f"Marked **{self.item_name}** as received.", embed=None, view=None
            )
            await self.parent_view.refresh_message_external()
        else:
            await interaction.response.edit_message(
                content=(
                    f"**{self.item_name}** was already marked received (maybe by someone else "
                    f"just now) — nothing changed."
                ),
                embed=None,
                view=None,
            )

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="Cancelled — nothing was marked received.", embed=None, view=None
        )


# ----------------------------------------------------------------------------
# Cog
# ----------------------------------------------------------------------------

class MissingList(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _init_db()

    async def log_received(self, interaction: discord.Interaction, item_name: str):
        channel = self.bot.get_channel(FUND_LOG_CHANNEL_ID)
        if channel is None:
            return
        try:
            await channel.send(
                f"✅ **{item_name}** marked received by {interaction.user.mention}"
            )
        except discord.HTTPException:
            pass

    @app_commands.command(
        name="missinglist", description="View and update the missing brainrots list"
    )
    async def missinglist(self, interaction: discord.Interaction):
        await db_seed_if_needed(interaction.guild_id)
        missing = await db_get_missing(interaction.guild_id)
        total_pages = max((len(missing) + PAGE_SIZE - 1) // PAGE_SIZE, 1)

        view = MissingListView(self, interaction.guild_id, 0, missing)
        embed = _build_embed(missing, 0, total_pages)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(MissingList(bot))
