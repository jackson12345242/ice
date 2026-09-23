import os
from dotenv import load_dotenv

load_dotenv()

# --- Secrets / environment ---
# Put your real token in a .env file (see .env.example) — never hardcode it here.
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# --- Fixed IDs from your spec ---
FUND_LOG_CHANNEL_ID = 1548407028118986923   # every /fund add and /remove fund gets logged here
FUND_ADMIN_USER_ID = 645395932812279844      # only this user can use /remove fund

# --- Brainrot catalog ---
# key = value used internally / in the DB, label = shown in the dropdown, asset = icon file in /assets
BRAINROTS = {
    "dragon_cannelloni": {
        "label": "Dragon Cannelloni",
        "asset": "assets/dragon_cannelloni.png",
    },
    "garama_madundung": {
        "label": "Garama / Madundung",
        "asset": "assets/garama.png",
    },
}

EMBED_COLOR = 0x5865F2  # Discord blurple, matches the reference screenshot

# --- Split settings ---
SPLIT_TEAM_SIZE = 13  # <-- update this whenever the team size changes
SPLIT_LOG_CHANNEL_ID = FUND_LOG_CHANNEL_ID  # change this if you want splits logged somewhere else
SPLIT_PAYMENT_TOLERANCE = 0.03  # 3% wiggle room for price moves / network fees
SPLIT_PAYMENT_WINDOW_MINUTES = 15  # only count transactions within this many minutes of now

# --- Blockchain lookups ---
BLOCKCYPHER_TOKEN = os.getenv("BLOCKCYPHER_TOKEN", "")
BSCSCAN_API_KEY = os.getenv("BSCSCAN_API_KEY", "")  # optional — public endpoint works fine without one
USDT_BEP20_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"

# --- Payment tracking ---
PAYMENT_LOG_CHANNEL_ID = 155211188756965798  # every /payment log goes here
PAYMENT_ADMIN_USER_ID = FUND_ADMIN_USER_ID  # only this user can use /payment remove

# tier = relative quality, used to weight the brainrot leaderboard (higher = better)
PAYMENT_BRAINROTS = {
    "dragon_cannelloni": {"label": "Dragon Cannelloni", "asset": "assets/dragon_cannelloni.png", "tier": 3},
    "madundung": {"label": "Madundung", "asset": "assets/madundung.png", "tier": 2},
    "garama": {"label": "Garama", "asset": "assets/garama.png", "tier": 1},
    "other": {"label": "Other", "asset": None, "tier": 0},
}
