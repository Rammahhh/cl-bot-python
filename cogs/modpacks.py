import logging
import asyncio
import json
import discord
from discord import app_commands, ui
from discord.ext import commands
from typing import Optional, Dict, Any, List
from urllib import request, parse

from config import BASE_URL, GAME_ID, MODPACK_CLASS_ID, DEFAULT_MOD_SLUG, get_env_var, env_list
from utils import parse_file_date

class Modpacks(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api_key = get_env_var("CURSEFORGE_API_KEY", required=True)
        self.monitors = self._setup_monitors()

    def _setup_monitors(self) -> List[Dict[str, Any]]:
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
            mod_id = int(mod_id_raw) if mod_id_raw else self.fetch_mod_id(slug)
            monitors.append({"slug": slug, "id": mod_id})
        
        logging.info("Ready to serve slash command for mods: %s", ", ".join(f"{m['slug']} (id={m['id']})" for m in monitors))
        return monitors

    def curseforge_request(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        query = parse.urlencode(params or {})
        url = f"{BASE_URL}{path}"
        if query:
            url = f"{url}?{query}"

        headers = {
            "Accept": "application/json",
            "x-api-key": self.api_key,
        }
        req = request.Request(url, headers=headers, method="GET")

        with request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            return json.loads(data.decode("utf-8"))

    def fetch_mod_id(self, slug: str) -> int:
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
        by_slug = self.curseforge_request("/mods/search", params={**params_common, "slug": slug}).get("data", [])
        candidate = pick_mod(by_slug)

        if not candidate:
            # Fallback to a fuzzy search.
            search = self.curseforge_request(
                "/mods/search",
                params={**params_common, "searchFilter": slug},
            ).get("data", [])
            candidate = pick_mod(search)

        if not candidate:
            raise RuntimeError(f"No mods found for slug '{slug}'")

        chosen_slug = candidate.get("slug")
        if chosen_slug and chosen_slug.lower() != slug.lower():
            logging.warning("Exact slug '%s' not found, using closest match '%s'", slug, chosen_slug)
        return int(candidate["id"])

    def fetch_mod_files(self, mod_id: int, page_size: int = 50) -> List[Dict[str, Any]]:
        params = {"index": 0, "pageSize": page_size}
        response = self.curseforge_request(f"/mods/{mod_id}/files", params=params)
        return response.get("data", [])

    def fetch_file(self, mod_id: int, file_id: int) -> Dict[str, Any]:
        response = self.curseforge_request(f"/mods/{mod_id}/files/{file_id}")
        return response.get("data") or {}

    def looks_like_server_file(self, file_obj: Dict[str, Any]) -> bool:
        name = (file_obj.get("displayName") or file_obj.get("fileName") or "").lower()
        return bool(
            file_obj.get("isServerPack")
            or "server" in name
            or file_obj.get("parentProjectFileId")
        )

    def server_pack_list(self, mod_id: int, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        files = self.fetch_mod_files(mod_id)
        server_files: List[Dict[str, Any]] = []
        seen_ids: set[int] = set()
        to_fetch: set[int] = set()

        for f in files:
            fid = int(f["id"])
            if self.looks_like_server_file(f):
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
                fetched = self.fetch_file(mod_id, ref_id)
            except Exception as exc:  # noqa: BLE001
                logging.warning("Failed to fetch referenced server pack %s: %s", ref_id, exc)
                continue

            if fetched and self.looks_like_server_file(fetched):
                server_files.append(fetched)
                seen_ids.add(ref_id)

        server_files.sort(key=lambda f: parse_file_date(f["fileDate"]), reverse=True)
        if limit:
            server_files = server_files[:limit]
        return server_files

    def format_summary(self, mod_name: str, files: List[Dict[str, Any]], max_items: int = 3) -> tuple[discord.Embed, ui.View]:
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

        return embed, view

    async def build_summaries(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for monitor in self.monitors:
            try:
                server_files = await asyncio.to_thread(self.server_pack_list, monitor["id"], limit=10)
                if not server_files:
                    results.append({"slug": monitor["slug"], "error": "No server pack files found."})
                    continue
                mod_name = server_files[0].get("projectName") or monitor["slug"]
                embed, view = self.format_summary(mod_name, server_files, max_items=3)
                results.append({"slug": monitor["slug"], "embed": embed, "view": view})
            except Exception as exc:  # noqa: BLE001
                logging.exception("Failed to build summary for %s", monitor["slug"])
                results.append({"slug": monitor["slug"], "error": f"Error fetching data: {exc}"})
        return results

    @app_commands.command(name="packsupdate", description="Show the latest server pack files for configured modpacks.")
    async def packsupdate(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        results = await self.build_summaries()

        for result in results:
            if "error" in result:
                await interaction.followup.send(f"{result['slug']}: {result['error']}", ephemeral=True)
            else:
                await interaction.followup.send(embed=result["embed"], view=result["view"])

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Modpacks(bot))
