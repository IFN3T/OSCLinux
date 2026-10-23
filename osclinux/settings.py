"""Persistent user configuration for OSCLinux."""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

SETTINGS_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "osclinux" / "settings.json"
DEFAULTS: dict[str, Any] = {
    "osc": {"host": "127.0.0.1", "port": 9000, "receive_port": 9001, "interval": 2, "mode": "alternate", "startup": False},
    "appearance": {"theme": "dark"},
    "order": ["spotify", "system", "temperatures", "weather", "clock", "custom"],
    "modules": {
        "spotify": {"enabled": True, "interval": 15, "format": "Titre + Artiste + Progression", "hide_paused": True},
        "system": {"enabled": True, "interval": 10, "cpu": True, "ram": True, "gpu": True},
        "temperatures": {"enabled": False, "interval": 10, "cpu": True, "gpu": True, "other": False},
        "weather": {"enabled": False, "interval": 10, "city": "Paris", "unit": "°C"},
        "clock": {"enabled": False, "interval": 10, "format": "24h"},
        "custom": {"enabled": False, "interval": 10, "message": "♫ Bonne journée !"},
    },
}


def _merge(base: dict[str, Any], loaded: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        elif key in result:
            result[key] = value
    return result


def load_settings(path: Path = SETTINGS_PATH) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            return deepcopy(DEFAULTS)
        return _merge(DEFAULTS, loaded)
    except (OSError, json.JSONDecodeError):
        return deepcopy(DEFAULTS)


def save_settings(settings: dict[str, Any], path: Path = SETTINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(settings, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
