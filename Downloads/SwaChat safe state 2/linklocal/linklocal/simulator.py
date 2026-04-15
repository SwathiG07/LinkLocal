import asyncio
from typing import Optional

from .group import GroupManager
from .peer import Peer


async def run_simulated_peer(name: str = "SimPeer", scripted_message: str = "hello from simulator") -> None:
    peer = Peer(name)
    GroupManager(peer)
    await peer.start()
    try:
        await asyncio.sleep(3)
        discovered = peer.discover()
        if discovered:
            await peer.send(scripted_message, discovered[0]["peer_id"])
        await asyncio.sleep(5)
    finally:
        await peer.stop()
