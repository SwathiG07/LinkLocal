import asyncio
import json
import threading
import uuid
from contextlib import suppress
from datetime import datetime
from functools import wraps
from typing import Any, Dict, List, Optional, Set

from flask import Flask, redirect, render_template, request, session, url_for

from ..config import load_config
from ..crypto import decrypt_message, export_public_key_pem, load_keypair
from ..discovery import DiscoveryService
from .. import storage
from ..utils import format_timestamp


class DashboardBackend:
    def __init__(self) -> None:
        self.config = load_config()
        self.private_key, self.public_key = load_keypair()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self.discovery = DiscoveryService(
            display_name="LinkLocal Superuser",
            peer_id=f"superuser-{uuid.uuid4()}",
            tcp_port=0,
            udp_port=int(self.config.get("udp_discovery_port", 55555)),
        )
        self._run_async(self.discovery.start()).result()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _run_async(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def shutdown(self) -> None:
        with suppress(Exception):
            self._run_async(self.discovery.stop()).result(timeout=5)
        self.loop.call_soon_threadsafe(self.loop.stop)

    def peer_info_for_group(self, group_meta: Dict) -> Optional[Dict]:
        admin_id = group_meta.get("admin_peer_id") or group_meta.get("created_by")
        if not admin_id:
            return None
        if admin_id == self.config["peer_id"]:
            return {
                "peer_id": self.config["peer_id"],
                "name": self.config["display_name"],
                "ip": "127.0.0.1",
                "tcp_port": self.config["tcp_port"],
            }
        peers = self.discovery.get_peers()
        return peers.get(admin_id)

    async def _request(self, host_peer: Dict, payload: Dict) -> Optional[Dict]:
        reader, writer = await asyncio.open_connection(host_peer["ip"], int(host_peer["tcp_port"]))
        try:
            writer.write((json.dumps(payload) + "\n").encode("utf-8"))
            await writer.drain()
            line = await reader.readline()
            if not line:
                return None
            return json.loads(line.decode("utf-8"))
        finally:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

    def query_group(self, group_meta: Dict, include_chat_log: bool = False) -> Dict:
        host = self.peer_info_for_group(group_meta)
        if not host:
            cached = dict(group_meta)
            cached["members"] = [
                {**(m if isinstance(m, dict) else {"peer_id": str(m)}), "online": False}
                for m in group_meta.get("members", [])
            ]
            return {"group": cached, "chat_log": None, "offline": True}

        payload = {
            "type": "superuser_query",
            "action": "group_status",
            "group_id": group_meta["group_id"],
            "sender_name": self.config["display_name"],
            "sender_id": self.config["peer_id"],
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "message_id": str(uuid.uuid4()),
            "public_key": export_public_key_pem(self.public_key),
            "include_chat_log": include_chat_log,
        }
        try:
            response = self._run_async(self._request(host, payload)).result(timeout=5)
        except Exception:
            response = None
            
        if not response or not response.get("ok"):
            cached = dict(group_meta)
            cached["members"] = [
                {**(m if isinstance(m, dict) else {"peer_id": str(m)}), "online": False}
                for m in group_meta.get("members", [])
            ]
            return {"group": cached, "chat_log": None, "offline": True}

        chat_log = None
        if include_chat_log and response.get("encrypted_key") and response.get("encrypted_body"):
            decrypted = decrypt_message(response["encrypted_key"], response["encrypted_body"], self.private_key)
            chat_log = json.loads(decrypted)
        return {"group": response["group"], "chat_log": chat_log, "offline": False}

    def kick_member(self, group_meta: Dict, target_peer_id: str) -> None:
        host = self.peer_info_for_group(group_meta)
        if not host:
            return
        payload = {
            "type": "superuser_query",
            "action": "kick_member",
            "group_id": group_meta["group_id"],
            "target_peer_id": target_peer_id,
            "sender_name": self.config["display_name"],
            "sender_id": self.config["peer_id"],
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "message_id": str(uuid.uuid4()),
            "public_key": export_public_key_pem(self.public_key),
        }
        self._run_async(self._request(host, payload)).result()

    def broadcast_announcement(self, text: str) -> None:
        for group_meta in storage.list_group_meta():
            host = self.peer_info_for_group(group_meta)
            if not host:
                continue
            payload = {
                "type": "superuser_query",
                "action": "broadcast_announcement",
                "group_id": group_meta["group_id"],
                "text": text,
                "sender_name": self.config["display_name"],
                "sender_id": self.config["peer_id"],
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "message_id": str(uuid.uuid4()),
                "public_key": export_public_key_pem(self.public_key),
            }
            try:
                self._run_async(self._request(host, payload)).result(timeout=5)
            except Exception:
                pass

    def peer_map(self) -> List[Dict]:
        peers = []
        for peer_id, info in self.discovery.get_peers().items():
            peers.append({"peer_id": peer_id, **info})
        return sorted(peers, key=lambda item: item.get("name", ""))


def build_dashboard_snapshot(enabled_logs: Set[str]) -> Dict[str, Any]:
    groups = []
    for group_meta in storage.list_group_meta():
        result = backend.query_group(group_meta, include_chat_log=group_meta["group_id"] in enabled_logs)
        history = storage.load_history(group_meta["group_id"])
        per_hour: Dict[str, int] = {}
        for message in history:
            hour = message["timestamp"][:13]
            per_hour[hour] = per_hour.get(hour, 0) + 1
        result["volume"] = sorted(per_hour.items())[-8:]
        groups.append(result)
    return {
        "groups": groups,
        "peer_map": backend.peer_map(),
        "logs": storage.load_logs(limit=100),
    }


backend = DashboardBackend()
app = Flask(__name__, template_folder="templates")
app.secret_key = load_config()["superuser_token"]


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


@app.route("/", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        token = request.form.get("token", "")
        if token == load_config()["superuser_token"]:
            session["authenticated"] = True
            return redirect(url_for("dashboard"))
        error = "Invalid superuser token"
    return render_template("login.html", error=error)


@app.route("/dashboard")
@login_required
def dashboard():
    enabled_logs: Set[str] = set(request.args.getlist("logs"))
    snapshot = build_dashboard_snapshot(enabled_logs)
    return render_template(
        "index.html",
        groups=snapshot["groups"],
        peer_map=snapshot["peer_map"],
        logs=snapshot["logs"],
        enabled_logs=enabled_logs,
        format_timestamp=format_timestamp,
    )


@app.post("/kick/<group_id>/<peer_id>")
@login_required
def kick_member(group_id: str, peer_id: str):
    group_meta = storage.load_group_meta(group_id)
    backend.kick_member(group_meta, peer_id)
    enabled_logs: List[str] = request.form.getlist("logs")
    return redirect(url_for("dashboard", **{"logs": enabled_logs}))


@app.post("/broadcast")
@login_required
def broadcast():
    text = request.form.get("text", "").strip()
    if text:
        backend.broadcast_announcement(text)
    enabled_logs: List[str] = request.form.getlist("logs")
    return redirect(url_for("dashboard", **{"logs": enabled_logs}))


def run_dashboard() -> None:
    try:
        app.run(port=5050, debug=False, use_reloader=False)
    finally:
        backend.shutdown()


if __name__ == "__main__":
    run_dashboard()
