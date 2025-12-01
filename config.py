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
