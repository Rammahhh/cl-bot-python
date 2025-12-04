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

from config import load_state, save_state, env_list, ROLE_ADMIN, PTERO_ADMIN_API_KEY, PTERO_PANEL_URL
from utils import parse_time

class Pterodactyl(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ptero_base_url = os.getenv("PTERO_BASE_URL", "https://panel.craftersland.org")
        self.ptero_app_key = os.getenv("PTERO_APPLICATION_API_KEY")
        self.ptero_client_key = os.getenv("PTERO_CLIENT_API_KEY")
        self.ptero_server_identifiers = env_list("PTERO_SERVER_IDENTIFIERS")
        ptero_channel_id_raw = os.getenv("PTERO_ACTIVITY_CHANNEL_ID", "1444399741998862597")
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
            raise

    def ptero_client_request(self, path: str, *, api_key: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        query = parse.urlencode(params or {})
        url = f"{self.ptero_base_url.rstrip('/')}/api/client{path}"
        if query:
            url = f"{url}?{query}"

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        req = request.Request(url, headers=headers, method="GET")
        with request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            return json.loads(data.decode("utf-8"))

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
    @discord.app_commands.checks.has_role(ROLE_ADMIN)
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
        if isinstance(error, discord.app_commands.MissingRole):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        else:
            await interaction.response.send_message(f"An error occurred: {str(error)}", ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Pterodactyl(bot))
