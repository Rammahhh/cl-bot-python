import logging
import aiohttp
import asyncio
import json
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

    async def sync_groups(self):
        await self.bot.wait_until_ready()
        if not IPS_API_URL or not IPS_API_KEY:
            return

        logging.info("Starting IPS Group Sync...")
        
        # 1. Fetch existing groups
        # IPS API pagination might be needed, but for now let's assume one page or just check the first page.
        # /core/groups usually returns a list.
        response = await self.ips_request("GET", "core/groups")
        if not response:
            return

        # IPS API structure for groups list: {"page": 1, "results": [...]} or just [...] depending on version/endpoint
        # Let's handle both just in case, though standard IPS 4 REST is usually wrapped in results for lists.
        existing_groups = []
        if "results" in response:
            existing_groups = response["results"]
        elif isinstance(response, list):
            existing_groups = response
        
        existing_names = {g["name"].lower() for g in existing_groups if "name" in g}
        
        # 2. Iterate and Create
        for server_name in SERVER_ROLES.keys():
            target_group_name = f"{server_name} Staff"
            
            if target_group_name.lower() in existing_names:
                logging.info(f"IPS Group '{target_group_name}' already exists.")
                continue

            logging.info(f"Creating IPS Group '{target_group_name}'...")
            
            # Create Group
            # Endpoint: POST /core/groups
            # Payload: {"name": "Group Name"}
            # Note: IPS API might require more fields or might not support creation via this endpoint directly 
            # if it's not fully exposed. But we proceed as per plan.
            create_response = await self.ips_request("POST", "core/groups", data={"name": target_group_name})
            
            if create_response:
                logging.info(f"Successfully created IPS Group: {target_group_name}")
            else:
                logging.error(f"Failed to create IPS Group: {target_group_name}")

        logging.info("IPS Group Sync Complete.")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Forums(bot))
