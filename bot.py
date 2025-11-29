#!/usr/bin/env python3
"""
Slash command bot: /packsupdate posts embeds for the latest server packs of configured modpacks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import parse, request

import discord
from discord import app_commands, ui

BASE_URL = "https://api.curseforge.com/v1"

GAME_ID = 432  # Minecraft
MODPACK_CLASS_ID = 4471

DEFAULT_MOD_SLUG = "ftb-stoneblock-4"

STATE_FILE_ENV = "STATE_FILE"
DEFAULT_STATE_FILE = Path.home() / ".packbot_state.json"


def load_dotenv(path: Path = Path(".env")) -> None:
    """Lightweight .env loader that sets env vars only if they are missing."""
    if not path.exists():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def get_env_var(key: str, *, default: Optional[str] = None, required: bool = False) -> str:
    value = os.getenv(key, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


def env_list(key: str) -> List[str]:
    raw = os.getenv(key)
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def resolve_state_path() -> Path:
    raw = os.getenv(STATE_FILE_ENV)
    path = Path(raw).expanduser() if raw else DEFAULT_STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_state(path: Optional[Path] = None) -> Dict[str, Any]:
    target = path or resolve_state_path()
    if not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text())
        return payload if isinstance(payload, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_state(state: Dict[str, Any], path: Optional[Path] = None) -> None:
    target = path or resolve_state_path()
    target.write_text(json.dumps(state, indent=2))


def curseforge_request(path: str, *, params: Optional[Dict[str, Any]] = None, api_key: str = "") -> Dict[str, Any]:
    query = parse.urlencode(params or {})
    url = f"{BASE_URL}{path}"
    if query:
        url = f"{url}?{query}"

    headers = {
        "Accept": "application/json",
        "x-api-key": api_key,
    }
    req = request.Request(url, headers=headers, method="GET")

    with request.urlopen(req, timeout=30) as resp:
        data = resp.read()
        return json.loads(data.decode("utf-8"))


def fetch_mod_id(slug: str, *, api_key: str) -> int:
    """Find the mod id for a slug, preferring exact slug matches."""

    def pick_mod(mods: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        slug_lower = slug.lower()
        for mod in mods:
            if mod.get("slug", "").lower() == slug_lower:
                return mod
        for mod in mods:
            if slug_lower in mod.get("slug", "").lower():
                return mod
        return mods[0] if mods else None

    params_common = {"gameId": GAME_ID, "classId": MODPACK_CLASS_ID}

    # First, try an exact slug lookup if the API supports it.
    by_slug = curseforge_request("/mods/search", params={**params_common, "slug": slug}, api_key=api_key).get("data", [])
    candidate = pick_mod(by_slug)

    if not candidate:
        # Fallback to a fuzzy search.
        search = curseforge_request(
            "/mods/search",
            params={**params_common, "searchFilter": slug},
            api_key=api_key,
        ).get("data", [])
        candidate = pick_mod(search)

    if not candidate:
        raise RuntimeError(f"No mods found for slug '{slug}'")

    chosen_slug = candidate.get("slug")
    if chosen_slug and chosen_slug.lower() != slug.lower():
        logging.warning("Exact slug '%s' not found, using closest match '%s'", slug, chosen_slug)
    return int(candidate["id"])


def fetch_mod_files(mod_id: int, *, api_key: str, page_size: int = 50) -> List[Dict[str, Any]]:
    params = {"index": 0, "pageSize": page_size}
    response = curseforge_request(f"/mods/{mod_id}/files", params=params, api_key=api_key)
    return response.get("data", [])


def fetch_file(mod_id: int, file_id: int, *, api_key: str) -> Dict[str, Any]:
    response = curseforge_request(f"/mods/{mod_id}/files/{file_id}", api_key=api_key)
    return response.get("data") or {}


def parse_file_date(value: str) -> datetime:
    # API returns ISO 8601 strings that often end with Z
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)


def looks_like_server_file(file_obj: Dict[str, Any]) -> bool:
    name = (file_obj.get("displayName") or file_obj.get("fileName") or "").lower()
    return bool(
        file_obj.get("isServerPack")
        or "server" in name
        or file_obj.get("parentProjectFileId")
    )


def server_pack_list(mod_id: int, *, api_key: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    files = fetch_mod_files(mod_id, api_key=api_key)
    server_files: List[Dict[str, Any]] = []
    seen_ids: set[int] = set()
    to_fetch: set[int] = set()

    for f in files:
        fid = int(f["id"])
        if looks_like_server_file(f):
            server_files.append(f)
            seen_ids.add(fid)

        for ref_key in ("serverPackFileId", "alternateFileId"):
            ref_id = f.get(ref_key)
            if ref_id:
                to_fetch.add(int(ref_id))

    for ref_id in sorted(to_fetch):
        if ref_id in seen_ids:
            continue
        try:
            fetched = fetch_file(mod_id, ref_id, api_key=api_key)
        except Exception as exc:  # noqa: BLE001
            logging.warning("Failed to fetch referenced server pack %s: %s", ref_id, exc)
            continue

        if fetched and looks_like_server_file(fetched):
            server_files.append(fetched)
            seen_ids.add(ref_id)

    server_files.sort(key=lambda f: parse_file_date(f["fileDate"]), reverse=True)
    if limit:
        server_files = server_files[:limit]
    return server_files


def format_summary(mod_name: str, files: List[Dict[str, Any]], max_items: int = 3) -> tuple[discord.Embed, ui.View]:
    items = files[:max_items]
    embed = discord.Embed(
        title=f"{mod_name} server packs",
        description=f"Latest {len(items)} server pack files." if items else "No server pack files found.",
        color=0x2ECC71,
        timestamp=parse_file_date(items[0]["fileDate"]) if items else None,
    )

    view = ui.View()
    for idx, f in enumerate(items, start=1):
        display_name = f.get("displayName") or f.get("fileName") or f"Server pack {idx}"
        date = parse_file_date(f["fileDate"]).strftime("%Y-%m-%d %H:%M UTC")
        release_type = {1: "Release", 2: "Beta", 3: "Alpha"}.get(f.get("releaseType"), "Unknown")
        embed.add_field(name=display_name, value=f"{release_type} • {date}", inline=False)

        url = f.get("downloadUrl")
        if url and len(view.children) < 5:
            view.add_item(
                ui.Button(style=discord.ButtonStyle.link, label=display_name[:80], url=url)
            )

    if not items:
        return embed, view

    return embed, view


class ApplicationModal(discord.ui.Modal, title="Server Application"):
    def __init__(self, channel_id: Optional[int]):
        super().__init__()
        self.channel_id = channel_id
        self.ign = discord.ui.TextInput(label="Minecraft IGN", placeholder="Your in-game name", max_length=32)
        self.age = discord.ui.TextInput(label="Age", placeholder="18", required=False, max_length=3)
        self.timezone = discord.ui.TextInput(label="Timezone", placeholder="e.g. UTC, EST", required=False, max_length=32)
        self.reason = discord.ui.TextInput(label="Why do you want to join?", style=discord.TextStyle.paragraph, max_length=500)
        self.experience = discord.ui.TextInput(label="Relevant experience", style=discord.TextStyle.paragraph, required=False, max_length=500)
        for input_field in (self.ign, self.age, self.timezone, self.reason, self.experience):
            self.add_item(input_field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="New Application",
            color=0x9B59B6,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="IGN", value=self.ign.value or "N/A", inline=True)
        if self.age.value:
            embed.add_field(name="Age", value=self.age.value, inline=True)
        if self.timezone.value:
            embed.add_field(name="Timezone", value=self.timezone.value, inline=True)
        embed.add_field(name="Reason", value=self.reason.value or "N/A", inline=False)
        if self.experience.value:
            embed.add_field(name="Experience", value=self.experience.value, inline=False)
        embed.set_author(
            name=f"{interaction.user} ({interaction.user.id})",
            icon_url=getattr(interaction.user.display_avatar, "url", discord.Embed.Empty),
        )

        if not self.channel_id:
            await interaction.response.send_message(
                "Thanks! However, no application channel is configured—please notify an admin.",
                ephemeral=True,
            )
            return

        try:
            channel = interaction.client.get_channel(self.channel_id) or await interaction.client.fetch_channel(self.channel_id)
            await channel.send(embed=embed)
            await interaction.response.send_message("Application submitted!", ephemeral=True)
        except Exception as exc:  # noqa: BLE001
            logging.error("Failed to send application embed: %s", exc)
            await interaction.response.send_message(
                "Could not deliver application. Please try again later.",
                ephemeral=True,
            )


def parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def ptero_request(path: str, *, base_url: str, api_key: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    query = parse.urlencode(params or {})
    url = f"{base_url.rstrip('/')}/api/application{path}"
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


def extract_activity_id(item: Dict[str, Any]) -> Optional[str]:
    attr = item.get("attributes", item)
    raw = attr.get("id") or item.get("id")
    if raw is None:
        return None
    return str(raw)


def summarize_properties(props: Dict[str, Any]) -> Optional[str]:
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


def format_activity_embed(item: Dict[str, Any], fallback_server_name: Optional[str] = None) -> discord.Embed:
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

    details = summarize_properties(properties)
    if details:
        embed.add_field(name="Details", value=details, inline=False)

    embed.set_footer(text="panel activity")
    return embed


def fetch_application_servers(base_url: str, api_key: str, *, per_page: int = 50) -> List[Dict[str, Any]]:
    servers: List[Dict[str, Any]] = []
    page = 1
    while True:
        params = {"page": page, "per_page": per_page}
        response = ptero_request("/servers", base_url=base_url, api_key=api_key, params=params)
        data = response.get("data", [])
        servers.extend(data)
        meta = response.get("meta", {}).get("pagination", {})
        if not meta.get("links", {}).get("next"):
            break
        page += 1
    return servers


def ptero_client_request(path: str, *, base_url: str, api_key: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    query = parse.urlencode(params or {})
    url = f"{base_url.rstrip('/')}/api/client{path}"
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


def fetch_client_server_activity(base_url: str, api_key: str, identifier: str, *, per_page: int = 50) -> List[Dict[str, Any]]:
    response = ptero_client_request(
        f"/servers/{identifier}/activity",
        base_url=base_url,
        api_key=api_key,
        params={"per_page": per_page},
    )
    return response.get("data", [])


def main() -> None:
    parser = ArgumentParser(description="Slash command bot for server pack updates.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    load_dotenv()

    api_key = get_env_var("CURSEFORGE_API_KEY", required=True)
    discord_token = get_env_var("DISCORD_TOKEN", required=True)
    slug_list = env_list("CURSEFORGE_MOD_SLUGS")
    if not slug_list:
        mod_slug = get_env_var("CURSEFORGE_MOD_SLUG", default=DEFAULT_MOD_SLUG)
        slug_list = [mod_slug, "all-the-mods-10"] if mod_slug == DEFAULT_MOD_SLUG else [mod_slug]

    mod_ids_env = env_list("CURSEFORGE_MOD_IDS")
    monitors: List[Dict[str, Any]] = []
    for idx, slug in enumerate(slug_list):
        mod_id_raw = None
        if mod_ids_env and idx < len(mod_ids_env):
            mod_id_raw = mod_ids_env[idx]
        elif idx == 0:
            mod_id_raw = get_env_var("CURSEFORGE_MOD_ID")
        mod_id = int(mod_id_raw) if mod_id_raw else fetch_mod_id(slug, api_key=api_key)
        monitors.append({"slug": slug, "id": mod_id})

    logging.info("Ready to serve slash command for mods: %s", ", ".join(f"{m['slug']} (id={m['id']})" for m in monitors))

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    ptero_base_url = os.getenv("PTERO_BASE_URL", "https://panel.craftersland.org")
    ptero_app_key = os.getenv("PTERO_APPLICATION_API_KEY")
    ptero_client_key = os.getenv("PTERO_CLIENT_API_KEY")
    ptero_server_identifiers = env_list("PTERO_SERVER_IDENTIFIERS")
    ptero_channel_id_raw = os.getenv("PTERO_ACTIVITY_CHANNEL_ID", "1444078030417952900")
    ptero_poll_seconds = int(os.getenv("PTERO_POLL_SECONDS", "30"))
    try:
        ptero_channel_id = int(ptero_channel_id_raw)
    except ValueError:
        ptero_channel_id = None
    application_channel_id_raw = os.getenv("APPLICATION_CHANNEL_ID")
    try:
        application_channel_id = int(application_channel_id_raw) if application_channel_id_raw else None
    except ValueError:
        application_channel_id = None

    async def load_ptero_servers() -> List[Dict[str, str]]:
        servers: List[Dict[str, str]] = []
        if ptero_server_identifiers:
            servers = [{"identifier": ident, "name": ident} for ident in ptero_server_identifiers]
        elif ptero_app_key:
            raw_servers = await asyncio.to_thread(fetch_application_servers, ptero_base_url, ptero_app_key)
            for entry in raw_servers:
                attr = entry.get("attributes", {})
                identifier = attr.get("identifier")
                if not identifier:
                    continue
                servers.append({"identifier": identifier, "name": attr.get("name") or identifier})
        return servers

    @client.event
    async def on_ready() -> None:
        await tree.sync()
        logging.info("Bot connected as %s", client.user)
        if ptero_client_key and ptero_channel_id:
            client.loop.create_task(pterodactyl_activity_loop())
        elif not ptero_client_key:
            logging.info("Pterodactyl activity loop disabled (missing PTERO_CLIENT_API_KEY)")
        elif not ptero_channel_id:
            logging.info("Pterodactyl activity loop disabled (invalid PTERO_ACTIVITY_CHANNEL_ID)")

    async def build_summaries() -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for monitor in monitors:
            try:
                server_files = await asyncio.to_thread(server_pack_list, monitor["id"], api_key=api_key, limit=10)
                if not server_files:
                    results.append({"slug": monitor["slug"], "error": "No server pack files found."})
                    continue
                mod_name = server_files[0].get("projectName") or monitor["slug"]
                embed, view = format_summary(mod_name, server_files, max_items=3)
                results.append({"slug": monitor["slug"], "embed": embed, "view": view})
            except Exception as exc:  # noqa: BLE001
                logging.exception("Failed to build summary for %s", monitor["slug"])
                results.append({"slug": monitor["slug"], "error": f"Error fetching data: {exc}"})
        return results

    @tree.command(name="packsupdate", description="Show the latest server pack files for configured modpacks.")
    async def packsupdate(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        results = await build_summaries()

        for result in results:
            if "error" in result:
                await interaction.followup.send(f"{result['slug']}: {result['error']}", ephemeral=True)
            else:
                await interaction.followup.send(embed=result["embed"], view=result["view"])

    @tree.command(name="application", description="Open the staff application form.")
    async def application(interaction: discord.Interaction) -> None:
        modal = ApplicationModal(application_channel_id)
        await interaction.response.send_modal(modal)

    async def pterodactyl_activity_loop() -> None:
        servers = await load_ptero_servers()
        if not servers:
            logging.warning("No Pterodactyl servers configured; activity loop disabled.")
            return

        await client.wait_until_ready()
        try:
            channel = client.get_channel(ptero_channel_id) or await client.fetch_channel(ptero_channel_id)
        except Exception as exc:  # noqa: BLE001
            logging.error("Unable to access channel %s: %s", ptero_channel_id, exc)
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
                        fetch_client_server_activity,
                        ptero_base_url,
                        ptero_client_key,
                        identifier,
                        per_page=1,
                    )
                    if activities:
                        latest_id = extract_activity_id(activities[0])
                        if latest_id:
                            server_state["last_id"] = latest_id
                except Exception:  # noqa: BLE001
                    continue
        save_state(state)

        while not client.is_closed():
            for server in servers:
                identifier = server["identifier"]
                server_state = ptero_state.setdefault(identifier, {})
                last_id = server_state.get("last_id")

                try:
                    activities = await asyncio.to_thread(
                        fetch_client_server_activity,
                        ptero_base_url,
                        ptero_client_key,
                        identifier,
                        per_page=50,
                    )
                except Exception as exc:  # noqa: BLE001
                    logging.exception("Failed to fetch activity for server %s: %s", identifier, exc)
                    continue

                if not activities:
                    continue

                newest_id = extract_activity_id(activities[0])
                if last_id is None and newest_id:
                    server_state["last_id"] = newest_id
                    save_state(state)
                    continue

                new_items: List[Dict[str, Any]] = []
                for act in activities:
                    act_id = extract_activity_id(act)
                    if act_id is None:
                        continue
                    if act_id == last_id:
                        break
                    new_items.append(act)

                if not new_items:
                    continue

                for act in reversed(new_items):
                    embed = format_activity_embed(act, fallback_server_name=server["name"])
                    await channel.send(embed=embed)

                updated_id = extract_activity_id(new_items[0])
                if updated_id:
                    server_state["last_id"] = updated_id
                    save_state(state)

            await asyncio.sleep(ptero_poll_seconds)

    client.run(discord_token)


if __name__ == "__main__":
    main()
