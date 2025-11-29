import logging
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from typing import Optional, Dict

from config import ROLE_HELPER, ROLE_STAFF, SERVER_ROLES

class DeclineModal(discord.ui.Modal, title="Decline Application"):
    def __init__(self, applicant: discord.Member, original_message: discord.Message):
        super().__init__()
        self.applicant = applicant
        self.original_message = original_message
        self.reason = discord.ui.TextInput(label="Reason for Rejection", style=discord.TextStyle.paragraph, max_length=500)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # Update Embed
        embed = self.original_message.embeds[0]
        embed.color = 0xE74C3C  # Red
        embed.add_field(name="Status", value=f"Declined by {interaction.user.mention}\nReason: {self.reason.value}", inline=False)
        
        await self.original_message.edit(embed=embed, view=None)
        
        # DM User
        try:
            await self.applicant.send(f"Your staff application has been **declined**.\nReason: {self.reason.value}")
        except discord.Forbidden:
            pass # Can't DM user
            
        await interaction.response.send_message("Application declined.", ephemeral=True)


class ApplicationReviewView(discord.ui.View):
    def __init__(self, applicant_id: int, server_name: str):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.server_name = server_name

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="app_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        guild = interaction.guild
        logging.info(f"Attempting to accept application for User ID: {self.applicant_id} in Guild: {guild.name} ({guild.id})")
        
        member = guild.get_member(self.applicant_id)
        if not member:
            logging.warning(f"User {self.applicant_id} not found in cache. Fetching...")
            try:
                member = await guild.fetch_member(self.applicant_id)
                logging.info(f"User {self.applicant_id} successfully fetched from API.")
            except discord.NotFound:
                logging.error(f"User {self.applicant_id} NOT FOUND via API.")
                await interaction.response.send_message(f"Error: User {self.applicant_id} not found in server.", ephemeral=True)
                return
            except discord.HTTPException as e:
                logging.error(f"HTTP Exception fetching user {self.applicant_id}: {e}")
                await interaction.response.send_message(f"Failed to fetch member: {e}", ephemeral=True)
                return

        # Assign Roles
        roles_to_add = [ROLE_HELPER, ROLE_STAFF]
        server_role_id = SERVER_ROLES.get(self.server_name)
        if server_role_id:
            roles_to_add.append(server_role_id)
            
        roles = [guild.get_role(rid) for rid in roles_to_add if guild.get_role(rid)]
        
        try:
            await member.add_roles(*roles)
        except discord.Forbidden:
            await interaction.response.send_message("I do not have permission to assign these roles. Please check my role hierarchy.", ephemeral=True)
            return
        except Exception as e:
            logging.error(f"Failed to assign roles: {e}")
            await interaction.response.send_message(f"Failed to assign roles: {e}", ephemeral=True)
            return

        # Update Embed
        embed = interaction.message.embeds[0]
        embed.color = 0x2ECC71  # Green
        embed.add_field(name="Status", value=f"Accepted by {interaction.user.mention}", inline=False)
        
        await interaction.message.edit(embed=embed, view=None)
        
        # DM User
        try:
            await member.send(f"Congratulations! Your staff application for **{self.server_name}** has been **ACCEPTED**!")
        except discord.Forbidden:
            pass

        await interaction.response.send_message("Application accepted and roles assigned.", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="app_decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        guild = interaction.guild
        member = guild.get_member(self.applicant_id)
        if not member:
            try:
                member = await guild.fetch_member(self.applicant_id)
            except discord.NotFound:
                 # Even if member left, we might want to just mark it declined locally
                 embed = interaction.message.embeds[0]
                 embed.color = 0xE74C3C
                 embed.add_field(name="Status", value=f"Declined by {interaction.user.mention} (User left server)", inline=False)
                 await interaction.message.edit(embed=embed, view=None)
                 await interaction.response.send_message("Application declined (User not found).", ephemeral=True)
                 return
            except Exception:
                 pass

        await interaction.response.send_modal(DeclineModal(member, interaction.message))


class ApplicationModalPart2(discord.ui.Modal, title="Server Application (Part 2/2)"):
    def __init__(self, part1_data: Dict[str, str], channel_id: Optional[int], server_name: str):
        super().__init__()
        self.part1_data = part1_data
        self.channel_id = channel_id
        self.server_name = server_name
        
        self.past_experience = discord.ui.TextInput(label="Past experiences", style=discord.TextStyle.paragraph, required=False, max_length=500)
        self.plugin_knowledge = discord.ui.TextInput(label="Knowledge of Luck Perms PEX Essentials etc", style=discord.TextStyle.paragraph, required=False, max_length=500)
        
        self.add_item(self.past_experience)
        self.add_item(self.plugin_knowledge)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title=f"New Application - {self.server_name}",
            color=0x9B59B6,
            timestamp=datetime.now(timezone.utc),
        )
        
        # Part 1 Fields
        embed.add_field(name="IGN", value=self.part1_data.get("ign", "N/A"), inline=True)
        if self.part1_data.get("age"):
            embed.add_field(name="Age", value=self.part1_data["age"], inline=True)
        if self.part1_data.get("timezone"):
            embed.add_field(name="Timezone", value=self.part1_data["timezone"], inline=True)
        
        embed.add_field(name="Why should we accept you?", value=self.part1_data.get("reason", "N/A"), inline=False)
        if self.part1_data.get("experience"):
            embed.add_field(name="What do you bring to the team?", value=self.part1_data["experience"], inline=False)
            
        # Part 2 Fields
        if self.past_experience.value:
            embed.add_field(name="Past experiences", value=self.past_experience.value, inline=False)
        if self.plugin_knowledge.value:
            embed.add_field(name="Plugin Knowledge", value=self.plugin_knowledge.value, inline=False)

        embed.set_author(
            name=f"{interaction.user} ({interaction.user.id})",
            icon_url=getattr(interaction.user.display_avatar, "url", None),
        )

        if not self.channel_id:
            await interaction.response.send_message(
                "Thanks! However, no application channel is configured—please notify an admin.",
                ephemeral=True,
            )
            return

        try:
            channel = interaction.client.get_channel(self.channel_id) or await interaction.client.fetch_channel(self.channel_id)
            view = ApplicationReviewView(interaction.user.id, self.server_name)
            await channel.send(embed=embed, view=view)
            await interaction.response.send_message("Application submitted successfully!", ephemeral=True)
        except Exception as exc:  # noqa: BLE001
            logging.error("Failed to send application embed: %s", exc)
            await interaction.response.send_message(
                "Could not deliver application. Please try again later.",
                ephemeral=True,
            )


class ContinueApplicationView(discord.ui.View):
    def __init__(self, part1_data: Dict[str, str], channel_id: Optional[int], server_name: str):
        super().__init__(timeout=300)
        self.part1_data = part1_data
        self.channel_id = channel_id
        self.server_name = server_name

    @discord.ui.button(label="Continue to Part 2", style=discord.ButtonStyle.primary)
    async def continue_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            ApplicationModalPart2(self.part1_data, self.channel_id, self.server_name)
        )


class ApplicationModal(discord.ui.Modal, title="Server Application (Part 1/2)"):
    def __init__(self, channel_id: Optional[int], server_name: str):
        super().__init__()
        self.channel_id = channel_id
        self.server_name = server_name
        self.ign = discord.ui.TextInput(label="Minecraft IGN", placeholder="Your in-game name", max_length=32)
        self.age = discord.ui.TextInput(label="Age", placeholder="18", required=False, max_length=3)
        self.timezone = discord.ui.TextInput(label="Timezone", placeholder="e.g. UTC, EST", required=False, max_length=32)
        self.reason = discord.ui.TextInput(label="Why should we accept you? (2 sentences)", style=discord.TextStyle.paragraph, max_length=500)
        self.experience = discord.ui.TextInput(label="What do you bring to the team?", style=discord.TextStyle.paragraph, required=False, max_length=500)
        for input_field in (self.ign, self.age, self.timezone, self.reason, self.experience):
            self.add_item(input_field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        part1_data = {
            "ign": self.ign.value,
            "age": self.age.value,
            "timezone": self.timezone.value,
            "reason": self.reason.value,
            "experience": self.experience.value
        }
        
        view = ContinueApplicationView(part1_data, self.channel_id, self.server_name)
        await interaction.response.send_message(
            "Part 1 received! Please click the button below to complete the final step.",
            view=view,
            ephemeral=True
        )

class ServerSelectionSelect(discord.ui.Select):
    def __init__(self, channel_id: Optional[int]):
        options = [discord.SelectOption(label=name) for name in SERVER_ROLES.keys()]
        super().__init__(placeholder="Select the server you wish to apply for...", min_values=1, max_values=1, options=options)
        self.channel_id = channel_id

    async def callback(self, interaction: discord.Interaction) -> None:
        server_name = self.values[0]
        modal = ApplicationModal(self.channel_id, server_name)
        await interaction.response.send_modal(modal)

class ServerSelectionView(discord.ui.View):
    def __init__(self, channel_id: Optional[int]):
        super().__init__()
        self.add_item(ServerSelectionSelect(channel_id))

class Applications(commands.Cog):
    def __init__(self, bot: commands.Bot, application_channel_id: Optional[int]):
        self.bot = bot
        self.application_channel_id = application_channel_id

    @app_commands.command(name="application", description="Open the staff application form.")
    async def application(self, interaction: discord.Interaction) -> None:
        view = ServerSelectionView(self.application_channel_id)
        await interaction.response.send_message("Please select the server you are applying for:", view=view, ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    # We need to pass the application_channel_id from the bot's config/env
    # For now, we'll retrieve it from the bot instance if we attach it there,
    # or re-read it from env. Re-reading is safer for decoupling.
    import os
    application_channel_id_raw = os.getenv("APPLICATION_CHANNEL_ID")
    try:
        application_channel_id = int(application_channel_id_raw) if application_channel_id_raw else None
    except ValueError:
        application_channel_id = None
        
    await bot.add_cog(Applications(bot, application_channel_id))
