import asyncio
import base64
import inspect
import json
import mimetypes
import queue
import uuid
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import storage
from .config import load_config, save_config
from .crypto import (
    decrypt_message,
    encrypt_message,
    export_public_key_pem,
    generate_keypair,
    load_keypair,
    load_public_key_from_pem,
    peer_verification_code,
)
from .discovery import DiscoveryService
from .events import bus
from .utils import ensure_initials, format_bytes, generate_chat_id, hash_text, now_iso


Callback = Callable[[Dict[str, Any]], None]
GroupHandler = Callable[[Dict[str, Any]], Any]

CONTENT_TYPES = {"text", "reply", "group_message", "audio", "file", "forward", "poll", "announcement"}


class Peer:
    def __init__(self, display_name: Optional[str]) -> None:
        self.config = load_config()
        self.display_name = display_name or self.config.get("display_name", "LinkLocal User")
        self.config["display_name"] = self.display_name
        self.config["avatar"] = self.config.get("avatar") or ensure_initials(self.display_name)
        save_config(self.config)

        self.peer_id = self.config["peer_id"]
        self.tcp_port = int(self.config.get("tcp_port", 55556))
        self.udp_port = int(self.config.get("udp_discovery_port", 55555))
        self.server: Optional[asyncio.base_events.Server] = None
        self.discovery = DiscoveryService(
            display_name=self.display_name,
            peer_id=self.peer_id,
            tcp_port=self.tcp_port,
            udp_port=self.udp_port,
            status_message=self.config.get("status_message", "Available"),
            avatar=self.config.get("avatar", "LL"),
        )
        self.private_key, self.public_key = load_keypair()
        self.known_peer_public_keys: Dict[str, Any] = {}
        self.manual_peers: Dict[str, Dict[str, Any]] = {
            item["peer_id"]: dict(item)
            for item in self.config.get("manual_peers", [])
            if item.get("peer_id")
        }
        self.event_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._callbacks: Dict[str, List[Callback]] = {
            "message": [],
            "reaction": [],
            "typing": [],
            "seen": [],
            "delivered": [],
            "peer_online": [],
            "peer_offline": [],
            "status": [],
            "stats": [],
        }
        self._group_handler: Optional[GroupHandler] = None
        self.connection_stats: Dict[str, Dict[str, Any]] = {}
        self._scheduled_tasks: List[asyncio.Task] = []

    async def start(self) -> None:
        generate_keypair()
        try:
            self.server = await asyncio.start_server(self._handle_connection, "0.0.0.0", self.tcp_port, limit=100*1024*1024)
        except OSError:
            self.server = await asyncio.start_server(self._handle_connection, "0.0.0.0", 0, limit=100*1024*1024)
            sock = self.server.sockets[0]
            self.tcp_port = int(sock.getsockname()[1])
            self.config["tcp_port"] = self.tcp_port
            save_config(self.config)

        self.discovery.tcp_port = self.tcp_port
        self.discovery.display_name = self.display_name
        self.discovery.status_message = self.config.get("status_message", "Available")
        self.discovery.avatar = self.config.get("avatar", "LL")
        self.discovery.on_peer_discovered.append(self._handle_peer_online)
        self.discovery.on_peer_lost.append(self._handle_peer_offline)
        await self.discovery.start()
        self._load_scheduled_messages()
        self._log("peer_started", {"tcp_port": self.tcp_port})

    async def stop(self) -> None:
        await self.discovery.stop()
        for task in self._scheduled_tasks:
            task.cancel()
        for task in self._scheduled_tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._scheduled_tasks.clear()
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        self._log("peer_stopped", {})

    def discover(self) -> List[Dict[str, Any]]:
        peers = self.discovery.get_peers()
        for peer_id, manual in self.manual_peers.items():
            peers.setdefault(
                peer_id,
                {
                    **manual,
                    "peer_id": peer_id,
                    "last_seen": manual.get("last_seen"),
                    "online": manual.get("online", False),
                },
            )
        return list(peers.values())

    def set_group_handler(self, handler: GroupHandler) -> None:
        self._group_handler = handler

    def update_profile(
        self,
        *,
        display_name: Optional[str] = None,
        status_message: Optional[str] = None,
        avatar: Optional[str] = None,
        theme: Optional[str] = None,
        do_not_disturb: Optional[bool] = None,
        notification_sound: Optional[bool] = None,
    ) -> None:
        if display_name:
            self.display_name = display_name
            self.config["display_name"] = display_name
            self.discovery.display_name = display_name
        if status_message is not None:
            self.config["status_message"] = status_message
            self.discovery.status_message = status_message
        if avatar is not None:
            self.config["avatar"] = avatar
            self.discovery.avatar = avatar
        if theme is not None:
            self.config["theme"] = theme
        if do_not_disturb is not None:
            self.config["do_not_disturb"] = do_not_disturb
        if notification_sound is not None:
            self.config["notification_sound"] = notification_sound
        save_config(self.config)

    def add_manual_peer(self, name: str, ip: str, tcp_port: int, peer_id: Optional[str] = None) -> str:
        resolved_peer_id = peer_id or f"manual-{hash_text(f'{ip}:{tcp_port}')[:12]}"
        self.manual_peers[resolved_peer_id] = {
            "peer_id": resolved_peer_id,
            "name": name,
            "ip": ip,
            "tcp_port": int(tcp_port),
            "status_message": "Manual peer",
            "avatar": ensure_initials(name),
            "online": False,
            "last_seen": None,
        }
        self.config["manual_peers"] = list(self.manual_peers.values())
        save_config(self.config)
        self._emit("status", {"peer_id": resolved_peer_id, "action": "manual_added"})
        return resolved_peer_id

    def block_peer(self, peer_id: str) -> None:
        blocked = self.config.get("blocked_peers", [])
        if peer_id not in blocked:
            blocked.append(peer_id)
            self.config["blocked_peers"] = blocked
            save_config(self.config)

    def unblock_peer(self, peer_id: str) -> None:
        blocked = self.config.get("blocked_peers", [])
        if peer_id in blocked:
            blocked.remove(peer_id)
            self.config["blocked_peers"] = blocked
            save_config(self.config)

    def _should_ignore_peer(self, peer_id: str) -> bool:
        return peer_id in self.config.get("blocked_peers", [])

    def remove_manual_peer(self, peer_id: str) -> None:
        if peer_id in self.manual_peers:
            self.manual_peers.pop(peer_id)
            self.config["manual_peers"] = list(self.manual_peers.values())
            save_config(self.config)

    def get_connection_stats(self) -> Dict[str, Dict[str, Any]]:
        return {key: dict(value) for key, value in self.connection_stats.items()}

    def get_peer_safety_code(self, peer_id: str) -> Optional[str]:
        key = self.known_peer_public_keys.get(peer_id)
        if key is None:
            return None
        return peer_verification_code(self.public_key, key)

    def on_message(self, fn: Callback) -> None:
        self._callbacks["message"].append(fn)

    def on_reaction(self, fn: Callback) -> None:
        self._callbacks["reaction"].append(fn)

    def on_typing(self, fn: Callback) -> None:
        self._callbacks["typing"].append(fn)

    def on_seen(self, fn: Callback) -> None:
        self._callbacks["seen"].append(fn)

    def on_delivered(self, fn: Callback) -> None:
        self._callbacks["delivered"].append(fn)

    def on_peer_online(self, fn: Callback) -> None:
        self._callbacks["peer_online"].append(fn)

    def on_peer_offline(self, fn: Callback) -> None:
        self._callbacks["peer_offline"].append(fn)

    def on_status(self, fn: Callback) -> None:
        self._callbacks["status"].append(fn)

    def on_stats(self, fn: Callback) -> None:
        self._callbacks["stats"].append(fn)

    async def send(
        self,
        message_text: str,
        to_peer_id: str,
        *,
        forwarded_from: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        delete_on_seen: bool = False,
        scheduled_for: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self._send_content(
            to_peer_id=to_peer_id,
            message_type="text",
            content_payload={"text": message_text},
            forwarded_from=forwarded_from,
            ttl_seconds=ttl_seconds,
            delete_on_seen=delete_on_seen,
            scheduled_for=scheduled_for,
        )

    async def reply_to(self, message_id: str, reply_text: str, to_peer_id: str) -> Dict[str, Any]:
        return await self._send_content(
            to_peer_id=to_peer_id,
            message_type="reply",
            content_payload={"text": reply_text},
            reply_to_id=message_id,
        )

    async def send_group_message(
        self,
        group_id: str,
        text: str,
        to_peer_id: str,
        *,
        message_id: Optional[str] = None,
        reply_to_id: Optional[str] = None,
        message_type: str = "group_message",
        forwarded_from: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        delete_on_seen: bool = False,
    ) -> Dict[str, Any]:
        return await self._send_content(
            to_peer_id=to_peer_id,
            message_type=message_type,
            content_payload={"text": text},
            group_id=group_id,
            message_id=message_id,
            reply_to_id=reply_to_id,
            forwarded_from=forwarded_from,
            ttl_seconds=ttl_seconds,
            delete_on_seen=delete_on_seen,
        )

    async def send_file(
        self,
        file_path: str,
        to_peer_id: str,
        *,
        group_id: Optional[str] = None,
        progress_cb: Optional[Callable[[int], None]] = None,
    ) -> Dict[str, Any]:
        path = Path(file_path)
        data = path.read_bytes()
        if progress_cb:
            progress_cb(20)
        payload = {
            "filename": path.name,
            "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "size": len(data),
            "blob_b64": base64.b64encode(data).decode("ascii"),
        }
        if progress_cb:
            progress_cb(60)
        record = await self._send_content(
            to_peer_id=to_peer_id,
            message_type="file",
            content_payload=payload,
            group_id=group_id,
        )
        if progress_cb:
            progress_cb(100)
        return record

    async def send_audio(
        self,
        file_path: str,
        to_peer_id: str,
        *,
        group_id: Optional[str] = None,
        progress_cb: Optional[Callable[[int], None]] = None,
    ) -> Dict[str, Any]:
        path = Path(file_path)
        data = path.read_bytes()
        if progress_cb:
            progress_cb(25)
        payload = {
            "filename": path.name,
            "mime_type": mimetypes.guess_type(path.name)[0] or "audio/wav",
            "size": len(data),
            "blob_b64": base64.b64encode(data).decode("ascii"),
        }
        if progress_cb:
            progress_cb(75)
        record = await self._send_content(
            to_peer_id=to_peer_id,
            message_type="audio",
            content_payload=payload,
            group_id=group_id,
        )
        if progress_cb:
            progress_cb(100)
        return record

    async def forward_message(
        self,
        source_message: Dict[str, Any],
        to_peer_id: str,
        *,
        group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        message_type = source_message.get("type", "text")
        message_type = "forward" if message_type in {"text", "reply", "group_message", "forward"} else message_type
        payload: Dict[str, Any] = {"text": source_message.get("display_content") or source_message.get("content") or ""}
        if source_message.get("file_meta"):
            file_path = source_message["file_meta"].get("saved_path")
            if file_path and Path(file_path).exists():
                return await self.send_file(file_path, to_peer_id, group_id=group_id)
        if source_message.get("audio_meta"):
            audio_path = source_message["audio_meta"].get("saved_path")
            if audio_path and Path(audio_path).exists():
                return await self.send_audio(audio_path, to_peer_id, group_id=group_id)
        return await self._send_content(
            to_peer_id=to_peer_id,
            message_type=message_type,
            content_payload=payload,
            group_id=group_id,
            forwarded_from=f"{source_message.get('sender_name', 'Unknown')} · {source_message.get('type', 'text')}",
        )

    async def send_poll(
        self,
        question: str,
        options: List[str],
        to_peer_id: str,
        *,
        group_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self._send_content(
            to_peer_id=to_peer_id,
            message_type="poll",
            content_payload={"question": question, "options": options},
            group_id=group_id,
            message_id=message_id,
        )

    async def vote_poll(self, poll_message_id: str, option: str, to_peer_id: str, *, group_id: Optional[str] = None) -> Dict[str, Any]:
        payload = self._base_payload("poll_vote", group_id=group_id)
        payload.update({"target_message_id": poll_message_id, "option": option})
        await self._send_payload(to_peer_id, payload, require_encryption=False)
        chat_id = group_id or generate_chat_id(self.peer_id, to_peer_id)
        message = self._find_message(chat_id, poll_message_id)
        if message:
            votes = dict(message.get("poll_votes", {}))
            votes[self.peer_id] = option
            storage.update_message(chat_id, poll_message_id, {"poll_votes": votes})
        return payload

    async def send_reaction(self, message_id: str, emoji: str, to_peer_id: str, *, group_id: Optional[str] = None) -> Dict[str, Any]:
        payload = self._base_payload("reaction", group_id=group_id)
        payload.update({"target_message_id": message_id, "emoji": emoji})
        await self._send_payload(to_peer_id, payload, require_encryption=False)
        chat_id = group_id or generate_chat_id(self.peer_id, to_peer_id)
        self._apply_reaction(chat_id, message_id, emoji, self.peer_id)
        data = {"message_id": message_id, "emoji": emoji, "sender_id": self.peer_id, "chat_id": chat_id, "group_id": group_id}
        self._emit("reaction", data)
        return data

    async def edit_message(self, message_id: str, new_text: str, to_peer_id: str, *, group_id: Optional[str] = None) -> Dict[str, Any]:
        payload = self._base_payload("edit", group_id=group_id)
        payload["target_message_id"] = message_id
        await self._send_payload(to_peer_id, payload, plaintext=json.dumps({"text": new_text}))
        chat_id = group_id or generate_chat_id(self.peer_id, to_peer_id)
        previous = self._find_message(chat_id, message_id)
        edit_history = list(previous.get("edit_history", []))
        previous_text = previous.get("display_content") or previous.get("content")
        if previous_text:
            edit_history.append(previous_text)
        storage.update_message(
            chat_id,
            message_id,
            {"content": new_text, "display_content": new_text, "is_edited": True, "edit_history": edit_history},
        )
        data = {"message_id": message_id, "content": new_text, "display_content": new_text, "chat_id": chat_id, "group_id": group_id, "is_edited": True}
        self._emit("message", data)
        return data

    async def delete_message(self, message_id: str, to_peer_id: str, *, group_id: Optional[str] = None) -> Dict[str, Any]:
        payload = self._base_payload("delete", group_id=group_id)
        payload["target_message_id"] = message_id
        await self._send_payload(to_peer_id, payload, require_encryption=False)
        chat_id = group_id or generate_chat_id(self.peer_id, to_peer_id)
        storage.delete_message_record(chat_id, message_id)
        data = {"message_id": message_id, "chat_id": chat_id, "group_id": group_id, "deleted": True}
        self._emit("message", data)
        return data

    async def send_typing(self, to_peer_id: str, *, group_id: Optional[str] = None) -> Dict[str, Any]:
        if self.config.get("do_not_disturb"):
            return {}
        payload = self._base_payload("typing", group_id=group_id)
        await self._send_payload(to_peer_id, payload, require_encryption=False)
        return payload

    async def send_seen(self, message_id: str, to_peer_id: str, *, group_id: Optional[str] = None) -> Dict[str, Any]:
        if self.config.get("do_not_disturb"):
            return {}
        payload = self._base_payload("seen", group_id=group_id)
        payload["target_message_id"] = message_id
        
        async def task():
            try:
                await self._send_payload(to_peer_id, payload, require_encryption=False)
                data = {"message_id": message_id, "sender_id": self.peer_id, "group_id": group_id}
                self._emit("seen", data)
            except Exception as e:
                self._log("receipt_failure", {"type": "seen", "to": to_peer_id, "error": str(e)})
                # Retry once after 30 seconds in background
                await asyncio.sleep(30)
                try:
                    await self._send_payload(to_peer_id, payload, require_encryption=False)
                    data = {"message_id": message_id, "sender_id": self.peer_id, "group_id": group_id}
                    self._emit("seen", data)
                except Exception:
                    pass

        asyncio.create_task(task())
        return payload

    async def send_delivered(self, message_id: str, to_peer_id: str, *, group_id: Optional[str] = None) -> Dict[str, Any]:
        payload = self._base_payload("delivered", group_id=group_id)
        payload["target_message_id"] = message_id
        
        async def task():
            try:
                await self._send_payload(to_peer_id, payload, require_encryption=False)
            except Exception as e:
                self._log("receipt_failure", {"type": "delivered", "to": to_peer_id, "error": str(e)})
                # Retry once after 15 seconds
                await asyncio.sleep(15)
                try:
                    await self._send_payload(to_peer_id, payload, require_encryption=False)
                except Exception:
                    pass

        asyncio.create_task(task())
        return payload

    async def ping(self, to_peer_id: str) -> Optional[float]:
        started = asyncio.get_running_loop().time()
        payload = self._base_payload("ping")
        payload["ping_started"] = started
        response = await self._send_payload(to_peer_id, payload, require_encryption=False, expect_response=True)
        if response is None:
            return None
        latency_ms = (asyncio.get_running_loop().time() - started) * 1000
        stats = self._record_stats(to_peer_id, sent_bytes=0, received_bytes=0, latency_ms=latency_ms)
        self._emit("stats", {"peer_id": to_peer_id, "stats": stats})
        return latency_ms

    def schedule_message(
        self,
        *,
        to_peer_id: str,
        text: str,
        when_iso: str,
        group_id: Optional[str] = None,
        forwarded_from: Optional[str] = None,
    ) -> None:
        item = {
            "id": str(uuid.uuid4()),
            "to_peer_id": to_peer_id,
            "text": text,
            "when_iso": when_iso,
            "group_id": group_id,
            "forwarded_from": forwarded_from,
        }
        scheduled = storage.load_scheduled_messages()
        scheduled.append(item)
        storage.save_scheduled_messages(scheduled)
        self._schedule_item(item)

    async def send_command(
        self,
        to_peer_id: str,
        payload: Dict[str, Any],
        *,
        plaintext: Optional[str] = None,
        require_encryption: bool = False,
        expect_response: bool = False,
    ) -> Optional[Dict[str, Any]]:
        return await self._send_payload(
            to_peer_id,
            payload,
            plaintext=plaintext,
            require_encryption=require_encryption,
            expect_response=expect_response,
        )

    async def _send_content(
        self,
        *,
        to_peer_id: str,
        message_type: str,
        content_payload: Dict[str, Any],
        group_id: Optional[str] = None,
        message_id: Optional[str] = None,
        reply_to_id: Optional[str] = None,
        forwarded_from: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        delete_on_seen: bool = False,
        scheduled_for: Optional[str] = None,
    ) -> Dict[str, Any]:
        timestamp = now_iso()
        current_message_id = message_id or str(uuid.uuid4())
        payload = self._base_payload(message_type, current_message_id, timestamp, group_id=group_id)
        if reply_to_id:
            payload["reply_to_id"] = reply_to_id
        if forwarded_from:
            payload["forwarded_from"] = forwarded_from
        if ttl_seconds is not None:
            payload["ttl_seconds"] = ttl_seconds
        if delete_on_seen:
            payload["delete_on_seen"] = True
        if scheduled_for:
            payload["scheduled_for"] = scheduled_for
        await self._send_payload(to_peer_id, payload, plaintext=json.dumps(content_payload))
        chat_id = group_id or generate_chat_id(self.peer_id, to_peer_id)
        record = self._message_record(
            message_id=current_message_id,
            sender_id=self.peer_id,
            sender_name=self.display_name,
            content=content_payload.get("text"),
            display_content=content_payload.get("text"),
            timestamp=timestamp,
            message_type=message_type,
            reply_to_id=reply_to_id,
            group_id=group_id,
            chat_id=chat_id,
            forwarded_from=forwarded_from,
            ttl_seconds=ttl_seconds,
            delete_on_seen=delete_on_seen,
            scheduled_for=scheduled_for,
        )
        self._populate_record_from_payload(record, content_payload, current_message_id)
        storage.save_message(chat_id, record)
        self._emit("message", record)
        return record

    async def _send_payload(
        self,
        to_peer_id: str,
        payload: Dict[str, Any],
        *,
        plaintext: Optional[str] = None,
        require_encryption: bool = True,
        expect_response: bool = False,
    ) -> Optional[Dict[str, Any]]:
        peer_info = self._get_peer_info(to_peer_id)
        last_error: Optional[Exception] = None
        
        # Collect all potential IPs to try (primary + all interfaces found in discovery)
        candidate_ips = [peer_info["ip"]]
        for alt_ip in peer_info.get("interfaces", []):
            if alt_ip not in candidate_ips:
                candidate_ips.append(alt_ip)
        
        max_attempts = 5
        for attempt in range(max_attempts):
            # On hotspots, try each candidate IP until one connects
            for target_ip in candidate_ips:
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(target_ip, int(peer_info["tcp_port"]), limit=100*1024*1024),
                        timeout=5.0 # Shorter timeout per IP during discovery phase
                    )
                    try:
                        if plaintext is not None:
                            public_key = await self._ensure_peer_key(reader, writer, to_peer_id)
                            payload.update(encrypt_message(plaintext, public_key))
                        elif require_encryption and to_peer_id not in self.known_peer_public_keys:
                            await self._ensure_peer_key(reader, writer, to_peer_id)

                        payload["public_key"] = export_public_key_pem(self.public_key)
                        raw = (json.dumps(payload) + "\n").encode("utf-8")
                        writer.write(raw)
                        await writer.drain()
                        
                        stats = self._record_stats(to_peer_id, sent_bytes=len(raw), received_bytes=0)
                        self._emit("stats", {"peer_id": to_peer_id, "stats": stats})
                        
                        if not expect_response:
                            return None
                            
                        line = await asyncio.wait_for(reader.readline(), timeout=10.0)
                        if not line:
                            return None
                        response = json.loads(line.decode("utf-8"))
                        self._record_stats(to_peer_id, sent_bytes=0, received_bytes=len(line))
                        self._cache_public_key(response.get("sender_id"), response.get("public_key"))
                        return response
                    finally:
                        writer.close()
                        with suppress(Exception):
                            await writer.wait_closed()
                except (asyncio.TimeoutError, OSError) as exc:
                    last_error = exc
                    # If this was the last IP and we have more attempts, we'll sleep
                    continue
                except Exception as exc:
                    last_error = exc
                    continue
            
            # If we tried all IPs and none worked, back-off before the next attempt
            wait_time = 0.5 * (2**attempt)
            if isinstance(last_error, OSError) and getattr(last_error, 'errno', None) == 121:
                wait_time += 1.0
            await asyncio.sleep(wait_time)
                
        raise ConnectionError(f"Multi-Path failure: {last_error}" if last_error else f"Unable to reach peer {to_peer_id}")

    async def _ensure_peer_key(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, peer_id: str):
        if peer_id in self.known_peer_public_keys:
            return self.known_peer_public_keys[peer_id]
        payload = self._base_payload("presence")
        payload["action"] = "key_exchange"
        payload["public_key"] = export_public_key_pem(self.public_key)
        raw = (json.dumps(payload) + "\n").encode("utf-8")
        writer.write(raw)
        await writer.drain()
        line = await reader.readline()
        if not line:
            raise ConnectionError(f"Key exchange failed with peer {peer_id}")
        response = json.loads(line.decode("utf-8"))
        public_key = self._cache_public_key(response.get("sender_id"), response.get("public_key"))
        if public_key is None:
            raise ConnectionError(f"No public key received from peer {peer_id}")
        if peer_id.startswith("manual-") and response.get("sender_id"):
            self._adopt_manual_peer_identity(peer_id, response["sender_id"], response.get("sender_name"))
        return public_key

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer_name = "unknown"
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                self._record_stats(peer_name, sent_bytes=0, received_bytes=len(line))
                try:
                    payload = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                peer_name = payload.get("sender_id", peer_name)
                self._cache_public_key(payload.get("sender_id"), payload.get("public_key"))
                self._log("tcp_receive", {"peer_id": payload.get("sender_id"), "type": payload.get("type"), "bytes": len(line)})
                if payload.get("type") == "presence" and payload.get("action") == "key_exchange":
                    response = self._base_payload("presence")
                    response["action"] = "key_exchange_ack"
                    response["public_key"] = export_public_key_pem(self.public_key)
                    raw = (json.dumps(response) + "\n").encode("utf-8")
                    writer.write(raw)
                    await writer.drain()
                    continue
                response = await self._handle_payload(payload)
                if response is not None:
                    raw = (json.dumps(response) + "\n").encode("utf-8")
                    writer.write(raw)
                    await writer.drain()
        finally:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

    async def _handle_payload(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        sender_id = payload.get("sender_id")
        if sender_id and self._should_ignore_peer(sender_id):
            return None
            
        message_type = payload.get("type")
        if message_type in CONTENT_TYPES:
            return await self._handle_content_payload(payload)
        if message_type == "reaction":
            return self._handle_reaction_payload(payload)
        if message_type == "edit":
            return self._handle_edit_payload(payload)
        if message_type == "delete":
            return self._handle_delete_payload(payload)
        if message_type == "typing":
            return self._handle_typing_payload(payload)
        if message_type == "seen":
            return self._handle_seen_payload(payload)
        if message_type == "delivered":
            return self._handle_delivered_payload(payload)
        if message_type == "poll_vote":
            return self._handle_poll_vote_payload(payload)
        if message_type == "ping":
            return self._base_payload("pong")
        if message_type in {"join_group", "leave_group", "group_meta", "superuser_query"} and self._group_handler:
            response = self._group_handler(payload)
            if inspect.isawaitable(response):
                response = await response
            return response
        return None

    async def _handle_content_payload(self, payload: Dict[str, Any]) -> None:
        plaintext = decrypt_message(
            payload["encrypted_key"],
            payload["encrypted_body"],
            self.private_key,
            payload.get("body_hmac", ""),
        )
        group_id = payload.get("group_id")
        chat_id = group_id or generate_chat_id(self.peer_id, payload["sender_id"])
        try:
            content_payload = json.loads(plaintext)
        except json.JSONDecodeError:
            content_payload = {"text": plaintext}
        record = self._message_record(
            message_id=payload["message_id"],
            sender_id=payload["sender_id"],
            sender_name=payload["sender_name"],
            content=content_payload.get("text"),
            display_content=content_payload.get("text"),
            timestamp=payload["timestamp"],
            message_type=payload["type"],
            reply_to_id=payload.get("reply_to_id"),
            group_id=group_id,
            chat_id=chat_id,
            forwarded_from=payload.get("forwarded_from"),
            ttl_seconds=payload.get("ttl_seconds"),
            delete_on_seen=payload.get("delete_on_seen", False),
            scheduled_for=payload.get("scheduled_for"),
        )
        self._populate_record_from_payload(record, content_payload, payload["message_id"])
        if group_id:
            try:
                group_meta = storage.load_group_meta(group_id)
                if not group_meta.get("persist_history", False) and record["content"]:
                    record["content"] = None
            except FileNotFoundError:
                pass
        storage.save_message(chat_id, record)
        self._emit("message", record)
        if payload["sender_id"] != self.peer_id:
            asyncio.create_task(self.send_delivered(payload["message_id"], payload["sender_id"], group_id=group_id))
        return None

    def _handle_reaction_payload(self, payload: Dict[str, Any]) -> None:
        chat_id = payload.get("group_id") or generate_chat_id(self.peer_id, payload["sender_id"])
        self._apply_reaction(chat_id, payload["target_message_id"], payload["emoji"], payload["sender_id"])
        data = {
            "message_id": payload["target_message_id"],
            "emoji": payload["emoji"],
            "sender_id": payload["sender_id"],
            "chat_id": chat_id,
            "group_id": payload.get("group_id"),
        }
        self._emit("reaction", data)
        return None

    def _handle_edit_payload(self, payload: Dict[str, Any]) -> None:
        chat_id = payload.get("group_id") or generate_chat_id(self.peer_id, payload["sender_id"])
        previous = self._find_message(chat_id, payload["target_message_id"])
        plaintext = decrypt_message(
            payload["encrypted_key"],
            payload["encrypted_body"],
            self.private_key,
            payload.get("body_hmac", ""),
        )
        try:
            new_payload = json.loads(plaintext)
        except json.JSONDecodeError:
            new_payload = {"text": plaintext}
        new_text = new_payload.get("text", "")
        edit_history = list(previous.get("edit_history", []))
        previous_text = previous.get("display_content") or previous.get("content")
        if previous_text:
            edit_history.append(previous_text)
        storage.update_message(
            chat_id,
            payload["target_message_id"],
            {"content": new_text, "display_content": new_text, "is_edited": True, "edit_history": edit_history},
        )
        self._emit(
            "message",
            {
                "message_id": payload["target_message_id"],
                "content": new_text,
                "display_content": new_text,
                "chat_id": chat_id,
                "group_id": payload.get("group_id"),
                "is_edited": True,
            },
        )
        return None

    def _handle_delete_payload(self, payload: Dict[str, Any]) -> None:
        chat_id = payload.get("group_id") or generate_chat_id(self.peer_id, payload["sender_id"])
        storage.delete_message_record(chat_id, payload["target_message_id"])
        self._emit("message", {"message_id": payload["target_message_id"], "chat_id": chat_id, "group_id": payload.get("group_id"), "deleted": True})
        return None

    def _handle_typing_payload(self, payload: Dict[str, Any]) -> None:
        data = {"sender_id": payload["sender_id"], "group_id": payload.get("group_id")}
        self._emit("typing", data)
        return None

    def _handle_seen_payload(self, payload: Dict[str, Any]) -> None:
        chat_id = payload.get("group_id") or generate_chat_id(self.peer_id, payload["sender_id"])
        message = self._find_message(chat_id, payload["target_message_id"])
        if not message:
            return None
        seen_by = list(message.get("seen_by", []))
        if payload["sender_id"] not in seen_by:
            seen_by.append(payload["sender_id"])
            storage.update_message(chat_id, payload["target_message_id"], {"seen_by": seen_by})
        if message.get("delete_on_seen"):
            ttl = int(message.get("ttl_seconds") or 0)
            self._schedule_local_delete(chat_id, payload["target_message_id"], ttl)
        data = {
            "message_id": payload["target_message_id"], 
            "sender_id": payload["sender_id"], 
            "group_id": payload.get("group_id"),
            "chat_id": chat_id
        }
        self._emit("seen", data)
        return None

    def _handle_delivered_payload(self, payload: Dict[str, Any]) -> None:
        chat_id = payload.get("group_id") or generate_chat_id(self.peer_id, payload["sender_id"])
        message = self._find_message(chat_id, payload["target_message_id"])
        if not message:
            return None
        delivered_to = list(message.get("delivered_to", []))
        if payload["sender_id"] not in delivered_to:
            delivered_to.append(payload["sender_id"])
            storage.update_message(chat_id, payload["target_message_id"], {"delivered_to": delivered_to})
        data = {
            "message_id": payload["target_message_id"], 
            "sender_id": payload["sender_id"], 
            "group_id": payload.get("group_id"), 
            "chat_id": chat_id,
            "delivered_to": delivered_to
        }
        self._emit("delivered", data)
        return None

    def _handle_poll_vote_payload(self, payload: Dict[str, Any]) -> None:
        chat_id = payload.get("group_id") or generate_chat_id(self.peer_id, payload["sender_id"])
        message = self._find_message(chat_id, payload["target_message_id"])
        votes = dict(message.get("poll_votes", {}))
        votes[payload["sender_id"]] = payload["option"]
        storage.update_message(chat_id, payload["target_message_id"], {"poll_votes": votes})
        self._emit("message", {"message_id": payload["target_message_id"], "chat_id": chat_id, "group_id": payload.get("group_id"), "poll_votes": votes})
        return None

    def _handle_peer_online(self, peer_info: Dict[str, Any]) -> None:
        self._emit("peer_online", peer_info)

    def _handle_peer_offline(self, peer_info: Dict[str, Any]) -> None:
        if peer_info.get("peer_id") in self.manual_peers:
            self.manual_peers[peer_info["peer_id"]]["last_seen"] = peer_info.get("last_seen")
            self.manual_peers[peer_info["peer_id"]]["online"] = False
        self._emit("peer_offline", peer_info)

    def _emit(self, event_name: str, data: Dict[str, Any]) -> None:
        bus.emit(event_name, data)
        self.event_queue.put({"event": event_name, "data": data})
        for callback in list(self._callbacks.get(event_name, [])):
            callback(data)

    def _cache_public_key(self, sender_id: Optional[str], public_key_pem: Optional[str]):
        if not sender_id or not public_key_pem:
            return None
        self.known_peer_public_keys[sender_id] = load_public_key_from_pem(public_key_pem)
        return self.known_peer_public_keys[sender_id]

    def _get_peer_info(self, peer_id: str) -> Dict[str, Any]:
        peers = self.discovery.get_peers()
        if peer_id in peers:
            return peers[peer_id]
        if peer_id in self.manual_peers:
            return self.manual_peers[peer_id]
        raise KeyError(f"Peer {peer_id} is not currently online or manually configured")

    def _find_message(self, chat_id: str, message_id: str) -> Dict[str, Any]:
        for item in storage.load_history(chat_id):
            if item.get("message_id") == message_id:
                return item
        return {}

    def _apply_reaction(self, chat_id: str, message_id: str, emoji: str, sender_id: str) -> None:
        message = self._find_message(chat_id, message_id)
        reactions = dict(message.get("reactions", {}))
        reactors = list(reactions.get(emoji, []))
        if sender_id not in reactors:
            reactors.append(sender_id)
        reactions[emoji] = reactors
        storage.update_message(chat_id, message_id, {"reactions": reactions})

    def _populate_record_from_payload(self, record: Dict[str, Any], content_payload: Dict[str, Any], message_id: str) -> None:
        if record["type"] == "file":
            data = base64.b64decode(content_payload["blob_b64"].encode("ascii"))
            saved_path = storage.save_transfer_blob(message_id, data, content_payload["filename"])
            record["file_meta"] = {
                "filename": content_payload["filename"],
                "mime_type": content_payload["mime_type"],
                "size": content_payload["size"],
                "saved_path": saved_path,
                "label": f"{content_payload['filename']} ({format_bytes(content_payload['size'])})",
            }
            record["display_content"] = record["file_meta"]["label"]
            record["attachments"] = [record["file_meta"]]
        elif record["type"] == "audio":
            data = base64.b64decode(content_payload["blob_b64"].encode("ascii"))
            saved_path = storage.save_transfer_blob(message_id, data, content_payload["filename"])
            record["audio_meta"] = {
                "filename": content_payload["filename"],
                "mime_type": content_payload["mime_type"],
                "size": content_payload["size"],
                "saved_path": saved_path,
                "label": f"Audio: {content_payload['filename']} ({format_bytes(content_payload['size'])})",
            }
            record["display_content"] = record["audio_meta"]["label"]
        elif record["type"] == "poll":
            record["poll"] = {"question": content_payload.get("question", ""), "options": list(content_payload.get("options", []))}
            record["display_content"] = content_payload.get("question", "Poll")
        elif content_payload.get("text") is not None:
            record["display_content"] = content_payload["text"]

    def _message_record(
        self,
        *,
        message_id: str,
        sender_id: str,
        sender_name: str,
        content: Optional[str],
        display_content: Optional[str],
        timestamp: str,
        message_type: str,
        reply_to_id: Optional[str] = None,
        group_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        forwarded_from: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        delete_on_seen: bool = False,
        scheduled_for: Optional[str] = None,
    ) -> Dict[str, Any]:
        return storage.normalize_message(
            {
                "message_id": message_id,
                "sender_id": sender_id,
                "sender_name": sender_name,
                "content": content,
                "display_content": display_content,
                "timestamp": timestamp,
                "type": message_type,
                "reply_to_id": reply_to_id,
                "group_id": group_id,
                "chat_id": chat_id,
                "forwarded_from": forwarded_from,
                "ttl_seconds": ttl_seconds,
                "delete_on_seen": delete_on_seen,
                "scheduled_for": scheduled_for,
            }
        )

    def _base_payload(
        self,
        message_type: str,
        message_id: Optional[str] = None,
        timestamp: Optional[str] = None,
        *,
        group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "type": message_type,
            "sender_name": self.display_name,
            "sender_id": self.peer_id,
            "timestamp": timestamp or now_iso(),
            "message_id": message_id or str(uuid.uuid4()),
            "avatar": self.config.get("avatar", "LL"),
            "status_message": self.config.get("status_message", "Available"),
        }
        if group_id:
            payload["group_id"] = group_id
        return payload

    def _record_stats(self, peer_id: str, *, sent_bytes: int, received_bytes: int, latency_ms: Optional[float] = None) -> Dict[str, Any]:
        stats = self.connection_stats.setdefault(
            peer_id,
            {
                "bytes_sent": 0,
                "bytes_received": 0,
                "latency_ms": None,
                "connected_since": now_iso(),
                "last_activity": now_iso(),
            },
        )
        stats["bytes_sent"] += sent_bytes
        stats["bytes_received"] += received_bytes
        stats["last_activity"] = now_iso()
        if latency_ms is not None:
            stats["latency_ms"] = round(latency_ms, 2)
        return dict(stats)

    def _schedule_item(self, item: Dict[str, Any]) -> None:
        async def runner() -> None:
            target = datetime.fromisoformat(item["when_iso"])
            delay = max((target - datetime.now(target.tzinfo)).total_seconds(), 0)
            await asyncio.sleep(delay)
            if item.get("group_id"):
                if self._group_handler:
                    response = self._group_handler({"type": "group_meta", "action": "send_scheduled_message", "group_id": item["group_id"], "text": item["text"]})
                    if inspect.isawaitable(response):
                        await response
            else:
                await self.send(item["text"], item["to_peer_id"], forwarded_from=item.get("forwarded_from"), scheduled_for=item["when_iso"])
            scheduled = [entry for entry in storage.load_scheduled_messages() if entry.get("id") != item["id"]]
            storage.save_scheduled_messages(scheduled)

        self._scheduled_tasks.append(asyncio.create_task(runner(), name=f"scheduled-{item['id']}"))

    def _load_scheduled_messages(self) -> None:
        for item in storage.load_scheduled_messages():
            self._schedule_item(item)

    def _schedule_local_delete(self, chat_id: str, message_id: str, ttl_seconds: int) -> None:
        async def runner() -> None:
            if ttl_seconds > 0:
                await asyncio.sleep(ttl_seconds)
            storage.delete_message_record(chat_id, message_id)
            self._emit("message", {"message_id": message_id, "chat_id": chat_id, "deleted": True})

        self._scheduled_tasks.append(asyncio.create_task(runner(), name=f"ttl-delete-{message_id}"))

    def _adopt_manual_peer_identity(self, old_peer_id: str, new_peer_id: str, sender_name: Optional[str]) -> None:
        if old_peer_id == new_peer_id or old_peer_id not in self.manual_peers:
            return
        manual = dict(self.manual_peers.pop(old_peer_id))
        manual["peer_id"] = new_peer_id
        if sender_name:
            manual["name"] = sender_name
        self.manual_peers[new_peer_id] = manual
        self.config["manual_peers"] = list(self.manual_peers.values())
        storage.rename_history(old_peer_id, new_peer_id)
        save_config(self.config)
        self.event_queue.put({"event": "identity_changed", "data": {"old_id": old_peer_id, "new_id": new_peer_id, "name": manual["name"]}})


    def _log(self, event_type: str, details: Dict[str, Any]) -> None:
        entry = {"timestamp": now_iso(), "peer_id": self.peer_id, "event": event_type, "details": details}
        storage.append_log(entry)
        bus.emit("network_log", entry)
