import asyncio
import logging

import discord
from discord.ext import commands

import database as db
from config import BOT_TOKEN

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

INITIAL_COGS = ["wallet", "fund", "split", "payment"]


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    synced = await bot.tree.sync()
    print(f"Synced {len(synced)} slash commands.")


async def main():
    await db.init_db()
    async with bot:
        for cog in INITIAL_COGS:
            await bot.load_extension(cog)
        if not BOT_TOKEN:
            raise RuntimeError(
                "DISCORD_BOT_TOKEN is not set. Copy .env.example to .env and add your bot token, "
                "or export it as an environment variable."
            )
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
