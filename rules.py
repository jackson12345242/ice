import discord
from discord import app_commands
from discord.ext import commands

import database as db
from config import EMBED_COLOR, RULES_ADMIN_USER_ID, RULES_LOG_CHANNEL_ID

RULES_TITLE = "ECLIPSE BASE RULES"

RULES_BODY = (
    "**1.** Be respectful to one another. Don't start fights in group chats. "
    "Take it to DMs. Common sense.\n\n"
    "**2.** If you get scammed for any item, IMMEDIATELY notify the team. "
    "We have ways to find out and it's always worse if you lie.\n\n"
    "**3.** Expensive items will be split even among group members. $25 or more item is split.\n\n"
    "**4.** Big items are obtained from the fund of dragons, but you are STILL expected to "
    "get items on your own as well separate from these funds.\n\n"
    "**5.** We will track every item obtained and what was paid for it (with proof via "
    "screenshot). Those people with lowest contribution can and will be asked for "
    "additional contribution to the fund.\n\n"
    "**6.** Prioritize valuable items (Los primos, traladeon, evildeon, orcaladeon, Los 25, "
    "chimnio, La ginger sekolah, rubrikoko, abysalocco, etc other items that Sammy only "
    "runs 1-2 times)\n\n"
    "**7.** Payment splits are expected within 24 hours of announcement. Unless an "
    "explanation is provided and arrangement is agreed upon.\n\n"
    "**8.** You can share indexes with other groups, but return items to the accounts so "
    "they are in accounts at all times.\n\n"
    "**9.** Do not remove extra items after the base is completed. Extra items are kept in "
    "case replacements are needed.\n\n"
    "**10.** Extremely valuable items (Los primos, etc) or extras will only be sold off "
    "when we have 5 extra items.\n\n"
    "**11.** Account access will remain limited while we collect base. Everyone will "
    "receive access once the base is available to sell.\n\n"
    "**12.** Repeated rule violations or extreme violations can and will result in removal "
    "from group without compensation. Use common sense. This means you may be kicked for "
    "any justifiable reason if agreed upon by leaders."
)

AGREE_DISCLAIMER = (
    "By clicking agree that means you agree to all the following rules above and that you "
    "may not devalue the base by selling it for under the market price and that you will not be given compensatiom if
    you leave or get kicked from the team."
)


class RulesView(discord.ui.View):
    """Persistent view — timeout=None and a fixed custom_id so the Agree button keeps
    working across bot restarts. 'Only once' is enforced via the rule_agreements table,
    not in-memory state, since persistent views are shared across every message."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Agree", style=discord.ButtonStyle.success, custom_id="eclipse_rules_agree")
    async def agree(self, interaction: discord.Interaction, button: discord.ui.Button):
        recorded = await db.record_rule_agreement(interaction.user.id)

        if not recorded:
            await interaction.response.send_message(
                "You've already agreed to the rules.", ephemeral=True
            )
            return

        await interaction.response.send_message(AGREE_DISCLAIMER, ephemeral=True)

        channel = interaction.client.get_channel(RULES_LOG_CHANNEL_ID)
        if channel is None:
            try:
                channel = await interaction.client.fetch_channel(RULES_LOG_CHANNEL_ID)
            except discord.HTTPException:
                return
        await channel.send(f"✅ {interaction.user.mention} agreed to the rules.")


class Rules(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    rules_group = app_commands.Group(name="rules", description="Base rules")

    @rules_group.command(name="send", description="Send the base rules embed (admin only)")
    async def rules_send(self, interaction: discord.Interaction):
        if interaction.user.id != RULES_ADMIN_USER_ID:
            await interaction.response.send_message(
                "You don't have permission to use this command.", ephemeral=True
            )
            return

        embed = discord.Embed(title=RULES_TITLE, description=RULES_BODY, color=EMBED_COLOR)
        await interaction.response.send_message(embed=embed, view=RulesView())


async def setup(bot: commands.Bot):
    await bot.add_cog(Rules(bot))
    # Re-register the persistent view on every startup so old "Agree" buttons
    # (from before a restart) keep responding.
    bot.add_view(RulesView())
