# CurseForge Server Pack Slash Bot

Discord slash command `/packsupdate` that posts embeds for the latest server packs of configured CurseForge modpacks (defaults: StoneBlock 4 and All the Mods 10).

## Setup
- Install deps (user-level is fine): `python3 -m pip install --user discord.py`
- Copy `.env.example` to `.env` and fill in:
  - `CURSEFORGE_API_KEY` – your CurseForge API key.
  - `DISCORD_TOKEN` – your Discord bot token.
  - Optional: `CURSEFORGE_MOD_SLUGS` (defaults to `ftb-stoneblock-4,all-the-mods-10`), `CURSEFORGE_MOD_IDS` (matching ids to skip lookup), legacy `CURSEFORGE_MOD_SLUG`/`CURSEFORGE_MOD_ID` for single mod.
  - For Pterodactyl activity relays: `PTERO_BASE_URL`, `PTERO_CLIENT_API_KEY`, `PTERO_ACTIVITY_CHANNEL_ID`, `PTERO_POLL_SECONDS` (defaults to 30), optionally `PTERO_SERVER_IDENTIFIERS`. If you also set `PTERO_APPLICATION_API_KEY`, the bot can auto-discover servers to monitor.
  - For the application form: `APPLICATION_CHANNEL_ID` (channel where submissions should be forwarded).
- Invite the bot with the `applications.commands` scope (and `bot` if you also want it online) so `/packsupdate` is available.

## Run
- Start the bot: `python3 bot.py`
- In Discord:
  - `/packsupdate` sends embeds with the latest three server pack files for each configured modpack.
  - `/application` opens a Discord modal (form) so applicants can submit IGN/age/timezone/reason/experience; responses are forwarded as embeds to `APPLICATION_CHANNEL_ID`.
- If the Pterodactyl vars are set, the bot polls each configured server’s client activity feed and streams new events as embeds to `PTERO_ACTIVITY_CHANNEL_ID`.
