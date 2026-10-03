import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
from config import (
    EMBED_COLOR,
    PAYMENT_BRAINROTS,
    INACTIVITY_LOG_CHANNEL_ID,
    INACTIVITY_ADMIN_USER_IDS,
    INACTIVITY_THRESHOLD_HOURS,
    INACTIVITY_REPORT_INTERVAL_HOURS,
)

log = logging.getLogger(__name__)


def _brainrot_label(key: str, other_name: str) -> str:
    if key == "other":
        return other_name or "Other"
    return PAYMENT_BRAINROTS.get(key, {}).get("label", other_name or key)


def _to_unix(logged_at: str) -> int:
    """sqlite's datetime('now') gives 'YYYY-MM-DD HH:MM:SS' in UTC with no offset."""
    dt = datetime.datetime.strptime(logged_at, "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=datetime.timezone.utc
    )
    return int(dt.timestamp())


def _format_trade_line(trade: dict) -> str:
    """Builds the 'Gave Xx Y for Zx W.' / 'Paid $X for Zx W.' line, with a Discord
    relative timestamp, from a get_last_brainrot_trade() result."""
    received = trade["received"]
    received_label = _brainrot_label(received["key"], received["other_name"])
    ts = f"<t:{_to_unix(trade['logged_at'])}:R>"

    if trade["paid_brainrot"]:
        pb = trade["paid_brainrot"]
        gave = f"Gave {pb['quantity']}x {_brainrot_label(pb['key'], pb['other_name'])}"
    elif trade["paid_money"] is not None:
        gave = f"Paid ${trade['paid_money']:,.2f}"
    else:
        gave = "Received"

    return f"{gave} for {received['quantity']}x {received_label}. {ts}"


class Inactivity(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    inactivity_group = app_commands.Group(name="inactivity", description="Member inactivity tracking")

    async def cog_load(self):
        self.auto_report_loop.start()

    async def cog_unload(self):
        self.auto_report_loop.cancel()

    async def _build_report_embed(self):
        """Returns (embed, inactive_count). embed is None if nobody is currently
        inactive or the guild/channel can't be resolved (inactive_count is 0 then)."""
        channel = self.bot.get_channel(INACTIVITY_LOG_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(INACTIVITY_LOG_CHANNEL_ID)
            except discord.HTTPException:
                log.warning("Couldn't resolve inactivity log channel %s", INACTIVITY_LOG_CHANNEL_ID)
                return None, 0

        guild = getattr(channel, "guild", None)
        if guild is None:
            log.warning("Inactivity log channel %s has no guild", INACTIVITY_LOG_CHANNEL_ID)
            return None, 0

        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            hours=INACTIVITY_THRESHOLD_HOURS
        )

        lines = []
        count = 0
        async for member in guild.fetch_members(limit=None):
            if member.bot:
                continue

            trade = await db.get_last_brainrot_trade(member.id)
            if trade is not None:
                logged_dt = datetime.datetime.strptime(
                    trade["logged_at"], "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=datetime.timezone.utc)
                if logged_dt >= cutoff:
                    continue  # active — skip

            count += 1
            lines.append(f"**{count}. {member.display_name}**")
            lines.append(f"*{member.display_name}'s Last received brainrot:*")
            if trade is None:
                lines.append("No brainrot received on record yet.")
            else:
                lines.append(_format_trade_line(trade))
            lines.append("")  # blank line between members

        if count == 0:
            return None, 0

        embed = discord.Embed(
            title="Member Inactivity Notice!",
            description="\n".join(lines).strip(),
            color=EMBED_COLOR,
        )
        return embed, count

    async def _send_report(self) -> int:
        """Builds and sends the report. Returns the number of inactive members
        found (0 if the report was skipped — nobody inactive, or channel/guild
        couldn't be resolved)."""
        embed, count = await self._build_report_embed()
        if embed is None:
            return 0

        channel = self.bot.get_channel(INACTIVITY_LOG_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(INACTIVITY_LOG_CHANNEL_ID)
            except discord.HTTPException:
                return 0

        await channel.send(embed=embed)
        return count

    @tasks.loop(hours=INACTIVITY_REPORT_INTERVAL_HOURS)
    async def auto_report_loop(self):
        try:
            await self._send_report()
        except Exception:
            # Never let an unhandled error silently kill this loop (discord.py
            # stops a tasks.loop entirely after one uncaught exception).
            log.exception("auto_report_loop failed")

    @auto_report_loop.before_loop
    async def before_auto_report_loop(self):
        await self.bot.wait_until_ready()

    # ---------------- /inactivity database ----------------
    @inactivity_group.command(
        name="database",
        description="Immediately send the member inactivity report (restricted)",
    )
    async def inactivity_database(self, interaction: discord.Interaction):
        if interaction.user.id not in INACTIVITY_ADMIN_USER_IDS:
            await interaction.response.send_message(
                "You don't have permission to use this command.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        count = await self._send_report()

        if count == 0:
            await interaction.followup.send("No one is currently inactive — report not sent.")
        else:
            await interaction.followup.send(f"Report sent — {count} inactive member(s).")


async def setup(bot: commands.Bot):
    await bot.add_cog(Inactivity(bot))
