import os
import json
from pathlib import Path
from typing import List, Optional, Dict, Any

# Constants
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

# Load environment variables immediately on import
load_dotenv()

# Role Configuration
ROLE_HELPER = 1442244395431628831
ROLE_STAFF = 1442244395431628830
ROLE_ADMIN = 1442244395452862465

SERVER_ROLES = {
    "Infinity Evolved": 1442244395360456750,
    "NomiFactory CEu": 1442244395343544455,
    "All the Mods 10": 1442244395327033461,
    "Stoneblock 4": 1442244395327033460,
    "Skyfactory 2.5": 1442244395360456747,
    "GregTech New Horizon": 1442244395360456751,
    "RLCraft": 1442244395343544453,
}

ROLE_TAGS = {
    1442244395327033460: "[SB4]",
    1442244395360456750: "[IE]",
    1442244395343544455: "[NomiFactory]",
    1442244395360456747: "[SF2.5]",
    1442244395360456751: "[GTNH]",
    1442244395327033461: "[ATM10]",
    1442244395343544453: "[RLC]",
}

SKIP_SYNC_ROLES = [
    1442244395452862465,
    1442244395452862464,
]

# IPS Integration
IPS_API_URL = os.getenv("IPS_API_URL")
IPS_API_KEY = os.getenv("IPS_API_KEY")

# Discord Configuration
GUILD_ID = os.getenv("GUILD_ID")

# Tebex Integration
TEBEX_KEYS = {
    "ATM": os.getenv("TEBEX_KEY_ATM", "70e1713be7f71470e2be2bde46c26e801b5b72ef"),
    "Nomi": os.getenv("TEBEX_KEY_NOMI", "5d3d300fcf193f18056036314b97ad512f62403d"),
    "Inf": os.getenv("TEBEX_KEY_INF", "6588413650593f03c3b22429fcef5c0cd1220270"),
    "SB4": os.getenv("TEBEX_KEY_SB4", "c1d2ba326510667c2603c4d574bc3cb422bd15f2"),
    "GTNH": os.getenv("TEBEX_KEY_GTNH", "1f10722992c938f360a0605488c03cf42b10d260"),
}
TEBEX_BASE_URL = "https://plugin.tebex.io"


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
