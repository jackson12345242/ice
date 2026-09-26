import discord
from discord import app_commands
from discord.ext import commands

import database as db
from coins import normalize_coin


class AddressButton(discord.ui.Button):
    def __init__(self, coin: str, network: str, address: str):
        label = f"{coin} — {network}" if network else coin
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.address = address

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(self.address, ephemeral=True)


class WalletView(discord.ui.View):
    def __init__(self, wallets: list[dict]):
        super().__init__(timeout=None)
        for w in wallets:
            self.add_item(AddressButton(w["coin"], w["network"], w["address"]))


def build_wallet_embed(target: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="Payment Addresses",
        description="Select a payment method below to view the saved address.",
        color=0x2B2D31,
    )
    embed.set_footer(text=f"Addresses saved by {target.display_name}")
    embed.timestamp = discord.utils.utcnow()
    return embed


class Wallet(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    wallet_group = app_commands.Group(name="wallet", description="Manage saved crypto payment addresses")

    @wallet_group.command(name="add", description="Save a crypto payment address")
    @app_commands.describe(
        coin="The coin, e.g. USDT, LTC, BTC",
        address="The wallet address",
        network="Optional network label, e.g. BSC, TRC20, ERC20",
    )
    async def wallet_add(
        self,
        interaction: discord.Interaction,
        coin: str,
        address: str,
        network: str = "",
    ):
        # Normalize so "Litecoin"/"LTC"/"litecoin" etc. are always saved as the same canonical
        # coin — this is what split-payment matching relies on to compare wallets correctly.
        coin = normalize_coin(coin)

        await db.add_wallet(interaction.user.id, coin, address, network)
        wallets = await db.get_wallets(interaction.user.id)

        embed = build_wallet_embed(interaction.user)
        embed.add_field(
            name="Saved",
            value=f"**{coin}{' — ' + network.upper() if network else ''}** address saved.",
            inline=False,
        )
        view = WalletView(wallets)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @wallet_group.command(name="user", description="View a user's saved payment addresses")
    @app_commands.describe(user="Whose addresses to view (defaults to you)")
    async def wallet_user(
        self,
        interaction: discord.Interaction,
        user: discord.User = None,
    ):
        target = user or interaction.user
        wallets = await db.get_wallets(target.id)

        if not wallets:
            await interaction.response.send_message(
                f"{target.display_name} hasn't saved any payment addresses yet.",
                ephemeral=True,
            )
            return

        embed = build_wallet_embed(target)
        view = WalletView(wallets)
        await interaction.response.send_message(embed=embed, view=view)

    @wallet_group.command(name="remove", description="Remove one of your saved payment addresses")
    @app_commands.describe(
        coin="Which coin's address to remove, e.g. USDT, LTC",
        network="Optional — only needed if you have more than one saved address for that coin",
    )
    async def wallet_remove(
        self,
        interaction: discord.Interaction,
        coin: str,
        network: str = "",
    ):
        target_coin = normalize_coin(coin)
        wallets = await db.get_wallets(interaction.user.id)
        matches = [w for w in wallets if normalize_coin(w["coin"]) == target_coin]

        if network:
            narrowed = [w for w in matches if (w["network"] or "").strip().lower() == network.strip().lower()]
            if narrowed:
                matches = narrowed

        if not matches:
            await interaction.response.send_message(
                f"You don't have a saved **{target_coin}** address to remove.", ephemeral=True
            )
            return

        if len(matches) > 1:
            lines = "\n".join(f"• {w['coin']} — {w['network'] or 'no network set'}" for w in matches)
            await interaction.response.send_message(
                f"You have more than one **{target_coin}** address saved — pass `network` to pick which one:\n{lines}",
                ephemeral=True,
            )
            return

        removed = matches[0]
        await db.remove_wallet(interaction.user.id, removed["coin"], removed["network"])

        wallets = await db.get_wallets(interaction.user.id)
        embed = build_wallet_embed(interaction.user)
        embed.add_field(
            name="Removed",
            value=f"**{removed['coin']}{' — ' + removed['network'].upper() if removed['network'] else ''}** address removed.",
            inline=False,
        )
        view = WalletView(wallets) if wallets else None
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Wallet(bot))
