from datetime import datetime, timezone
from typing import Optional

def parse_file_date(value: str) -> datetime:
    # API returns ISO 8601 strings that often end with Z
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)

def parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None
