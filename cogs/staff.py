import logging
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, Tuple

from config import ROLE_TAGS, SKIP_SYNC_ROLES, ROLE_STAFF, ROLE_ADMIN

class Staff(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _sync_member(self, member: discord.Member) -> Tuple[bool, str]:
        """
        Syncs a single member's nickname.
        Returns (success, message).
        """
        # Check for skip roles
        for role in member.roles:
            if role.id in SKIP_SYNC_ROLES:
                return False, "Skipped (Protected Role)"

        # Find the highest priority role tag
        found_tag = None
        for role in member.roles:
            if role.id in ROLE_TAGS:
                found_tag = ROLE_TAGS[role.id]
                break 

        if not found_tag:
            return False, "No staff role tag found"

        current_nick = member.display_name
        
        # Check if already tagged correctly
        if current_nick.startswith(found_tag):
            return True, "Already synced"

        new_base_name = current_nick
        parts = current_nick.split(" ", 1)
        if len(parts) > 1 and parts[0].startswith("[") and parts[0].endswith("]"):
             new_base_name = parts[1]
        
        new_nick = f"{found_tag} {new_base_name}"

        if len(new_nick) > 32:
            allowed_len = 32 - len(found_tag) - 1
            new_base_name = new_base_name[:allowed_len]
            new_nick = f"{found_tag} {new_base_name}"

        try:
            await member.edit(nick=new_nick)
            logging.info(f"Updated nickname for {member.id} to {new_nick}")
            return True, f"Updated to {new_nick}"
        except discord.Forbidden:
            logging.warning(f"Failed to update nickname for {member.id}: Forbidden")
            return False, "Missing Permissions"
        except Exception as e:
            logging.error(f"Failed to update nickname for {member.id}: {e}")
            return False, f"Error: {e}"

    @app_commands.command(name="staffsync", description="Sync your nickname with your staff role tag.")
    async def staffsync(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        
        user = interaction.user
        if not isinstance(user, discord.Member):
            await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
            return

        success, msg = await self._sync_member(user)
        if success:
            if msg == "Already synced":
                 await interaction.followup.send(f"Your nickname is already synced.", ephemeral=True)
            else:
                 await interaction.followup.send(f"Nickname updated successfully.", ephemeral=True)
        else:
            await interaction.followup.send(f"Failed to sync: {msg}", ephemeral=True)

    @app_commands.command(name="staffsyncall", description="Sync all staff nicknames (Admin only).")
    async def staffsyncall(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        
        if not isinstance(interaction.user, discord.Member):
             await interaction.followup.send("Server only.", ephemeral=True)
             return

        # Check for Admin role
        has_admin = any(role.id == ROLE_ADMIN for role in interaction.user.roles)
        if not has_admin:
            await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
            return

        guild = interaction.guild
        await interaction.followup.send("Starting mass sync... this may take a while.", ephemeral=True)
        
        count_updated = 0
        count_skipped = 0
        count_failed = 0
        
        # Iterate over all members. 
        # Note: guild.members might be incomplete if intents are not set or chunking hasn't happened.
        # Ideally we should chunk the guild first.
        if not guild.chunked:
            await guild.chunk()
            
        for member in guild.members:
            # Check if they have the generic Staff role first to filter down
            has_staff_role = any(role.id == ROLE_STAFF for role in member.roles)
            if not has_staff_role:
                continue
                
            success, msg = await self._sync_member(member)
            if success:
                if msg != "Already synced":
                    count_updated += 1
            else:
                if msg == "Skipped (Protected Role)":
                    count_skipped += 1
                elif msg == "No staff role tag found":
                    pass # Just a staff member without a specific server role?
                else:
                    count_failed += 1
                    
        await interaction.followup.send(
            f"Mass sync complete.\nUpdated: {count_updated}\nSkipped (Protected): {count_skipped}\nFailed: {count_failed}", 
            ephemeral=True
        )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Staff(bot))
