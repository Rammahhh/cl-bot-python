#!/usr/bin/env python3
"""
Slash command bot: Main entry point.
Loads extensions from cogs/ directory.
"""

import asyncio
import logging
import os
import discord
from discord.ext import commands

from config import load_dotenv, get_env_var

# Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

class PackBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Load Cogs
        initial_extensions = [
            "cogs.applications",
            "cogs.migration",
            "cogs.modpacks",
            "cogs.staff",
            "cogs.forums",
        ]
        
        for ext in initial_extensions:
            try:
                await self.load_extension(ext)
                logging.info(f"Loaded extension: {ext}")
            except Exception as e:
                logging.exception(f"Failed to load extension {ext}")

        # Sync Slash Commands
        await self.tree.sync()
        logging.info("Synced slash commands.")

    async def on_ready(self):
        logging.info(f"Bot connected as {self.user}")
        logging.info(f"Connected to {len(self.guilds)} guilds.")
        for g in self.guilds:
            logging.info(f"Guild: {g.name} (ID: {g.id}) - Members: {g.member_count}")

def main():
    load_dotenv()
    discord_token = get_env_var("DISCORD_TOKEN", required=True)
    
    bot = PackBot()
    bot.run(discord_token)

if __name__ == "__main__":
    main()
