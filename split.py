import datetime
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import database as db
from config import (
    EMBED_COLOR,
    SPLIT_TEAM_SIZE,
    BLOCKCYPHER_TOKEN,
    MEGANODE_API_KEY,
    USDT_BEP20_CONTRACT,
    SPLIT_PAYMENT_TOLERANCE,
    SPLIT_PAYMENT_WINDOW_MINUTES,
)
from wallet import WalletView
from coins import normalize_coin

# BSCTrace (via MegaNode) is the current recommended replacement for the deprecated
# BscScan API and for Etherscan V2 (which has no free tier for BNB Chain). It's a
# standard JSON-RPC 2.0 endpoint rather than a REST/module-action API.
MEGANODE_BSC_URL = f"https://bsc-mainnet.nodereal.io/v1/{MEGANODE_API_KEY}"

# How far back (in blocks) to look when scanning for the payment window, as a safety
# margin around SPLIT_PAYMENT_WINDOW_MINUTES. BSC blocks land roughly every ~1-3s, so
# 10,000 blocks comfortably covers windows well beyond 15 minutes with room to spare.
MEGANODE_BLOCK_LOOKBACK = 10_000

log = logging.getLogger(__name__)


async def get_ltc_usd_price() -> float:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "litecoin", "vs_currencies": "usd"},
        ) as resp:
            data = await resp.json()
            return float(data["litecoin"]["usd"])


async def find_ltc_payments(receiver_address: str, sender_address: str, min_usd: float, tolerance: float):
    """Return every RECENT incoming LTC tx to receiver_address from sender_address that lands
    within the tolerance band of min_usd, most recent first: [(tx_id, amount_usd), ...]."""
    price = await get_ltc_usd_price()
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        minutes=SPLIT_PAYMENT_WINDOW_MINUTES
    )

    url = f"https://api.blockcypher.com/v1/ltc/main/addrs/{receiver_address}/full"
    params = {"limit": 50, "confirmations": 0}
    if BLOCKCYPHER_TOKEN:
        params["token"] = BLOCKCYPHER_TOKEN

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                body = await resp.text()
                log.warning(
                    "BlockCypher LTC lookup failed for %s: HTTP %s — %s",
                    receiver_address, resp.status, body[:300],
                )
                return []
            data = await resp.json()

    matches = []
    seen_from_sender = 0
    near_misses = []
    for tx in data.get("txs", []):
        ts_raw = tx.get("confirmed") or tx.get("received")
        if not ts_raw:
            continue
        try:
            tx_time = datetime.datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if tx_time < cutoff:
            continue

        input_addrs = set()
        for i in tx.get("inputs", []):
            input_addrs.update(i.get("addresses", []) or [])
        if sender_address not in input_addrs:
            continue

        seen_from_sender += 1
        for out in tx.get("outputs", []):
            if receiver_address in (out.get("addresses") or []):
                amount_ltc = out.get("value", 0) / 1e8
                amount_usd = amount_ltc * price
                if abs(amount_usd - min_usd) <= min_usd * tolerance:
                    matches.append((tx.get("hash"), amount_usd))
                else:
                    near_misses.append((tx.get("hash"), amount_usd))

    if not matches:
        log.info(
            "LTC match miss: receiver=%s sender=%s expected=$%.2f tolerance=%.2f window=%sm "
            "-> %s tx(s) in window from sender, near-misses(usd)=%s",
            receiver_address, sender_address, min_usd, tolerance, SPLIT_PAYMENT_WINDOW_MINUTES,
            seen_from_sender, near_misses,
        )
    return matches


async def _meganode_rpc(session: aiohttp.ClientSession, method: str, params: list):
    """Call a JSON-RPC 2.0 method against the BSCTrace/MegaNode endpoint. Returns the
    parsed `result` on success, or None (with a warning logged) on any failure."""
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    async with session.post(MEGANODE_BSC_URL, json=payload) as resp:
        try:
            data = await resp.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError) as e:
            body = await resp.text()
            log.warning(
                "MegaNode %s returned unparseable response: HTTP %s (%s) — %s",
                method, resp.status, e, body[:300],
            )
            return None
        if resp.status != 200:
            log.warning("MegaNode %s failed: HTTP %s — %s", method, resp.status, str(data)[:300])
            return None
        if "error" in data:
            log.warning("MegaNode %s API error: %s", method, data["error"])
            return None
        return data.get("result")


async def find_usdt_bep20_payments(receiver_address: str, sender_address: str, min_usd: float, tolerance: float):
    """Return every RECENT incoming USDT (BEP20) transfer to receiver_address from sender_address
    that lands within the tolerance band of min_usd, most recent first: [(tx_id, amount_usd), ...].

    Uses BSCTrace via MegaNode's nr_getAssetTransfers (JSON-RPC), the recommended
    replacement for the deprecated BscScan API / paid-only Etherscan V2 BNB Chain access.
    """
    cutoff_ts = int(
        (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=SPLIT_PAYMENT_WINDOW_MINUTES)).timestamp()
    )

    async with aiohttp.ClientSession() as session:
        latest_hex = await _meganode_rpc(session, "eth_blockNumber", [])
        if latest_hex is None:
            return []
        try:
            latest_block = int(latest_hex, 16)
        except (TypeError, ValueError):
            log.warning("MegaNode eth_blockNumber returned unexpected value: %r", latest_hex)
            return []
        from_block = max(latest_block - MEGANODE_BLOCK_LOOKBACK, 0)

        result = await _meganode_rpc(
            session,
            "nr_getAssetTransfers",
            [{
                "category": ["20"],
                "fromBlock": hex(from_block),
                "toBlock": hex(latest_block),
                "contractAddresses": [USDT_BEP20_CONTRACT],
                "fromAddress": sender_address,
                "toAddress": receiver_address,
                "order": "desc",
                "maxCount": "0x3e8",  # 1000, the max nr_getAssetTransfers allows
            }],
        )

    if result is None:
        return []

    matches = []
    seen_from_sender = 0
    near_misses = []
    for tr in result.get("transfers", []) or []:
        try:
            tx_ts = int(tr.get("blockTimeStamp", 0))
        except (TypeError, ValueError):
            continue
        if tx_ts < cutoff_ts:
            continue

        if (tr.get("from") or "").lower() != sender_address.lower():
            continue
        if (tr.get("to") or "").lower() != receiver_address.lower():
            continue

        seen_from_sender += 1
        try:
            raw_value = int(tr.get("value", "0x0"), 16)
        except (TypeError, ValueError):
            continue
        decimal_hex = tr.get("decimal")
        try:
            decimals = int(decimal_hex, 16) if decimal_hex else 18
        except (TypeError, ValueError):
            decimals = 18
        amount_usdt = raw_value / (10 ** decimals)

        if abs(amount_usdt - min_usd) <= min_usd * tolerance:
            matches.append((tr.get("hash"), amount_usdt))
        else:
            near_misses.append((tr.get("hash"), amount_usdt))

    if not matches:
        log.info(
            "USDT match miss: receiver=%s sender=%s expected=$%.2f tolerance=%.2f window=%sm "
            "-> %s tx(s) in window from sender, near-misses(usdt)=%s",
            receiver_address, sender_address, min_usd, tolerance, SPLIT_PAYMENT_WINDOW_MINUTES,
            seen_from_sender, near_misses,
        )
    return matches


class Split(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    split_group = app_commands.Group(name="split", description="Split a brainrot cost across the team")

    @split_group.command(name="start", description="Start a new cost split for the team")
    @app_commands.describe(
        brainrot="Which brainrot this split is for",
        total="Total cost to split",
    )
    async def split_start(
        self,
        interaction: discord.Interaction,
        brainrot: str,
        total: float,
    ):
        existing = await db.get_active_split()
        if existing is not None:
            await interaction.response.send_message(
                "There's already an active split. End it with `/split end` before starting a new one.",
                ephemeral=True,
            )
            return

        brainrot = brainrot.strip()
        per_person = total / SPLIT_TEAM_SIZE

        split_id = await db.create_split(
            creator_id=interaction.user.id,
            brainrot=brainrot,
            total_amount=total,
            team_size=SPLIT_TEAM_SIZE,
            channel_id=interaction.channel_id,
        )

        wallets = await db.get_wallets(interaction.user.id)

        embed = discord.Embed(title="💸 New Split Started", color=EMBED_COLOR)
        embed.add_field(name="Started by", value=interaction.user.mention, inline=False)
        embed.add_field(name="Brainrot", value=brainrot, inline=True)
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

    @split_group.command(name="end", description="End the active split")
    async def split_end(self, interaction: discord.Interaction):
        split = await db.get_active_split()
        if split is None:
            await interaction.response.send_message("There's no active split right now.", ephemeral=True)
            return

        await db.end_split(split["id"])
        summary = await db.get_split_summary(split["id"])

        embed = discord.Embed(title="🏁 Split Ended", color=EMBED_COLOR)
        embed.add_field(name="Brainrot", value=split["brainrot"], inline=True)
        embed.add_field(name="Total Cost", value=f"${split['total_amount']:,.2f}", inline=True)
        embed.add_field(name="Paid", value=f"{len(summary)} / {split['team_size']}", inline=True)
        if summary:
            lines = [f"<@{p['user_id']}> — ${p['amount_paid']:,.2f} ({p['coin']})" for p in summary]
            embed.add_field(name="Confirmed payers", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Confirmed payers", value="No one confirmed yet.", inline=False)

        await interaction.response.send_message(embed=embed)

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
            pw_coin = normalize_coin(pw["coin"])
            for cw in creator_wallets:
                cw_coin = normalize_coin(cw["coin"])
                if pw_coin != cw_coin:
                    continue
                if pw_coin == "LTC":
                    try:
                        candidates = await find_ltc_payments(cw["address"], pw["address"], per_person, SPLIT_PAYMENT_TOLERANCE)
                    except Exception:
                        log.exception("LTC payment lookup crashed for receiver=%s sender=%s", cw["address"], pw["address"])
                        candidates = []
                elif pw_coin == "USDT":
                    try:
                        candidates = await find_usdt_bep20_payments(cw["address"], pw["address"], per_person, SPLIT_PAYMENT_TOLERANCE)
                    except Exception:
                        log.exception("USDT payment lookup crashed for receiver=%s sender=%s", cw["address"], pw["address"])
                        candidates = []
                else:
                    candidates = []

                for tx_id, amount_usd in candidates:
                    if await db.is_tx_used(tx_id):
                        continue  # this exact transaction already credited someone else — skip it
                    result = (tx_id, amount_usd)
                    used_coin = pw_coin
                    break
                if result:
                    break
            if result:
                break

        if not result:
            payer_coins = {normalize_coin(w["coin"]) for w in payer_wallets}
            creator_coins = {normalize_coin(w["coin"]) for w in creator_wallets}
            if not (payer_coins & creator_coins):
                log.info(
                    "Split coin mismatch: %s's wallets normalize to %s, %s's wallets normalize to %s — no overlap",
                    user.display_name, payer_coins, self.bot.get_user(split["creator_id"]) or split["creator_id"], creator_coins,
                )
            await interaction.edit_original_response(
                content=(
                    f"Couldn't find a matching, unused payment of about ${per_person:,.2f} "
                    f"from {user.display_name}'s saved address yet. Try again in a few minutes."
                )
            )
            return

        tx_id, amount_paid = result
        await db.mark_split_payment(split["id"], user.id, tx_id, amount_paid, used_coin)
        await db.mark_tx_used(tx_id, split["id"], user.id)

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
            summary = await db.get_split_summary(split["id"])
            total_received = sum(p["amount_paid"] for p in summary)

            if used_coin == "LTC":
                explorer_url = f"https://live.blockcypher.com/ltc/tx/{tx_id}/"
            elif used_coin == "USDT":
                explorer_url = f"https://bscscan.com/tx/{tx_id}"
            else:
                explorer_url = None

            dm_embed = discord.Embed(title="Split Payment Received", color=EMBED_COLOR, url=explorer_url)
            dm_embed.add_field(name="Brainrot", value=split["brainrot"], inline=False)
            dm_embed.add_field(name="Paid by", value=user.display_name, inline=True)
            dm_embed.add_field(name="Amount", value=f"${amount_paid:,.2f} ({used_coin})", inline=True)
            dm_embed.add_field(name="Transaction ID", value=f"`{tx_id}`", inline=False)
            if explorer_url:
                dm_embed.add_field(name="View Transaction", value=explorer_url, inline=False)
            dm_embed.add_field(
                name="Received So Far (this split)",
                value=f"${total_received:,.2f} / ${split['total_amount']:,.2f} — {len(summary)}/{split['team_size']} paid",
                inline=False,
            )
            if summary:
                payer_lines = [f"<@{p['user_id']}> — ${p['amount_paid']:,.2f} ({p['coin']})" for p in summary]
                dm_embed.add_field(name="People who've paid", value="\n".join(payer_lines), inline=False)

            try:
                await creator.send(embed=dm_embed)
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Split(bot))
