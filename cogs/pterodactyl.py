import logging
import asyncio
import json
import os
import secrets
import string
import urllib.error
import discord
from discord.ext import commands, tasks
from typing import Optional, Dict, Any, List
from urllib import request, parse

from config import load_state, save_state, env_list, ROLE_ADMIN, ROLE_SENIOR_ADMIN, PTERO_ADMIN_API_KEY, PTERO_PANEL_URL
from utils import parse_time


# Constants for Subuser Creation
PTERO_CLIENT_API_KEY_SUBUSER = "ptlc_HYgu2jBfk1rGQloijWaQKONQsvdmyqAn7aMlVprs6D1"
ROLE_SUBUSER_CREATOR = 1442244395431628834

SERVER_UUIDS = {
    "sb4": "e7fa3ad0",
    "inf": "5fb1ba73",
    "gtnh": "936b4133",
    "atm10": "ad7a0275",
    "nomi": "faa84f7a",
}

STAFF_ROLE_IDS = {
    1442244395327033460: "sb4",
    1442244395327033461: "atm10",
    1442244395343544455: "nomi",
    1442244395360456751: "gtnh",
    1442244395360456750: "inf",
}

SUBUSER_PERMISSIONS = [
    "control.console",
    "control.start",
    "control.stop",
    "control.restart",
    "user.create",
    "user.read",
    "user.update",
    "user.delete",
    "file.create",
    "file.read",
    "file.update",
    "file.delete",
    "file.archive",
    "backup.create",
    "backup.read",
    "backup.delete",
    "allocation.read",
    "allocation.create",
    "allocation.update",
    "allocation.delete",
    "startup.read",
    "startup.update",
    "database.create",
    "database.read",
    "database.update",
    "database.delete",
    "schedule.create",
    "schedule.read",
    "schedule.update",
    "schedule.delete"
]

class Pterodactyl(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ptero_base_url = PTERO_PANEL_URL
        self.ptero_app_key = os.getenv("PTERO_APPLICATION_API_KEY")
        self.ptero_client_key = os.getenv("PTERO_CLIENT_API_KEY")
        self.ptero_server_identifiers = env_list("PTERO_SERVER_IDENTIFIERS")
        ptero_channel_id_raw = os.getenv("PTERO_ACTIVITY_CHANNEL_ID", "1443397300910030919")
        self.ptero_poll_seconds = int(os.getenv("PTERO_POLL_SECONDS", "30"))
        
        try:
            self.ptero_channel_id = int(ptero_channel_id_raw)
        except ValueError:
            self.ptero_channel_id = None

        if self.ptero_client_key and self.ptero_channel_id:
             self.activity_loop.start()
        elif not self.ptero_client_key:
             logging.info("Pterodactyl activity loop disabled (missing PTERO_CLIENT_API_KEY)")
        elif not self.ptero_channel_id:
             logging.info("Pterodactyl activity loop disabled (invalid PTERO_ACTIVITY_CHANNEL_ID)")

    def cog_unload(self):
        self.activity_loop.cancel()

    def ptero_request(self, path: str, *, api_key: str, params: Optional[Dict[str, Any]] = None, method: str = "GET", data: Optional[Dict[str, Any]] = None, base_url: Optional[str] = None) -> Dict[str, Any]:
        query = parse.urlencode(params or {})
        target_base = base_url or self.ptero_base_url
        url = f"{target_base.rstrip('/')}/api/application{path}"
        if query:
            url = f"{url}?{query}"

        headers = {
            "Accept": "Application/vnd.pterodactyl.v1+json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")

        req = request.Request(url, data=body, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                return json.loads(data.decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            logging.error(f"Pterodactyl API Error {e.code} on {url}: {error_body}")
            # Raise with body so it appears in Discord message
            raise Exception(f"HTTP {e.code}: {error_body[:1800]}")

    def ptero_client_request(self, path: str, *, api_key: str, params: Optional[Dict[str, Any]] = None, method: str = "GET", data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        query = parse.urlencode(params or {})
        url = f"{self.ptero_base_url.rstrip('/')}/api/client{path}"
        if query:
            url = f"{url}?{query}"

        # Debug logging
        masked_key = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "INVALID_KEY_LENGTH"
        logging.info(f"Ptero Client Req: {method} {url} | Key: {masked_key} | Data: {data}")

        headers = {
            "Accept": "Application/vnd.pterodactyl.v1+json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")

        req = request.Request(url, data=body, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                logging.info(f"Ptero Client Resp: {resp.status} | Body: {data.decode('utf-8')[:200]}...")
                return json.loads(data.decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            logging.error(f"Ptero Client HTTP Error {e.code}: {err_body}")
            raise

    def fetch_application_servers(self, api_key: str, *, per_page: int = 50) -> List[Dict[str, Any]]:
        servers: List[Dict[str, Any]] = []
        page = 1
        while True:
            params = {"page": page, "per_page": per_page}
            response = self.ptero_request("/servers", api_key=api_key, params=params)
            data = response.get("data", [])
            servers.extend(data)
            meta = response.get("meta", {}).get("pagination", {})
            if not meta.get("links", {}).get("next"):
                break
            page += 1
        return servers

    def fetch_client_server_activity(self, api_key: str, identifier: str, *, per_page: int = 50) -> List[Dict[str, Any]]:
        response = self.ptero_client_request(
            f"/servers/{identifier}/activity",
            api_key=api_key,
            params={"per_page": per_page},
        )
        return response.get("data", [])

    async def load_ptero_servers(self) -> List[Dict[str, str]]:
        servers: List[Dict[str, str]] = []
        if self.ptero_server_identifiers:
            servers = [{"identifier": ident, "name": ident} for ident in self.ptero_server_identifiers]
        elif self.ptero_app_key:
            raw_servers = await asyncio.to_thread(self.fetch_application_servers, self.ptero_app_key)
            for entry in raw_servers:
                attr = entry.get("attributes", {})
                identifier = attr.get("identifier")
                if not identifier:
                    continue
                servers.append({"identifier": identifier, "name": attr.get("name") or identifier})
        return servers

    def extract_activity_id(self, item: Dict[str, Any]) -> Optional[str]:
        attr = item.get("attributes", item)
        raw = attr.get("id") or item.get("id")
        if raw is None:
            return None
        return str(raw)

    def summarize_properties(self, props: Dict[str, Any]) -> Optional[str]:
        if not props:
            return None

        summary_parts: List[str] = []
        command = props.get("command")
        if command:
            summary_parts.append(f"Command: `{command}`")

        file_path = props.get("file")
        if file_path:
            summary_parts.append(f"File: `{file_path}`")

        directory = props.get("directory")
        files = props.get("files")
        if directory and isinstance(files, list):
            summary_parts.append(f"Deleted {len(files)} item(s) from `{directory}`")

        schedule = props.get("schedule")
        if schedule:
            summary_parts.append(f"Schedule: `{schedule}`")

        identifier = props.get("identifier")
        if identifier and not summary_parts:
            summary_parts.append(f"Identifier: `{identifier}`")

        if not summary_parts:
            simple = json.dumps(props, ensure_ascii=False)
            if len(simple) > 300:
                simple = simple[:297] + "..."
            summary_parts.append(simple)

        return "\n".join(summary_parts)

    def format_activity_embed(self, item: Dict[str, Any], fallback_server_name: Optional[str] = None) -> discord.Embed:
        attr = item.get("attributes", item)
        rel = attr.get("relationships", item.get("relationships", {})) or {}
        properties = attr.get("properties", {})

        event = attr.get("event") or attr.get("action") or "Activity"
        description = attr.get("description") or properties.get("description") or properties.get("action") or "Activity event"
        ip = attr.get("ip") or properties.get("ip")
        timestamp = parse_time(attr.get("timestamp") or attr.get("updated_at") or attr.get("created_at"))

        actor_rel = rel.get("actor", {}).get("attributes", {})
        actor = actor_rel.get("username") or actor_rel.get("email") or actor_rel.get("id")
        actor_name = actor or attr.get("actor")

        subject_rel = rel.get("subject", {}).get("attributes", {})
        server_name = (
            subject_rel.get("name")
            or subject_rel.get("hostname")
            or properties.get("server")
            or properties.get("subject")
            or fallback_server_name
        )

        embed = discord.Embed(title="Pterodactyl Activity", description=description, color=0x3498DB)
        if timestamp:
            embed.timestamp = timestamp
        embed.add_field(name="Event", value=str(event), inline=True)
        if actor_name:
            embed.add_field(name="Actor", value=str(actor_name), inline=True)
        if server_name:
            embed.add_field(name="Server", value=str(server_name), inline=False)
        if ip:
            embed.add_field(name="IP", value=str(ip), inline=True)

        details = self.summarize_properties(properties)
        if details:
            embed.add_field(name="Details", value=details, inline=False)

        embed.set_footer(text="panel activity")
        return embed

    @tasks.loop(seconds=30)
    async def activity_loop(self):
        # We need to update the interval if it changed in env, but tasks.loop doesn't support dynamic interval easily.
        # For now we stick to the init value.
        
        servers = await self.load_ptero_servers()
        if not servers:
            logging.warning("No Pterodactyl servers configured; activity loop disabled.")
            self.activity_loop.cancel()
            return

        try:
            channel = self.bot.get_channel(self.ptero_channel_id) or await self.bot.fetch_channel(self.ptero_channel_id)
        except Exception as exc:  # noqa: BLE001
            logging.error("Unable to access channel %s: %s", self.ptero_channel_id, exc)
            return

        state = load_state()
        ptero_state = state.setdefault("pterodactyl", {}).setdefault("servers", {})

        # Seed missing last_id without sending the backlog
        for server in servers:
            identifier = server["identifier"]
            server_state = ptero_state.setdefault(identifier, {})
            if "last_id" not in server_state:
                try:
                    activities = await asyncio.to_thread(
                        self.fetch_client_server_activity,
                        self.ptero_client_key,
                        identifier,
                        per_page=1,
                    )
                    if activities:
                        latest_id = self.extract_activity_id(activities[0])
                        if latest_id:
                            server_state["last_id"] = latest_id
                except Exception:  # noqa: BLE001
                    continue
        save_state(state)

        for server in servers:
            identifier = server["identifier"]
            server_state = ptero_state.setdefault(identifier, {})
            last_id = server_state.get("last_id")

            try:
                activities = await asyncio.to_thread(
                    self.fetch_client_server_activity,
                    self.ptero_client_key,
                    identifier,
                    per_page=50,
                )
            except Exception as exc:  # noqa: BLE001
                logging.exception("Failed to fetch activity for server %s: %s", identifier, exc)
                continue

            if not activities:
                continue

            newest_id = self.extract_activity_id(activities[0])
            if last_id is None and newest_id:
                server_state["last_id"] = newest_id
                save_state(state)
                continue

            new_items: List[Dict[str, Any]] = []
            for act in activities:
                act_id = self.extract_activity_id(act)
                if act_id is None:
                    continue
                if act_id == last_id:
                    break
                new_items.append(act)

            if not new_items:
                continue

            for act in reversed(new_items):
                embed = self.format_activity_embed(act, fallback_server_name=server["name"])
                await channel.send(embed=embed)

            updated_id = self.extract_activity_id(new_items[0])
            if updated_id:
                server_state["last_id"] = updated_id
                save_state(state)

    @activity_loop.before_loop
    async def before_activity_loop(self):
        await self.bot.wait_until_ready()

    @discord.app_commands.command(name="createadmin", description="Create a new admin user on the Pterodactyl panel")
    @discord.app_commands.describe(username="The username for the new account", email="The email address for the new account")
    @discord.app_commands.checks.has_any_role(ROLE_ADMIN, ROLE_SENIOR_ADMIN)
    async def create_admin(self, interaction: discord.Interaction, username: str, email: str):
        await interaction.response.defer(ephemeral=True)
        
        # Generate password
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(secrets.choice(alphabet) for i in range(16))
        
        # Create user payload
        payload = {
            "username": username,
            "email": email,
            "first_name": username,
            "last_name": "Admin",
            "password": password,
            "root_admin": True,
            "language": "en"
        }
        
        try:
            logging.info(f"Creating admin user on {PTERO_PANEL_URL} with username {username}")
            response = await asyncio.to_thread(
                self.ptero_request,
                "/users",
                api_key=PTERO_ADMIN_API_KEY,
                method="POST",
                data=payload,
                base_url=PTERO_PANEL_URL
            )
            
            if "errors" in response:
                errors = "\n".join([e.get("detail", "Unknown error") for e in response["errors"]])
                await interaction.followup.send(f"Failed to create user:\n{errors}", ephemeral=True)
                return
            
            # Check if object is user (success)
            if response.get("object") != "user":
                 # Fallback error handling if errors key missing but not success
                 await interaction.followup.send(f"Unexpected response from Pterodactyl: {json.dumps(response)}", ephemeral=True)
                 return

            user_attr = response.get("attributes", {})
            user_id = user_attr.get("id")
            
            embed = discord.Embed(title="Admin User Created", color=discord.Color.green())
            embed.add_field(name="Panel URL", value=PTERO_PANEL_URL, inline=False)
            embed.add_field(name="Username", value=username, inline=True)
            embed.add_field(name="Email", value=email, inline=True)
            embed.add_field(name="Password", value=f"||{password}||", inline=False)
            embed.set_footer(text=f"User ID: {user_id}")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logging.exception("Error creating admin user")
            await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)

    @create_admin.error
    async def create_admin_error(self, interaction: discord.Interaction, error):
        if isinstance(error, discord.app_commands.MissingAnyRole):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        else:
            await interaction.response.send_message(f"An error occurred: {str(error)}", ephemeral=True)

    @discord.app_commands.command(name="panelregister", description="Create a subuser on the Pterodactyl panel based on staff roles")
    @discord.app_commands.describe(username="The username for the new account")
    @discord.app_commands.checks.has_role(ROLE_SUBUSER_CREATOR)
    async def panel_register(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        
        # Determine staff roles
        target_servers = []
        member = interaction.user
        if not member:
            await interaction.followup.send("Could not identify user.", ephemeral=True)
            return

        for role in member.roles:
            if role.id in STAFF_ROLE_IDS:
                target_servers.append(STAFF_ROLE_IDS[role.id])
        
        if not target_servers:
            await interaction.followup.send("You do not have any recognized staff roles for panel access.", ephemeral=True)
            return

        # Generate credentials
        email = f"{username}@cl.local"
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(secrets.choice(alphabet) for i in range(16))
        
        # Create user via Application API first
        user_payload = {
            "username": username,
            "email": email,
            "first_name": username,
            "last_name": "Staff",
            "password": password,
            "language": "en"
        }

        try:
            logging.info(f"Creating user {username} via Application API")
            await asyncio.to_thread(
                self.ptero_request,
                "/users",
                api_key=PTERO_ADMIN_API_KEY,
                method="POST",
                data=user_payload,
                base_url=PTERO_PANEL_URL
            )
        except Exception as e:
            # If user already exists, we proceed.
            # We can't easily check the error code without parsing the string message from our helper
            # but usually it's 422 or similar.
            logging.warning(f"User creation failed (likely exists): {e}")

        results = []
        
        for server_key in target_servers:
            server_uuid = SERVER_UUIDS.get(server_key)
            if not server_uuid:
                results.append(f"❌ **{server_key.upper()}**: Server UUID not configured.")
                continue
                
            payload = {
                "email": email,
                "permissions": SUBUSER_PERMISSIONS
            }
            
            try:
                # We use the CLIENT API to add a subuser
                # POST /api/client/servers/{server}/users
                self.ptero_client_request(
                    f"/servers/{server_uuid}/users",
                    api_key=PTERO_CLIENT_API_KEY_SUBUSER,
                    method="POST",
                    data=payload
                )
                results.append(f"✅ **{server_key.upper()}**: Access granted.")
            except Exception as e:
                # Basic error parsing
                msg = str(e)
                if "HTTP 403" in msg:
                    msg = "Forbidden (Check bot permisisons/limit)"
                elif "HTTP 422" in msg:
                    msg = "User already exists or invalid data"
                results.append(f"⚠️ **{server_key.upper()}**: Failed - {msg}")

        # Send DM
        dm_embed = discord.Embed(title="Panel Access Created", description=f"Your panel account for **{username}** has been set up.", color=discord.Color.green())
        dm_embed.add_field(name="Panel URL", value=PTERO_PANEL_URL, inline=False)
        dm_embed.add_field(name="Username", value=email, inline=True)
        dm_embed.add_field(name="Password", value=f"||{password}||", inline=True)
        dm_embed.add_field(name="Access Summary", value="\n".join(results), inline=False)
        dm_embed.set_footer(text="Please quit and restart your browser if cannot log in.")

        try:
            await member.send(embed=dm_embed)
            dm_status = "Credentials sent via DM."
        except discord.Forbidden:
            dm_status = "Could not DM credentials. Please enable DMs."

        # Reply to interaction
        summary_embed = discord.Embed(title="Panel Registration Complete", color=discord.Color.blue())
        summary_embed.add_field(name="User", value=f"{username} ({email})", inline=True)
        summary_embed.add_field(name="Results", value="\n".join(results), inline=False)
        summary_embed.set_footer(text=dm_status)
        
        await interaction.followup.send(embed=summary_embed, ephemeral=True)

    @panel_register.error
    async def panel_register_error(self, interaction: discord.Interaction, error):
        if isinstance(error, discord.app_commands.MissingRole):
             await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        else:
             await interaction.response.send_message(f"An error occurred: {str(error)}", ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Pterodactyl(bot))



