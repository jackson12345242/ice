import difflib
import os

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from config import EMBED_COLOR, PAYMENT_LOG_CHANNEL_ID, PAYMENT_ADMIN_USER_ID, PAYMENT_BRAINROTS

BRAINROT_CHOICES = [
    app_commands.Choice(name=info["label"], value=key) for key, info in PAYMENT_BRAINROTS.items()
]

_KNOWN_LABELS = {
    info["label"]: key for key, info in PAYMENT_BRAINROTS.items() if key != "other"
}


def resolve_brainrot(choice_value: str, other_name: str = ""):
    """Returns (key, display_label). If 'other' was picked but the typed name closely
    matches a known brainrot, snap to that instead of creating a stray 'other' entry."""
    if choice_value != "other":
        return choice_value, PAYMENT_BRAINROTS[choice_value]["label"]

    name = (other_name or "").strip()
    if name:
        match = difflib.get_close_matches(name, _KNOWN_LABELS.keys(), n=1, cutoff=0.6)
        if match:
            matched_key = _KNOWN_LABELS[match[0]]
            return matched_key, PAYMENT_BRAINROTS[matched_key]["label"]
    return "other", name or "Other"


class LeaderboardView(discord.ui.View):
    def __init__(self, money_embed: discord.Embed, brainrot_embed: discord.Embed):
        super().__init__(timeout=180)
        self.money_embed = money_embed
        self.brainrot_embed = brainrot_embed

    @discord.ui.button(label="💰 Money", style=discord.ButtonStyle.primary)
    async def money_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.money_embed)

    @discord.ui.button(label="🧠 Brainrot", style=discord.ButtonStyle.secondary)
    async def brainrot_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.brainrot_embed)


class Payment(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    payment_group = app_commands.Group(name="payment", description="Track team payments")
    log_group = app_commands.Group(name="log", description="Log a payment", parent=payment_group)

    async def _post_log(self, embed: discord.Embed):
        channel = self.bot.get_channel(PAYMENT_LOG_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(PAYMENT_LOG_CHANNEL_ID)
            except discord.HTTPException:
                return
        await channel.send(embed=embed)

    # ---------------- /payment log brainrot ----------------
    @log_group.command(name="brainrot", description="Log brainrots you've received")
    @app_commands.describe(
        brainrot="Which brainrot",
        quantity="How many (default 1)",
        other_name="Name of the brainrot if you picked Other",
        image="Optional proof screenshot",
    )
    @app_commands.choices(brainrot=BRAINROT_CHOICES)
    async def log_brainrot(
        self,
        interaction: discord.Interaction,
        brainrot: app_commands.Choice[str],
        quantity: int = 1,
        other_name: str = "",
        image: discord.Attachment = None,
    ):
        key, label = resolve_brainrot(brainrot.value, other_name)
        image_url = image.url if image else None

        await db.log_payment_brainrot(
            interaction.user.id, key, label if key == "other" else None, quantity, image_url
        )

        embed = discord.Embed(title="🧠 Brainrot Logged", color=EMBED_COLOR)
        embed.add_field(name="Logged by", value=interaction.user.mention, inline=False)
        embed.add_field(name="Brainrot", value=f"{quantity}x {label}", inline=True)
        if image_url:
            embed.set_image(url=image_url)
        embed.timestamp = discord.utils.utcnow()

        await interaction.response.send_message(f"Logged {quantity}x {label}.", ephemeral=True)
        await self._post_log(embed)

    # ---------------- /payment log money ----------------
    @log_group.command(name="money", description="Log a money payment")
    @app_commands.describe(amount="How much you paid", image="Optional proof screenshot")
    async def log_money(
        self,
        interaction: discord.Interaction,
        amount: float,
        image: discord.Attachment = None,
    ):
        image_url = image.url if image else None
        await db.log_payment_money(interaction.user.id, amount, image_url)

        embed = discord.Embed(title="💵 Money Logged", color=EMBED_COLOR)
        embed.add_field(name="Logged by", value=interaction.user.mention, inline=False)
        embed.add_field(name="Amount", value=f"${amount:,.2f}", inline=True)
        if image_url:
            embed.set_image(url=image_url)
        embed.timestamp = discord.utils.utcnow()

        await interaction.response.send_message(f"Logged ${amount:,.2f}.", ephemeral=True)
        await self._post_log(embed)

    # ---------------- /payment view ----------------
    @payment_group.command(name="view", description="View a user's logged payments")
    @app_commands.describe(user="Whose payments to view (defaults to you)")
    async def payment_view(self, interaction: discord.Interaction, user: discord.User = None):
        target = user or interaction.user
        totals, money_total = await db.get_payment_summary(target.id)

        if not totals and money_total <= 0:
            await interaction.response.send_message(
                f"{target.display_name} hasn't logged any payments yet.", ephemeral=True
            )
            return

        summary = discord.Embed(
            title=f"📋 {target.display_name}'s Payments",
            description=f"**Total money paid:** ${money_total:,.2f}",
            color=EMBED_COLOR,
        )

        embeds = [summary]
        files = []
        line_num = 1
        for entry in totals.values():
            qty = entry["quantity"]
            if qty <= 0:
                continue
            key = entry["key"]
            label = entry["other_name"] if key == "other" else PAYMENT_BRAINROTS[key]["label"]
            asset = PAYMENT_BRAINROTS.get(key, {}).get("asset")

            e = discord.Embed(description=f"**{line_num}. {qty}x {label}**", color=EMBED_COLOR)
            if asset and os.path.exists(asset):
                file = discord.File(asset, filename=os.path.basename(asset))
                files.append(file)
                e.set_thumbnail(url=f"attachment://{file.filename}")
            embeds.append(e)
            line_num += 1

        await interaction.response.send_message(embeds=embeds, files=files)

    # ---------------- /payment leaderboard ----------------
    @payment_group.command(name="leaderboard", description="View the payment leaderboard")
    async def payment_leaderboard(self, interaction: discord.Interaction):
        money_rows = await db.get_leaderboard_money()
        money_embed = discord.Embed(title="💰 Money Leaderboard", color=EMBED_COLOR)
        if money_rows:
            lines = [f"{i + 1}. <@{r['user_id']}> — ${r['total']:,.2f}" for i, r in enumerate(money_rows[:15])]
            money_embed.description = "\n".join(lines)
        else:
            money_embed.description = "No money logged yet."

        raw_rows = await db.get_leaderboard_brainrot_rows()
        per_user = {}
        for user_id, key, other_name, qty in raw_rows:
            if not qty:
                continue
            tier = PAYMENT_BRAINROTS.get(key, {}).get("tier", 0)
            entry = per_user.setdefault(user_id, {"score": 0, "counts": {}})
            entry["score"] += qty * tier
            label = other_name if key == "other" else PAYMENT_BRAINROTS[key]["label"]
            entry["counts"][label] = entry["counts"].get(label, 0) + qty

        ranked = sorted(per_user.items(), key=lambda kv: kv[1]["score"], reverse=True)
        brainrot_embed = discord.Embed(title="🧠 Brainrot Leaderboard", color=EMBED_COLOR)
        lines = []
        for i, (user_id, data) in enumerate(ranked[:15]):
            positive_counts = {label: c for label, c in data["counts"].items() if c > 0}
            if not positive_counts:
                continue
            counts_str = ", ".join(f"{c}x {label}" for label, c in positive_counts.items())
            lines.append(f"{i + 1}. <@{user_id}> — {counts_str}")
        brainrot_embed.description = "\n".join(lines) if lines else "No brainrots logged yet."

        view = LeaderboardView(money_embed, brainrot_embed)
        await interaction.response.send_message(embed=money_embed, view=view)

    # ---------------- /payment remove ----------------
    @payment_group.command(name="remove", description="Remove a user's logged payments (admin only)")
    @app_commands.describe(
        user="Whose payments to adjust",
        type="Brainrot or Money",
        brainrot="Which brainrot to remove (Brainrot type only; leave blank to clear every type)",
        amount="Specific amount/quantity to subtract (leave blank to clear everything in that category)",
    )
    @app_commands.choices(
        type=[
            app_commands.Choice(name="Brainrot", value="brainrot"),
            app_commands.Choice(name="Money", value="money"),
        ],
        brainrot=BRAINROT_CHOICES,
    )
    async def payment_remove(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        type: app_commands.Choice[str],
        brainrot: app_commands.Choice[str] = None,
        amount: float = None,
    ):
        if interaction.user.id != PAYMENT_ADMIN_USER_ID:
            await interaction.response.send_message(
                "You don't have permission to use this command.", ephemeral=True
            )
            return

        if type.value == "money":
            if amount is None:
                await db.clear_payment_money(user.id)
                desc = "cleared all logged money"
            else:
                await db.adjust_payment_money(user.id, amount)
                desc = f"removed ${amount:,.2f}"
        else:
            if brainrot is None:
                await db.clear_payment_brainrot(user.id)
                desc = "cleared all logged brainrots"
            elif amount is None:
                await db.clear_payment_brainrot(user.id, brainrot.value)
                desc = f"cleared all logged {brainrot.name}"
            else:
                await db.adjust_payment_brainrot(user.id, brainrot.value, int(amount))
                desc = f"removed {int(amount)}x {brainrot.name}"

        await interaction.response.send_message(f"Done — {desc} for {user.display_name}.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Payment(bot))
