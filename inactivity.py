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

    @staticmethod
    def _member_block(count: int, member: discord.Member, trade: dict) -> list:
        lines = [f"**{count}. {member.display_name}**", f"*{member.display_name}'s Last received brainrot:*"]
        if trade is None:
            lines.append("No brainrot received on record yet.")
        else:
            lines.append(_format_trade_line(trade))
        lines.append("")  # blank line between members
        return lines

    async def _build_report_embeds(self):
        """Returns (inactive_embed, active_embed, inactive_count, active_count).
        Both embeds are None if the guild/channel can't be resolved."""
        channel = self.bot.get_channel(INACTIVITY_LOG_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(INACTIVITY_LOG_CHANNEL_ID)
            except discord.HTTPException:
                log.warning("Couldn't resolve inactivity log channel %s", INACTIVITY_LOG_CHANNEL_ID)
                return None, None, 0, 0

        guild = getattr(channel, "guild", None)
        if guild is None:
            log.warning("Inactivity log channel %s has no guild", INACTIVITY_LOG_CHANNEL_ID)
            return None, None, 0, 0

        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            hours=INACTIVITY_THRESHOLD_HOURS
        )

        inactive_lines, active_lines = [], []
        inactive_count, active_count = 0, 0

        async for member in guild.fetch_members(limit=None):
            if member.bot:
                continue

            trade = await db.get_last_brainrot_trade(member.id)
            is_active = False
            if trade is not None:
                logged_dt = datetime.datetime.strptime(
                    trade["logged_at"], "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=datetime.timezone.utc)
                is_active = logged_dt >= cutoff

            if is_active:
                active_count += 1
                active_lines.extend(self._member_block(active_count, member, trade))
            else:
                inactive_count += 1
                inactive_lines.extend(self._member_block(inactive_count, member, trade))

        inactive_embed = discord.Embed(
            title="Member Inactivity Notice!",
            description=(
                "\n".join(inactive_lines).strip()
                if inactive_count
                else f"Everyone has paid for something within the last {INACTIVITY_THRESHOLD_HOURS} hours! 🎉"
            ),
            color=EMBED_COLOR,
        )
        active_embed = discord.Embed(
            title="✅ Active Members",
            description=(
                "\n".join(active_lines).strip()
                if active_count
                else "No one's currently active."
            ),
            color=EMBED_COLOR,
        )
        return inactive_embed, active_embed, inactive_count, active_count

    async def _send_report(self):
        """Builds and sends the report (inactive + active sections as one message).
        Returns (inactive_count, active_count) — both 0 if the channel/guild
        couldn't be resolved and nothing was sent."""
        inactive_embed, active_embed, inactive_count, active_count = await self._build_report_embeds()
        if inactive_embed is None:
            return 0, 0

        channel = self.bot.get_channel(INACTIVITY_LOG_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(INACTIVITY_LOG_CHANNEL_ID)
            except discord.HTTPException:
                return 0, 0

        await channel.send(embeds=[inactive_embed, active_embed])
        return inactive_count, active_count

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

        try:
            inactive_count, active_count = await self._send_report()
        except Exception:
            log.exception("Manual /inactivity database failed")
            await interaction.followup.send(
                "Something went wrong building the report — check the bot's logs. "
                "(Common cause: the Members intent isn't enabled in the running deployment.)"
            )
            return

        if inactive_count == 0 and active_count == 0:
            await interaction.followup.send(
                "Couldn't find any members to check — see the bot's logs."
            )
        else:
            await interaction.followup.send(
                f"Report sent — {inactive_count} inactive, {active_count} active."
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Inactivity(bot))
