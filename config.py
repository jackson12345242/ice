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
    "garama": {
        "label": "Garama",
        "asset": "assets/garama.png",
    },
    "madundung": {
        "label": "Madundung",
        "asset": "assets/madundung.png",
    },
}

EMBED_COLOR = 0x5865F2  # Discord blurple, matches the reference screenshot
