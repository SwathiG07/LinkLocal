import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import get_chats_dir, get_groups_dir, get_logs_dir, get_scheduled_path, get_transfers_dir


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _chat_path(chat_id: str) -> Path:
    return get_chats_dir() / f"{chat_id}.json"


def _group_path(group_id: str) -> Path:
    return get_groups_dir() / f"{group_id}.json"


def _log_path() -> Path:
    return get_logs_dir() / "events.json"


def _transfer_path(transfer_id: str) -> Path:
    return get_transfers_dir() / transfer_id


def _read_json_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        try:
            return json.load(handle)
        except json.JSONDecodeError:
            return []


def _write_json(path: Path, data: Any) -> None:
    _ensure_parent(path)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def normalize_message(message_dict: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {
        "message_id": message_dict.get("message_id"),
        "sender_id": message_dict.get("sender_id"),
        "sender_name": message_dict.get("sender_name"),
        "content": message_dict.get("content"),
        "display_content": message_dict.get("display_content"),
        "timestamp": message_dict.get("timestamp"),
        "type": message_dict.get("type", "text"),
        "reactions": message_dict.get("reactions", {}),
        "is_edited": bool(message_dict.get("is_edited", False)),
        "edit_history": list(message_dict.get("edit_history", [])),
        "is_deleted": bool(message_dict.get("is_deleted", False)),
        "reply_to_id": message_dict.get("reply_to_id"),
        "group_id": message_dict.get("group_id"),
        "chat_id": message_dict.get("chat_id"),
        "forwarded_from": message_dict.get("forwarded_from"),
        "pinned": bool(message_dict.get("pinned", False)),
        "ttl_seconds": message_dict.get("ttl_seconds"),
        "delete_on_seen": bool(message_dict.get("delete_on_seen", False)),
        "attachments": list(message_dict.get("attachments", [])),
        "content_type": message_dict.get("content_type", "text/plain"),
        "audio_meta": message_dict.get("audio_meta"),
        "file_meta": message_dict.get("file_meta"),
        "poll": message_dict.get("poll"),
        "poll_votes": message_dict.get("poll_votes", {}),
        "scheduled_for": message_dict.get("scheduled_for"),
        "seen_by": list(message_dict.get("seen_by", [])),
    }
    return normalized


def save_message(chat_id: str, message_dict: Dict[str, Any]) -> None:
    path = _chat_path(chat_id)
    _ensure_parent(path)
    messages = _read_json_list(path)
    msg_id = message_dict.get("message_id")
    if msg_id and any(m.get("message_id") == msg_id for m in messages):
        return  # Deduplicate
    messages.append(normalize_message(message_dict))
    _write_json(path, messages)


def load_history(chat_id: str) -> List[Dict[str, Any]]:
    return [normalize_message(item) for item in _read_json_list(_chat_path(chat_id))]


def update_message(chat_id: str, message_id: str, updated_fields: Dict[str, Any]) -> None:
    path = _chat_path(chat_id)
    messages = _read_json_list(path)
    updated = False
    for message in messages:
        if message.get("message_id") == message_id:
            message.update(updated_fields)
            updated = True
            break
    if updated:
        _write_json(path, [normalize_message(item) for item in messages])


def delete_message_record(chat_id: str, message_id: str) -> None:
    update_message(
        chat_id,
        message_id,
        {
            "is_deleted": True,
            "content": None,
            "display_content": "This message was deleted",
        },
    )


def delete_history(chat_id: str) -> None:
    path = _chat_path(chat_id)
    if path.exists():
        path.unlink()

def rename_history(old_chat_id: str, new_chat_id: str) -> None:
    old_path = _chat_path(old_chat_id)
    if old_path.exists():
        new_path = _chat_path(new_chat_id)
        if not new_path.exists():
            old_path.rename(new_path)


def save_group_meta(group_id: str, group_dict: Dict[str, Any]) -> None:
    _write_json(_group_path(group_id), group_dict)

def delete_group_meta(group_id: str) -> None:
    path = _group_path(group_id)
    if path.exists():
        path.unlink()


def load_group_meta(group_id: str) -> Dict[str, Any]:
    path = _group_path(group_id)
    if not path.exists():
        raise FileNotFoundError(f"Unknown group: {group_id}")
    with path.open("r", encoding="utf-8") as handle:
        try:
            return json.load(handle)
        except json.JSONDecodeError:
            return {}


def list_group_meta() -> List[Dict[str, Any]]:
    groups_dir = get_groups_dir()
    groups_dir.mkdir(parents=True, exist_ok=True)
    groups = []
    for path in sorted(groups_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as handle:
            try:
                groups.append(json.load(handle))
            except json.JSONDecodeError:
                continue
    return groups


def list_chat_ids() -> List[str]:
    chats_dir = get_chats_dir()
    chats_dir.mkdir(parents=True, exist_ok=True)
    return sorted(path.stem for path in chats_dir.glob("*.json"))


def search_messages(query: str) -> List[Dict[str, Any]]:
    query_lower = query.lower()
    results = []
    for chat_id in list_chat_ids():
        for message in load_history(chat_id):
            haystack = " ".join(
                str(value)
                for value in [
                    message.get("content"),
                    message.get("display_content"),
                    message.get("sender_name"),
                    message.get("forwarded_from"),
                ]
                if value
            ).lower()
            if query_lower in haystack:
                results.append({"chat_id": chat_id, "message": message})
    return results


def append_log(entry: Dict[str, Any]) -> None:
    path = _log_path()
    logs = _read_json_list(path)
    logs.append(entry)
    _write_json(path, logs[-500:])


def load_logs(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    logs = _read_json_list(_log_path())
    if limit is not None:
        return logs[-limit:]
    return logs


def save_transfer_blob(transfer_id: str, data: bytes, filename: str) -> str:
    target = _transfer_path(transfer_id)
    _ensure_parent(target)
    target.mkdir(parents=True, exist_ok=True)
    file_path = target / filename
    file_path.write_bytes(data)
    return str(file_path)


def load_scheduled_messages() -> List[Dict[str, Any]]:
    path = get_scheduled_path()
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_scheduled_messages(items: List[Dict[str, Any]]) -> None:
    _write_json(get_scheduled_path(), items)
