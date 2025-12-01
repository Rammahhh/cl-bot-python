import logging
import aiohttp
import asyncio
import json
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, Dict, Any, List

from config import IPS_API_URL, IPS_API_KEY, SERVER_ROLES

class Forums(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        # Trigger the sync in the background so we don't block startup
        self.bot.loop.create_task(self.sync_groups())

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    async def ips_request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not IPS_API_URL or not IPS_API_KEY:
            logging.warning("IPS_API_URL or IPS_API_KEY not set. Skipping IPS integration.")
            return {}

        url = f"{IPS_API_URL.rstrip('/')}/{endpoint.lstrip('/')}"
        auth = aiohttp.BasicAuth(IPS_API_KEY, "") # IPS uses API key as username, empty password
        
        try:
            async with self.session.request(method, url, auth=auth, data=data) as response:
                if response.status not in (200, 201):
                    text = await response.text()
                    logging.error(f"IPS API Error ({response.status}): {text}")
                    return {}
                return await response.json()
        except Exception as e:
            logging.error(f"IPS Request Failed: {e}")
            return {}

    async def sync_groups(self) -> str:
        await self.bot.wait_until_ready()
        if not IPS_API_URL or not IPS_API_KEY:
            return "IPS configuration missing."

        logging.info("Starting IPS Group Sync...")
        
        response = await self.ips_request("GET", "core/groups")
        if not response:
            return "Failed to fetch existing groups from IPS."

        existing_groups = []
        if "results" in response:
            existing_groups = response["results"]
        elif isinstance(response, list):
            existing_groups = response
        
        existing_names = {g["name"].lower() for g in existing_groups if "name" in g}
        
        missing_groups = []
        
        # 2. Iterate and Check
        for server_name in SERVER_ROLES.keys():
            target_group_name = f"{server_name} Staff"
            
            if target_group_name.lower() in existing_names:
                logging.info(f"IPS Group '{target_group_name}' exists.")
                continue

            logging.warning(f"IPS Group '{target_group_name}' is MISSING.")
            missing_groups.append(target_group_name)

        logging.info("IPS Group Sync Complete.")
        
        if missing_groups:
            msg = "**Sync Complete.**\n\n**Missing Groups** (Please create these manually in IPS AdminCP):\n"
            msg += "\n".join(f"- {g}" for g in missing_groups)
            return msg
        else:
            return "Sync Complete. All groups exist."

    async def get_ips_group_ids(self) -> Dict[str, int]:
        """Returns a mapping of Group Name (lower) -> Group ID."""
        response = await self.ips_request("GET", "core/groups")
        if not response:
            return {}
        
        groups = []
        if "results" in response:
            groups = response["results"]
        elif isinstance(response, list):
            groups = response
            
        return {g["name"].lower(): g["id"] for g in groups if "name" in g and "id" in g}

    async def find_forum_user(self, name: str) -> Optional[Dict[str, Any]]:
        """Finds a forum user by name (case-insensitive search via API)."""
        # API expects 'name' parameter.
        response = await self.ips_request("GET", "core/members", data={"name": name})
        if not response:
            return None
            
        results = []
        if "results" in response:
            results = response["results"]
        elif isinstance(response, list):
            results = response
            
        # Exact match check (case-insensitive) just to be safe
        for user in results:
            if user.get("name", "").lower() == name.lower():
                return user
        return None

    async def add_user_to_group(self, user_id: int, group_id: int) -> bool:
        """Adds a user to a secondary group."""
        # 1. Get current user to find existing groups
        user_data = await self.ips_request("GET", f"core/members/{user_id}")
        if not user_data:
            return False
            
        current_secondary = user_data.get("secondaryGroups", [])
        # Ensure it's a list of ints
        current_secondary = [int(g) for g in current_secondary]
        
        if group_id in current_secondary:
            return True # Already in group
            
        current_secondary.append(group_id)
        
        # 2. Update user
        # Endpoint: POST /core/members/{id}
        # Payload: {"secondaryGroups": [id, id, ...]}
        # IPS API often expects comma-separated string for arrays in form-data if not using array syntax
        # Let's try sending as a list first, but log it.
        
        logging.info(f"Updating user {user_id} groups to: {current_secondary}")
        
        # Try comma-separated string, which is common for IPS APIs
        payload = {"secondaryGroups": ",".join(map(str, current_secondary))}
        
        response = await self.ips_request("POST", f"core/members/{user_id}", data=payload)
        
        logging.info(f"Update response for {user_id}: {json.dumps(response)}")
        
        # Verify if update actually happened
        if response and "secondaryGroups" in response:
            new_groups = [int(g) for g in response["secondaryGroups"]]
            if group_id in new_groups:
                return True
            else:
                logging.error(f"API returned success but group {group_id} is NOT in new groups: {new_groups}")
                return False
                
        return bool(response)

    async def sync_users(self, interaction: discord.Interaction) -> str:
        """Syncs Discord staff to IPS groups."""
        from config import SERVER_ROLES, ROLE_TAGS, ROLE_STAFF
        
        # 1. Get Group IDs
        group_map = await self.get_ips_group_ids()
        if not group_map:
            return "Failed to fetch IPS groups. Cannot sync users."
            
        guild = interaction.guild
        if not guild:
            return "Guild not found."
            
        synced_count = 0
        failed_count = 0
        not_found_count = 0
        
        # 2. Iterate Discord Members
        for member in guild.members:
            # Must have generic STAFF role
            if not any(r.id == ROLE_STAFF for r in member.roles):
                continue
                
            # Determine target groups based on roles
            target_group_ids = []
            for role in member.roles:
                # Check if this role corresponds to a server (from SERVER_ROLES)
                # We need to reverse lookup SERVER_ROLES (Name -> ID) to find the Name
                # But SERVER_ROLES is Name -> ID.
                # Let's check if role.id is in SERVER_ROLES.values()
                
                # Optimization: Pre-calculate Role ID -> Group Name
                # But we can just iterate.
                for s_name, s_role_id in SERVER_ROLES.items():
                    if role.id == s_role_id:
                        # This member has this server role.
                        # Target Group Name = "{s_name} Staff"
                        target_name = f"{s_name} Staff".lower()
                        if target_name in group_map:
                            target_group_ids.append(group_map[target_name])
            
            if not target_group_ids:
                continue

            # 3. Find Forum User
            # Parse name from nickname: "[TAG] Name" -> "Name"
            display_name = member.display_name
            clean_name = display_name
            
            # Use ROLE_TAGS logic to strip tag if present
            parts = display_name.split(" ", 1)
            if len(parts) > 1 and parts[0].startswith("[") and parts[0].endswith("]"):
                 clean_name = parts[1]
            
            forum_user = await self.find_forum_user(clean_name)
            if not forum_user:
                logging.warning(f"User '{clean_name}' (Discord: {member.id}) not found on forum.")
                not_found_count += 1
                continue
                
            # 4. Sync Groups
            user_id = forum_user["id"]
            user_success = True
            for gid in target_group_ids:
                if not await self.add_user_to_group(user_id, gid):
                    user_success = False
                    logging.error(f"Failed to add user {clean_name} to group {gid}")
            
            if user_success:
                synced_count += 1
            else:
                failed_count += 1
                
        return f"User Sync Complete.\nSynced: {synced_count}\nNot Found: {not_found_count}\nFailed: {failed_count}"

    @app_commands.command(name="syncforums", description="Manually trigger IPS group and user synchronization.")
    async def syncforums(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        
        # Optional: Check for admin permissions
        from config import ROLE_ADMIN
        has_admin = any(role.id == ROLE_ADMIN for role in interaction.user.roles)
        if not has_admin:
            await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
            return

        # 1. Sync Groups (Check existence)
        group_status = await self.sync_groups()
        
        # 2. Sync Users
        await interaction.followup.send(f"{group_status}\n\nStarting User Sync...", ephemeral=True)
        user_status = await self.sync_users(interaction)
        
        await interaction.followup.send(user_status, ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Forums(bot))
