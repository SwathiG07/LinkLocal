import json

from linklocal.discovery import DiscoveryService


def test_discovery_adds_peer_from_valid_broadcast():
    service = DiscoveryService(
        display_name="Self",
        peer_id="self-peer",
        tcp_port=55556,
        udp_port=55555,
    )
    payload = json.dumps(
        {
            "name": "Alice",
            "ip": "192.168.1.10",
            "tcp_port": 55560,
            "peer_id": "peer-alice",
        }
    ).encode("utf-8")

    service._process_payload(payload, now=100.0)

    peers = service.get_peers()
    assert "peer-alice" in peers
    assert peers["peer-alice"]["name"] == "Alice"
    assert peers["peer-alice"]["ip"] == "192.168.1.10"


def test_discovery_expires_stale_peer():
    service = DiscoveryService(
        display_name="Self",
        peer_id="self-peer",
        tcp_port=55556,
        udp_port=55555,
        peer_timeout=15,
    )
    payload = json.dumps(
        {
            "name": "Bob",
            "ip": "192.168.1.11",
            "tcp_port": 55561,
            "peer_id": "peer-bob",
        }
    ).encode("utf-8")

    service._process_payload(payload, now=100.0)
    service.expire_peers(now=116.0)

    assert service.get_peers() == {}
