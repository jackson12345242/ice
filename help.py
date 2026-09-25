import discord
from discord import app_commands
from discord.ext import commands

EMBED_COLOR = 0x2B2D31

# ---------------------------------------------------------------------------
# Command reference. Add a new dict entry here whenever a command is added
# and it'll automatically show up in /help.
# ---------------------------------------------------------------------------
CATEGORIES = {
    "wallet": {
        "emoji": "🪙",
        "label": "Wallet",
        "blurb": "Save and look up crypto payment addresses.",
        "commands": [
            {
                "name": "/wallet add",
                "usage": "/wallet add coin:<text> address:<text> network:<text (optional)>",
                "what": "Saves one of *your* crypto payment addresses so other people can find where to send you money.",
                "params": [
                    ("coin", "Required.", "The coin you're saving an address for, e.g. `USDT`, `LTC`, `BTC`."),
                    ("address", "Required.", "The actual wallet address."),
                    ("network", "Optional.", "A network label, e.g. `BSC`, `TRC20`, `ERC20` — useful for coins like USDT that exist on multiple networks."),
                ],
                "notes": "You can run this once per coin/network you use. Each saved address shows up as its own button when someone views your wallet.",
            },
            {
                "name": "/wallet user",
                "usage": "/wallet user user:<@member (optional)>",
                "what": "Shows a person's saved payment addresses as a set of buttons — tapping a button privately reveals that address to you.",
                "params": [
                    ("user", "Optional.", "Whose addresses to view. Defaults to you if left blank."),
                ],
                "notes": "If the person hasn't saved any addresses with `/wallet add`, you'll get a message saying so instead.",
            },
        ],
    },
    "fund": {
        "emoji": "💰",
        "label": "Fund",
        "blurb": "Track the shared team fund (brainrots + money).",
        "commands": [
            {
                "name": "/fund add",
                "usage": "/fund add amount:<number (optional)> brainrot:<choice (optional)> money:<number (optional)>",
                "what": "Adds brainrots and/or cash to the shared fund. You must include at least one of `brainrot` or `money` — you can also do both at once in a single command.",
                "params": [
                    ("brainrot", "Optional.", "Which brainrot to add, picked from the dropdown list."),
                    ("amount", "Optional.", "How many of that brainrot to add. If you picked a `brainrot` but leave this blank, it defaults to 1."),
                    ("money", "Optional.", "A dollar amount to add to the fund's cash balance."),
                ],
                "notes": "Every add is posted to the fund log channel with your name attached, so there's a record of who added what.",
            },
            {
                "name": "/fund view",
                "usage": "/fund view",
                "what": "Shows the fund's current state: total money on hand, plus how many of each brainrot are currently in the fund (with thumbnails).",
                "params": [],
                "notes": None,
            },
            {
                "name": "/remove fund",
                "usage": "/remove fund type:<Brainrot|Money> amount:<number> brainrot:<choice (required if type=Brainrot)>",
                "what": "🔒 **Restricted to the fund admin.** Removes brainrots or money from the shared fund.",
                "params": [
                    ("type", "Required.", "Whether you're removing `Brainrot` or `Money`."),
                    ("amount", "Required.", "How much to remove — a quantity for brainrots, or a dollar amount for money."),
                    ("brainrot", "Required if type is Brainrot.", "Which brainrot to remove."),
                ],
                "notes": "Anyone other than the configured fund admin will get a permission-denied message. Every removal is posted to the fund log channel.",
            },
        ],
    },
    "split": {
        "emoji": "🔀",
        "label": "Split",
        "blurb": "Split the cost of a brainrot evenly across the team and verify payments on-chain.",
        "commands": [
            {
                "name": "/split start",
                "usage": "/split start brainrot:<text> total:<number>",
                "what": "Starts a new cost split for the team. The total is divided evenly across the fixed team size to work out each person's share, and posts a public embed with a button linking to the starter's saved wallet address(es).",
                "params": [
                    ("brainrot", "Required.", "What the split is for (name/description)."),
                    ("total", "Required.", "The total cost to split between the team."),
                ],
                "notes": "Only one split can be active at a time — you'll need to run `/split end` on the current one before starting another. If the person starting the split hasn't saved a wallet with `/wallet add`, the embed will flag that instead of showing a payment button.",
            },
            {
                "name": "/split end",
                "usage": "/split end",
                "what": "Ends the currently active split and posts a summary showing how many people paid and how much each confirmed payer sent.",
                "params": [],
                "notes": "If there's no active split, you'll be told there's nothing to end.",
            },
            {
                "name": "/split complete",
                "usage": "/split complete user:<@member>",
                "what": "Checks the blockchain to verify that a specific teammate has paid their share of the active split, then marks them as paid if a matching payment is found.",
                "params": [
                    ("user", "Required.", "The teammate to check."),
                ],
                "notes": (
                    "Looks for a recent LTC or USDT (BEP20) transaction from that person's saved wallet address to the "
                    "split starter's saved address, within a time window and dollar tolerance of their expected share. "
                    "Both the split starter and the payer need an address saved via `/wallet add` for this to work, and "
                    "a transaction that's already been credited to someone else won't be matched again."
                ),
            },
        ],
    },
    "payment": {
        "emoji": "💵",
        "label": "Payment",
        "blurb": "Log personal brainrot trades and cash payments, and check leaderboards.",
        "commands": [
            {
                "name": "/payment log brainrot",
                "usage": "/payment log brainrot payment_brainrot:<choice> recieved_brainrot:<text> quantity:<number (optional)> proof:<attachment (optional)>",
                "what": "Logs a brainrot-for-brainrot trade you personally made — what you paid away and what you got back.",
                "params": [
                    ("payment_brainrot", "Required.", "The brainrot you paid/gave away, picked from the dropdown."),
                    ("recieved_brainrot", "Required.", "The brainrot you received in return. Type it freely — Dragon Cannelloni and Garama/Madundung are recognized automatically, and close misspellings of known brainrots are auto-matched too."),
                    ("quantity", "Optional, default 1.", "**Only scales the brainrot you paid.** The received brainrot is always logged as 1x — e.g. if you paid 3 Dragons for 1 Cockroach, set `quantity` to 3 and it logs as `3x Dragon → 1x Cockroach`."),
                    ("proof", "Optional.", "A screenshot attachment as proof of the trade."),
                ],
                "notes": "Posts a log embed to the payment log channel and confirms privately to you.",
            },
            {
                "name": "/payment log money",
                "usage": "/payment log money money_given:<number> recieved_brainrot:<text> quantity:<number (optional)> proof:<attachment (optional)>",
                "what": "Logs a cash payment you made in exchange for a brainrot you received.",
                "params": [
                    ("money_given", "Required.", "How much money you paid."),
                    ("recieved_brainrot", "Required.", "The brainrot you received. Typed freely, same auto-matching as above."),
                    ("quantity", "Optional, default 1.", "How many of the received brainrot this payment covers."),
                    ("proof", "Optional.", "A screenshot attachment as proof of payment."),
                ],
                "notes": "Posts a log embed to the payment log channel and confirms privately to you.",
            },
            {
                "name": "/payment view",
                "usage": "/payment view user:<@member (optional)>",
                "what": "Shows a user's logged payment history: total money paid, and every brainrot they've paid out (with thumbnails).",
                "params": [
                    ("user", "Optional.", "Whose payments to view. Defaults to you if left blank."),
                ],
                "notes": None,
            },
            {
                "name": "/payment leaderboard",
                "usage": "/payment leaderboard",
                "what": "Shows two rankings you can flip between with buttons: a money leaderboard (total $ paid) and a brainrot leaderboard (ranked by a tier-weighted score of brainrots paid out).",
                "params": [],
                "notes": None,
            },
            {
                "name": "/payment remove",
                "usage": "/payment remove user:<@member> type:<Brainrot Received|Brainrot Paid|Money> brainrot:<choice (optional)> amount:<number (optional)>",
                "what": "🔒 **Restricted to the payment admin.** Adjusts or clears a user's logged payments.",
                "params": [
                    ("user", "Required.", "Whose logged payments to adjust."),
                    ("type", "Required.", "Which category to adjust: `Brainrot Received`, `Brainrot Paid`, or `Money`."),
                    ("brainrot", "Optional, brainrot types only.", "Which specific brainrot to remove. Leave blank to clear every brainrot in that category."),
                    ("amount", "Optional.", "A specific quantity/dollar amount to subtract. Leave blank to clear everything in that category instead."),
                ],
                "notes": "Anyone other than the configured payment admin will get a permission-denied message.",
            },
            {
                "name": "/brainrot received",
                "usage": "/brainrot received user:<@member (optional)>",
                "what": "Shows every brainrot a user has received, from both trades (`/payment log brainrot`) and cash payments (`/payment log money`).",
                "params": [
                    ("user", "Optional.", "Whose received brainrots to view. Defaults to you if left blank."),
                ],
                "notes": None,
            },
        ],
    },
}


def build_overview_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📖 Command Help",
        description=(
            "Pick a category from the dropdown below to see every command in it, exactly how to "
            "use it, and what each option does.\n\nQuick overview:"
        ),
        color=EMBED_COLOR,
    )
    for cat in CATEGORIES.values():
        cmd_names = ", ".join(f"`{c['name']}`" for c in cat["commands"])
        embed.add_field(
            name=f"{cat['emoji']} {cat['label']}",
            value=f"{cat['blurb']}\n{cmd_names}",
            inline=False,
        )
    embed.set_footer(text="Use the dropdown to see full details for each command.")
    return embed


def build_category_embed(key: str) -> discord.Embed:
    cat = CATEGORIES[key]
    embed = discord.Embed(
        title=f"{cat['emoji']} {cat['label']} Commands",
        description=cat["blurb"],
        color=EMBED_COLOR,
    )
    for cmd in cat["commands"]:
        lines = [f"**What it does:** {cmd['what']}", f"**Usage:** `{cmd['usage']}`"]
        if cmd["params"]:
            lines.append("**Options:**")
            for pname, req, desc in cmd["params"]:
                lines.append(f"• `{pname}` — {req} {desc}")
        if cmd["notes"]:
            lines.append(f"**Note:** {cmd['notes']}")
        value = "\n".join(lines)
        # Discord field values cap at 1024 chars; trim defensively just in case.
        if len(value) > 1024:
            value = value[:1021] + "..."
        embed.add_field(name=cmd["name"], value=value, inline=False)
    return embed


class HelpSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Overview", value="overview", emoji="📖")
        ] + [
            discord.SelectOption(label=cat["label"], value=key, emoji=cat["emoji"])
            for key, cat in CATEGORIES.items()
        ]
        super().__init__(placeholder="Choose a category...", options=options)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        embed = build_overview_embed() if value == "overview" else build_category_embed(value)
        await interaction.response.edit_message(embed=embed)


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(HelpSelect())


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="See every command and how to use it")
    async def help_command(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=build_overview_embed(), view=HelpView()
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
