import asyncio
import json
import socket
import time
from contextlib import suppress
from typing import Any, Callable, Dict, List, Optional

from .events import bus
from .utils import get_local_ip, get_local_ips, now_iso


class DiscoveryService:
    def __init__(
        self,
        display_name: str,
        peer_id: str,
        tcp_port: int,
        udp_port: int = 55555,
        heartbeat_interval: int = 5,
        peer_timeout: int = 15,
        local_ip: Optional[str] = None,
        *,
        status_message: str = "Available",
        avatar: str = "LL",
    ) -> None:
        self.display_name = display_name
        self.peer_id = peer_id
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.heartbeat_interval = heartbeat_interval
        self.peer_timeout = peer_timeout
        self.local_ip = local_ip or get_local_ip()
        self.status_message = status_message
        self.avatar = avatar
        self.on_peer_discovered: List[Callable[[Dict[str, Any]], None]] = []
        self.on_peer_lost: List[Callable[[Dict[str, Any]], None]] = []
        self._peers: Dict[str, Dict[str, Any]] = {}
        self._socket: Optional[socket.socket] = None
        self._tasks: List[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._socket.bind(("", self.udp_port))
        self._socket.setblocking(False)
        self._running = True
        self._tasks = [
            asyncio.create_task(self._broadcast_loop(), name="discovery-broadcast"),
            asyncio.create_task(self._listen_loop(), name="discovery-listen"),
            asyncio.create_task(self._cleanup_loop(), name="discovery-cleanup"),
        ]

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def get_peers(self) -> Dict[str, Dict[str, Any]]:
        return {peer_id: dict(info) for peer_id, info in self._peers.items()}

    async def _broadcast_loop(self) -> None:
        assert self._socket is not None
        loop = asyncio.get_running_loop()
        while self._running:
            payload = {
                "name": self.display_name,
                "ip": self.local_ip,
                "tcp_port": self.tcp_port,
                "peer_id": self.peer_id,
                "status_message": self.status_message,
                "avatar": self.avatar,
                "interfaces": get_local_ips(),
            }
            raw = json.dumps(payload).encode("utf-8")
            await loop.sock_sendto(self._socket, raw, ("255.255.255.255", self.udp_port))
            await asyncio.sleep(self.heartbeat_interval)

    async def _listen_loop(self) -> None:
        assert self._socket is not None
        loop = asyncio.get_running_loop()
        while self._running:
            data, addr = await loop.sock_recvfrom(self._socket, 65535)
            self._process_payload(data, addr=addr)

    async def _cleanup_loop(self) -> None:
        while self._running:
            await asyncio.sleep(1)
            self.expire_peers()

    def expire_peers(self, now: Optional[float] = None) -> None:
        now = now or time.time()
        lost = []
        for peer_id, peer in list(self._peers.items()):
            if now - peer["last_seen_monotonic"] > self.peer_timeout:
                peer["last_seen"] = now_iso()
                peer["online"] = False
                lost.append(self._peers.pop(peer_id))
        for peer in lost:
            bus.emit("peer_lost", peer)
            for callback in list(self.on_peer_lost):
                callback(dict(peer))

    def _process_payload(self, data: bytes, addr=None, now: Optional[float] = None) -> None:
        now = now or time.time()
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return

        peer_id = payload.get("peer_id")
        name = payload.get("name")
        ip = payload.get("ip") or (addr[0] if addr else None)
        tcp_port = payload.get("tcp_port")
        if not peer_id or peer_id == self.peer_id or not name or not ip or not tcp_port:
            return

        existing = self._peers.get(peer_id)
        record = {
            "name": name,
            "ip": ip,
            "tcp_port": tcp_port,
            "last_seen": now_iso(),
            "last_seen_monotonic": now,
            "peer_id": peer_id,
            "status_message": payload.get("status_message", "Available"),
            "avatar": payload.get("avatar", "LL"),
            "interfaces": payload.get("interfaces", [ip]),
            "online": True,
        }
        self._peers[peer_id] = record
        if existing is None:
            bus.emit("peer_discovered", record)
            for callback in list(self.on_peer_discovered):
                callback(dict(record))
