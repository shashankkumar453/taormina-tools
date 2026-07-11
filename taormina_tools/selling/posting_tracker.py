from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG_PATH = Path("out/posting-log.json")


def load_log(path: Path = DEFAULT_LOG_PATH) -> dict[str, dict[str, str | None]]:
    if not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


def save_log(log: dict[str, dict[str, str | None]], path: Path = DEFAULT_LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(log, f, indent=2)


def is_posted(log: dict, vin: str, platform: str) -> bool:
    entry = log.get(vin, {})
    return entry.get(platform) is not None


def mark_posted(log: dict, vin: str, platform: str) -> None:
    if vin not in log:
        log[vin] = {}
    log[vin][platform] = datetime.now(timezone.utc).isoformat()
