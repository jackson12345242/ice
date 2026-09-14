import os
from dotenv import load_dotenv

load_dotenv()

# --- Secrets / environment ---
# Put your real token in a .env file (see .env.example) — never hardcode it here.
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# --- Fixed IDs from your spec ---
FUND_LOG_CHANNEL_ID = 1548407028118986923   # every /fund add and /remove fund gets logged here
FUND_ADMIN_USER_ID = 645395932812279844      # only this user can use /remove fund
BRAINROTS = {
    "dragon_cannelloni": {
        "label": "Dragon Cannelloni",
        "asset": "assets/dragon_cannelloni.png",
    },
    "garama_madundung": {
        "label": "Garama / Madundung",
        "asset": "assets/garama.png",   # using this as the display image — swap if you want a combined image instead
    },
}
EMBED_COLOR = 0x5865F2  # Discord blurple, matches the reference screenshot
