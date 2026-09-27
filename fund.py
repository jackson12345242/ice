import os

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from config import BRAINROTS, EMBED_COLOR, FUND_LOG_CHANNEL_ID, FUND_ADMIN_USER_ID

# Shared choice list for every command that needs a brainrot dropdown
BRAINROT_CHOICES = [
    app_commands.Choice(name=info["label"], value=key) for key, info in BRAINROTS.items()
]


def asset_file(key: str) -> discord.File:
    path = BRAINROTS[key]["asset"]
    return discord.File(path, filename=os.path.basename(path))


class Fund(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    fund_group = app_commands.Group(name="fund", description="Track the shared fund")
    remove_group = app_commands.Group(name="remove", description="Remove things from the fund")

    # ---------------- /fund add ----------------
    @fund_group.command(name="add", description="Add brainrots and/or money to the fund")
    @app_commands.describe(
        amount="How many of the brainrot to add (defaults to 1 if brainrot is picked)",
        brainrot="Which brainrot to add (optional)",
        money="How much money to add to the fund (optional)",
        user="Who actually gave this? Defaults to you if left blank.",
    )
    @app_commands.choices(brainrot=BRAINROT_CHOICES)
    async def fund_add(
        self,
        interaction: discord.Interaction,
        amount: int = None,
        brainrot: app_commands.Choice[str] = None,
        money: float = None,
        user: discord.Member = None,
    ):
        if brainrot is None and money is None:
            await interaction.response.send_message(
                "Give me at least a `brainrot` or a `money` amount to add.",
                ephemeral=True,
            )
            return

        contributor = user or interaction.user
        added_lines = []

        if brainrot is not None:
            qty = amount if amount is not None else 1
            await db.add_brainrot(brainrot.value, qty)
            await db.add_contribution("brainrot", brainrot.value, contributor.id, qty)
            added_lines.append(f"**{qty}x {brainrot.name}**")

        if money is not None:
            await db.add_money(money)
            await db.add_contribution("money", None, contributor.id, money)
            added_lines.append(f"**${money:,.2f}**")

        summary = " and ".join(added_lines)
        from_note = f" (from {contributor.mention})" if contributor.id != interaction.user.id else ""
        await interaction.response.send_message(
            f"Added {summary} to the fund{from_note}.", ephemeral=True
        )

        await self._log(interaction.user, f"➕ Added {summary} to the fund — given by {contributor.mention}.")

    # ---------------- /fund view ----------------
    @fund_group.command(name="view", description="Show the current fund balance")
    async def fund_view(self, interaction: discord.Interaction):
        totals = await db.get_brainrot_totals()
        money = await db.get_money_total()

        summary = discord.Embed(
            title="💰 Fund Balance",
            description=f"**Money in fund:** ${money:,.2f}",
            color=EMBED_COLOR,
        )

        embeds = [summary]
        files = []
        for key, info in BRAINROTS.items():
            qty = totals.get(key, 0)
            if qty <= 0:
                continue
            file = asset_file(key)
            files.append(file)
            e = discord.Embed(
                description=f"**{info['label']}** — {qty}x",
                color=EMBED_COLOR,
            )
            e.set_thumbnail(url=f"attachment://{file.filename}")
            embeds.append(e)

        await interaction.response.send_message(embeds=embeds, files=files)

    # ---------------- /fund database ----------------
    @fund_group.command(name="database", description="Show who contributed what to the fund")
    @app_commands.describe(brainrot="Only show one brainrot's contributors (optional)")
    @app_commands.choices(brainrot=BRAINROT_CHOICES)
    async def fund_database(
        self, interaction: discord.Interaction, brainrot: app_commands.Choice[str] = None
    ):
        embeds = []

        keys_to_show = [brainrot.value] if brainrot else list(BRAINROTS.keys())
        for key in keys_to_show:
            totals = await db.get_contribution_totals("brainrot", key)
            if not totals:
                continue
            lines = [
                f"<@{uid}> — {int(qty)}x"
                for uid, qty in sorted(totals.items(), key=lambda kv: -kv[1])
            ]
            embeds.append(
                discord.Embed(
                    title=f"{BRAINROTS[key]['label']} contributors",
                    description="\n".join(lines),
                    color=EMBED_COLOR,
                )
            )

        money_totals = await db.get_contribution_totals("money")
        if money_totals and brainrot is None:
            lines = [
                f"<@{uid}> — ${amt:,.2f}"
                for uid, amt in sorted(money_totals.items(), key=lambda kv: -kv[1])
            ]
            embeds.append(
                discord.Embed(
                    title="Money contributors",
                    description="\n".join(lines),
                    color=EMBED_COLOR,
                )
            )

        if not embeds:
            await interaction.response.send_message(
                "No contributions on record yet — this only tracks fund additions made "
                "with `/fund add` going forward.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(embeds=embeds[:10])

    # ---------------- /remove fund ----------------
    @remove_group.command(name="fund", description="Remove brainrots or money from the fund (restricted)")
    @app_commands.describe(
        type="Whether you're removing a brainrot or money",
        amount="How much to remove",
        brainrot="Which brainrot to remove (required if type is Brainrot)",
    )
    @app_commands.choices(
        type=[
            app_commands.Choice(name="Brainrot", value="brainrot"),
            app_commands.Choice(name="Money", value="money"),
        ],
        brainrot=BRAINROT_CHOICES,
    )
    async def remove_fund(
        self,
        interaction: discord.Interaction,
        type: app_commands.Choice[str],
        amount: float,
        brainrot: app_commands.Choice[str] = None,
    ):
        if interaction.user.id != FUND_ADMIN_USER_ID:
            await interaction.response.send_message(
                "You don't have permission to use this command.", ephemeral=True
            )
            return

        if type.value == "brainrot":
            if brainrot is None:
                await interaction.response.send_message(
                    "Pick which `brainrot` to remove.", ephemeral=True
                )
                return
            qty = int(amount)
            await db.remove_brainrot(brainrot.value, qty)
            taken, shortfall = await db.remove_contributions("brainrot", brainrot.value, qty)
            desc = f"**{qty}x {brainrot.name}**"
            from_text = self._format_taken(taken, is_money=False)
        else:
            await db.remove_money(amount)
            taken, shortfall = await db.remove_contributions("money", None, amount)
            desc = f"**${amount:,.2f}**"
            from_text = self._format_taken(taken, is_money=True)

        message = f"Removed {desc} from the fund"
        if from_text:
            message += f" (taken from {from_text})"
        if shortfall > 0:
            leftover = int(shortfall) if type.value == "brainrot" else shortfall
            message += f" — {leftover} of that had no contributor record on file"
        message += "."

        await interaction.response.send_message(message, ephemeral=True)
        await self._log(interaction.user, f"➖ Removed {desc} from the fund" + (f" (from {from_text})" if from_text else "") + ".")

    @staticmethod
    def _format_taken(taken: list, is_money: bool) -> str:
        if not taken:
            return ""
        parts = []
        for t in taken:
            amt = f"${t['amount']:,.2f}" if is_money else f"{int(t['amount'])}x"
            parts.append(f"{amt} from <@{t['user_id']}>")
        return ", ".join(parts)

    async def _log(self, actor: discord.abc.User, text: str):
        channel = self.bot.get_channel(FUND_LOG_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(FUND_LOG_CHANNEL_ID)
            except discord.HTTPException:
                return
        embed = discord.Embed(description=text, color=EMBED_COLOR)
        embed.set_author(name=actor.display_name, icon_url=actor.display_avatar.url)
        embed.timestamp = discord.utils.utcnow()
        await channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Fund(bot))
