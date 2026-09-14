import discord
from discord import app_commands
from discord.ext import commands

import database as db


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
        await db.add_wallet(interaction.user.id, coin, address, network)
        wallets = await db.get_wallets(interaction.user.id)

        embed = build_wallet_embed(interaction.user)
        embed.add_field(
            name="Saved",
            value=f"**{coin.upper()}{' — ' + network.upper() if network else ''}** address saved.",
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


async def setup(bot: commands.Bot):
    await bot.add_cog(Wallet(bot))
