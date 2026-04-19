import json
import os
import secrets
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


_APP_DIR_OVERRIDE: Optional[Path] = None


def set_app_dir(path: Optional[str]) -> None:
    global _APP_DIR_OVERRIDE
    _APP_DIR_OVERRIDE = Path(path).expanduser() if path else None


def get_app_dir() -> Path:
    if _APP_DIR_OVERRIDE is not None:
        return _APP_DIR_OVERRIDE
    if os.getenv("LINKLOCAL_HOME"):
        return Path(os.environ["LINKLOCAL_HOME"]).expanduser()
    return Path.home() / ".linklocal"


def get_keys_dir() -> Path:
    return get_app_dir() / "keys"


def get_chats_dir() -> Path:
    return get_app_dir() / "chats"


def get_groups_dir() -> Path:
    return get_app_dir() / "groups"


def get_logs_dir() -> Path:
    return get_app_dir() / "logs"


def get_transfers_dir() -> Path:
    return get_app_dir() / "transfers"


def get_config_path() -> Path:
    return get_app_dir() / "config.json"


def get_scheduled_path() -> Path:
    return get_app_dir() / "scheduled.json"


def _ensure_layout() -> None:
    get_app_dir().mkdir(parents=True, exist_ok=True)
    get_keys_dir().mkdir(parents=True, exist_ok=True)
    get_chats_dir().mkdir(parents=True, exist_ok=True)
    get_groups_dir().mkdir(parents=True, exist_ok=True)
    get_logs_dir().mkdir(parents=True, exist_ok=True)
    get_transfers_dir().mkdir(parents=True, exist_ok=True)


def _default_config() -> Dict[str, Any]:
    return {
        "peer_id": str(uuid.uuid4()),
        "display_name": "LinkLocal User",
        "tcp_port": 55556,
        "udp_discovery_port": 55555,
        "superuser_token": secrets.token_hex(32),
        "status_message": "Available",
        "avatar": "LL",
        "theme": "light",
        "do_not_disturb": False,
        "notification_sound": True,
        "manual_peers": [],
        "app_pin_hash": None,
        "integrity_secret": secrets.token_hex(32),
        "key_rotation_interval": 10,
    }


def _merge_defaults(data: Dict[str, Any]) -> Dict[str, Any]:
    merged = _default_config()
    merged.update(data)
    return merged


def load_config() -> Dict[str, Any]:
    _ensure_layout()
    config_path = get_config_path()
    if not config_path.exists():
        data = _default_config()
        save_config(data)
        return data
    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    merged = _merge_defaults(data)
    if merged != data:
        save_config(merged)
    return merged


def save_config(data: Dict[str, Any]) -> None:
    _ensure_layout()
    merged = _merge_defaults(data)
    with get_config_path().open("w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2, sort_keys=True)
