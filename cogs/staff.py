import logging
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from config import ROLE_TAGS

class Staff(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="staffsync", description="Sync your nickname with your staff role tag.")
    async def staffsync(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        
        user = interaction.user
        if not isinstance(user, discord.Member):
            await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
            return

        # Find the highest priority role tag (or just the first one found)
        # We iterate through the user's roles and check if any match our configured tags
        found_tag = None
        for role in user.roles:
            if role.id in ROLE_TAGS:
                found_tag = ROLE_TAGS[role.id]
                break # Stop at the first match. 
                # Note: Discord roles are usually ordered by position, but user.roles might not be.
                # If priority matters, we might need to sort user.roles or iterate ROLE_TAGS.
                # For now, first match is a reasonable start.

        if not found_tag:
            await interaction.followup.send("You do not have a configured staff role.", ephemeral=True)
            return

        current_nick = user.display_name
        
        # Check if already tagged correctly
        if current_nick.startswith(found_tag):
            await interaction.followup.send(f"Your nickname is already synced: `{current_nick}`", ephemeral=True)
            return

        # If the user has a different tag (e.g. promoted/demoted/switched), we should probably replace it.
        # But simply prepending is the requested behavior: "update their username from being whatever it is currently to [SERVERSTAFFROLE] Namehere"
        # However, if they already have *another* tag, we might end up with "[SB4] [ATM10] Ramma".
        # Let's try to be smart: if it starts with '[' and contains ']', maybe strip it?
        # For now, let's stick to the simple requirement: Set to "[TAG] Name".
        # But "Name" should probably be their "base" name. 
        # If their nick is currently "Ramma", it becomes "[SB4] Ramma".
        # If it is already "[SB4] Ramma", we caught that above.
        # If it is "[ATM10] Ramma" and they are now SB4, we probably want "[SB4] Ramma", not "[SB4] [ATM10] Ramma".
        
        # Simple heuristic: Split by space, if first part looks like a tag, drop it.
        new_base_name = current_nick
        parts = current_nick.split(" ", 1)
        if len(parts) > 1 and parts[0].startswith("[") and parts[0].endswith("]"):
             new_base_name = parts[1]
        
        new_nick = f"{found_tag} {new_base_name}"

        # Discord nickname limit is 32 chars
        if len(new_nick) > 32:
            # Truncate the base name to fit
            # len(tag) + 1 (space) + len(base) <= 32
            # len(base) <= 32 - len(tag) - 1
            allowed_len = 32 - len(found_tag) - 1
            new_base_name = new_base_name[:allowed_len]
            new_nick = f"{found_tag} {new_base_name}"

        try:
            await user.edit(nick=new_nick)
            await interaction.followup.send(f"Nickname updated to: `{new_nick}`", ephemeral=True)
            logging.info(f"Updated nickname for {user.id} to {new_nick}")
        except discord.Forbidden:
            await interaction.followup.send("I do not have permission to change your nickname.", ephemeral=True)
            logging.warning(f"Failed to update nickname for {user.id}: Forbidden")
        except Exception as e:
            await interaction.followup.send("An error occurred while updating your nickname.", ephemeral=True)
            logging.error(f"Failed to update nickname for {user.id}: {e}")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Staff(bot))
