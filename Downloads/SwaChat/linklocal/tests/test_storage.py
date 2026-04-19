from linklocal import storage
from linklocal.config import set_app_dir


def test_save_and_load_history(tmp_path, monkeypatch):
    set_app_dir(str(tmp_path))
    message = {
        "message_id": "msg-1",
        "sender_id": "peer-a",
        "sender_name": "Alice",
        "content": "hello",
        "timestamp": "2026-01-01T10:00:00",
        "type": "text",
        "reactions": {},
        "is_edited": False,
        "edit_history": [],
        "is_deleted": False,
        "reply_to_id": None,
    }

    storage.save_message("peer-a_peer-b", message)
    history = storage.load_history("peer-a_peer-b")

    for key, value in message.items():
        assert history[0][key] == value
    set_app_dir(None)


def test_update_message_merges_fields(tmp_path, monkeypatch):
    set_app_dir(str(tmp_path))
    message = {
        "message_id": "msg-1",
        "sender_id": "peer-a",
        "sender_name": "Alice",
        "content": "hello",
        "timestamp": "2026-01-01T10:00:00",
        "type": "text",
        "reactions": {},
        "is_edited": False,
        "edit_history": [],
        "is_deleted": False,
        "reply_to_id": None,
    }

    storage.save_message("peer-a_peer-b", message)
    storage.update_message(
        "peer-a_peer-b",
        "msg-1",
        {"content": "updated", "is_edited": True},
    )

    history = storage.load_history("peer-a_peer-b")
    assert history[0]["content"] == "updated"
    assert history[0]["is_edited"] is True
    set_app_dir(None)
