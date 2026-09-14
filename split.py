import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import database as db
from config import (
    BRAINROTS,
    EMBED_COLOR,
    SPLIT_TEAM_SIZE,
    BLOCKCYPHER_TOKEN,
    BSCSCAN_API_KEY,
    USDT_BEP20_CONTRACT,
    SPLIT_PAYMENT_TOLERANCE,
)
from wallet import WalletView

BRAINROT_CHOICES = [
    app_commands.Choice(name=info["label"], value=key) for key, info in BRAINROTS.items()
]


async def get_ltc_usd_price() -> float:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "litecoin", "vs_currencies": "usd"},
        ) as resp:
            data = await resp.json()
            return float(data["litecoin"]["usd"])


async def find_ltc_payment(receiver_address: str, sender_address: str, min_usd: float, tolerance: float):
    """Look for an incoming LTC tx to receiver_address whose input includes sender_address,
    worth at least min_usd (with tolerance). Returns (tx_id, amount_usd) or None."""
    price = await get_ltc_usd_price()

    url = f"https://api.blockcypher.com/v1/ltc/main/addrs/{receiver_address}/full"
    params = {"limit": 50}
    if BLOCKCYPHER_TOKEN:
        params["token"] = BLOCKCYPHER_TOKEN

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()

    for tx in data.get("txs", []):
        input_addrs = set()
        for i in tx.get("inputs", []):
            input_addrs.update(i.get("addresses", []) or [])
        if sender_address not in input_addrs:
            continue
        for out in tx.get("outputs", []):
            if receiver_address in (out.get("addresses") or []):
                amount_ltc = out.get("value", 0) / 1e8
                amount_usd = amount_ltc * price
                if amount_usd >= min_usd * (1 - tolerance):
                    return tx.get("hash"), amount_usd
    return None


async def find_usdt_bep20_payment(receiver_address: str, sender_address: str, min_usd: float, tolerance: float):
    """Look for an incoming USDT (BEP20) transfer to receiver_address from sender_address,
    worth at least min_usd (with tolerance). Returns (tx_id, amount_usd) or None."""
    url = "https://api.bscscan.com/api"
    params = {
        "module": "account",
        "action": "tokentx",
        "contractaddress": USDT_BEP20_CONTRACT,
        "address": receiver_address,
        "sort": "desc",
    }
    if BSCSCAN_API_KEY:
        params["apikey"] = BSCSCAN_API_KEY

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            data = await resp.json()

    for tx in data.get("result", []) or []:
        if tx.get("from", "").lower() != sender_address.lower():
            continue
        if tx.get("to", "").lower() != receiver_address.lower():
            continue
        decimals = int(tx.get("tokenDecimal", 18))
        amount_usdt = int(tx.get("value", "0")) / (10 ** decimals)
        if amount_usdt >= min_usd * (1 - tolerance):
            return tx.get("hash"), amount_usdt
    return None


class Split(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    split_group = app_commands.Group(name="split", description="Split a brainrot cost across the team")

    @split_group.command(name="start", description="Start a new cost split for the team")
    @app_commands.describe(
        brainrot="Which brainrot this split is for",
        total="Total cost to split",
    )
    @app_commands.choices(brainrot=BRAINROT_CHOICES)
    async def split_start(
        self,
        interaction: discord.Interaction,
        brainrot: app_commands.Choice[str],
        total: float,
    ):
        existing = await db.get_active_split()
        if existing is not None:
            await interaction.response.send_message(
                "There's already an active split. Finish it out with `/split complete` for everyone first.",
                ephemeral=True,
            )
            return

        per_person = total / SPLIT_TEAM_SIZE

        split_id = await db.create_split(
            creator_id=interaction.user.id,
            brainrot=brainrot.value,
            total_amount=total,
            team_size=SPLIT_TEAM_SIZE,
            channel_id=interaction.channel_id,
        )

        wallets = await db.get_wallets(interaction.user.id)

        embed = discord.Embed(title="💸 New Split Started", color=EMBED_COLOR)
        embed.add_field(name="Started by", value=interaction.user.mention, inline=False)
        embed.add_field(name="Brainrot", value=brainrot.name, inline=True)
        embed.add_field(name="Total Cost", value=f"${total:,.2f}", inline=True)
        embed.add_field(name="Split Between", value=f"{SPLIT_TEAM_SIZE} people", inline=True)
        embed.add_field(name="Each Person Pays", value=f"${per_person:,.2f}", inline=False)
        embed.set_footer(text="Tap a button below to see where to send your share.")

        view = None
        if wallets:
            view = WalletView(wallets)
        else:
            embed.add_field(
                name="⚠️ No address on file",
                value=f"{interaction.user.mention} hasn't saved a payment address yet — run `/wallet add` first.",
                inline=False,
            )

        if view is not None:
            message = await interaction.channel.send(embed=embed, view=view)
        else:
            message = await interaction.channel.send(embed=embed)

        await db.set_split_message(split_id, message.id)
        await interaction.response.send_message("Split started!", ephemeral=True)

    @split_group.command(name="complete", description="Mark a person's share of the active split as paid")
    @app_commands.describe(user="The person who paid their share")
    async def split_complete(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.send_message(
            "⏳ Hang Tight! Checking the blockchain for a recent payment.", ephemeral=True
        )

        split = await db.get_active_split()
        if split is None:
            await interaction.edit_original_response(content="There's no active split right now.")
            return

        already = await db.get_split_payment(split["id"], user.id)
        if already and already["paid"]:
            await interaction.edit_original_response(
                content=f"{user.display_name} is already marked as paid for this split."
            )
            return

        creator_wallets = await db.get_wallets(split["creator_id"])
        payer_wallets = await db.get_wallets(user.id)

        if not creator_wallets:
            await interaction.edit_original_response(
                content="The split creator hasn't saved a payment address, so I can't verify anything."
            )
            return
        if not payer_wallets:
            await interaction.edit_original_response(
                content=f"{user.display_name} hasn't saved a payment address with `/wallet add`, so I can't match their payment."
            )
            return

        per_person = split["per_person_amount"]
        result = None
        used_coin = None

        for pw in payer_wallets:
            for cw in creator_wallets:
                if pw["coin"] != cw["coin"]:
                    continue
                if pw["coin"] == "LTC":
                    found = await find_ltc_payment(cw["address"], pw["address"], per_person, SPLIT_PAYMENT_TOLERANCE)
                elif pw["coin"] == "USDT":
                    found = await find_usdt_bep20_payment(cw["address"], pw["address"], per_person, SPLIT_PAYMENT_TOLERANCE)
                else:
                    found = None
                if found:
                    result = found
                    used_coin = pw["coin"]
                    break
            if result:
                break

        if not result:
            await interaction.edit_original_response(
                content=(
                    f"Couldn't find a matching payment of at least ${per_person:,.2f} "
                    f"from {user.display_name} yet. Try again in a few minutes."
                )
            )
            return

        tx_id, amount_paid = result
        await db.mark_split_payment(split["id"], user.id, tx_id, amount_paid, used_coin)

        await interaction.edit_original_response(
            content=f"✅ Verified — {user.display_name}'s payment is confirmed."
        )

        channel = self.bot.get_channel(split["channel_id"])
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(split["channel_id"])
            except discord.HTTPException:
                channel = None
        if channel is not None:
            await channel.send(f"✅ {user.mention} has paid their share of the split.")

        creator = self.bot.get_user(split["creator_id"])
        if creator is None:
            try:
                creator = await self.bot.fetch_user(split["creator_id"])
            except discord.HTTPException:
                creator = None
        if creator is not None:
            dm_embed = discord.Embed(title="Split Payment Received", color=EMBED_COLOR)
            dm_embed.add_field(name="Paid by", value=user.display_name, inline=False)
            dm_embed.add_field(name="Amount", value=f"${amount_paid:,.2f} ({used_coin})", inline=True)
            dm_embed.add_field(name="Transaction ID", value=f"`{tx_id}`", inline=False)
            try:
                await creator.send(embed=dm_embed)
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Split(bot))
