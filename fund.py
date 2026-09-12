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
    )
    @app_commands.choices(brainrot=BRAINROT_CHOICES)
    async def fund_add(
        self,
        interaction: discord.Interaction,
        amount: int = None,
        brainrot: app_commands.Choice[str] = None,
        money: float = None,
    ):
        if brainrot is None and money is None:
            await interaction.response.send_message(
                "Give me at least a `brainrot` or a `money` amount to add.",
                ephemeral=True,
            )
            return

        added_lines = []

        if brainrot is not None:
            qty = amount if amount is not None else 1
            await db.add_brainrot(brainrot.value, qty)
            added_lines.append(f"**{qty}x {brainrot.name}**")

        if money is not None:
            await db.add_money(money)
            added_lines.append(f"**${money:,.2f}**")

        summary = " and ".join(added_lines)
        await interaction.response.send_message(f"Added {summary} to the fund.", ephemeral=True)

        await self._log(interaction.user, f"➕ Added {summary} to the fund.")

    # ---------------- /fund ----------------
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
            await db.remove_brainrot(brainrot.value, int(amount))
            desc = f"**{int(amount)}x {brainrot.name}**"
        else:
            await db.remove_money(amount)
            desc = f"**${amount:,.2f}**"

        await interaction.response.send_message(f"Removed {desc} from the fund.", ephemeral=True)
        await self._log(interaction.user, f"➖ Removed {desc} from the fund.")

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
