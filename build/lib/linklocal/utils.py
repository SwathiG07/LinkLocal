import hashlib
import random
import secrets
import socket
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List


WORDS = [
    "TIGER",
    "RIVER",
    "FALCON",
    "CEDAR",
    "LOTUS",
    "MAPLE",
    "PANTHER",
    "GLACIER",
    "CORAL",
    "THUNDER",
    "MEADOW",
    "WILLOW",
    "EMBER",
    "SUMMIT",
    "OCEAN",
    "PEBBLE",
    "MONSOON",
    "ORCHID",
    "FOREST",
    "BISON",
    "HERON",
    "CANYON",
    "DAWN",
    "MIST",
    "LYNX",
    "SPARROW",
    "BAMBOO",
    "CLOUD",
    "CLIFF",
    "BREEZE",
    "NOVA",
    "SEQUOIA",
    "RAVEN",
    "DUNE",
    "VALLEY",
    "KOALA",
    "AURORA",
    "OTTER",
    "RIDGE",
    "CYPRESS",
    "MARLIN",
    "GROVE",
    "COMET",
    "BADGER",
    "RAINFOREST",
    "SPRING",
    "EAGLE",
    "ISLAND",
    "TUNDRA",
    "GEYSER",
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def get_local_ips() -> List[str]:
    ips = {get_local_ip()}
    try:
        hostname = socket.gethostname()
        for result in socket.getaddrinfo(hostname, None, socket.AF_INET):
            candidate = result[4][0]
            if candidate and not candidate.startswith("127."):
                ips.add(candidate)
    except OSError:
        pass
    return sorted(ips)


def generate_group_code() -> str:
    return f"{random.choice(WORDS)}-{random.randint(1000, 9999)}"


def generate_invite_token() -> str:
    return secrets.token_urlsafe(18)


def build_invite_link(group_id: str, token: str) -> str:
    return f"linklocal://join/{group_id}?token={token}"


def extract_group_code(candidate: str) -> str:
    if candidate.startswith("linklocal://join/"):
        return candidate.split("/", 3)[-1].split("?", 1)[0]
    return candidate.strip().upper()


def extract_invite_token(candidate: str) -> str:
    if "?token=" in candidate:
        return candidate.split("?token=", 1)[1].strip()
    return ""


def format_timestamp(iso_string: str) -> str:
    dt = datetime.fromisoformat(iso_string)
    now = datetime.now(dt.tzinfo)
    local_time = dt.strftime("%I:%M %p").lstrip("0")
    if dt.date() == now.date():
        return local_time
    if dt.date() == (now - timedelta(days=1)).date():
        return f"Yesterday {local_time}"
    return dt.strftime("%Y-%m-%d %I:%M %p").lstrip("0")


def format_relative_time(iso_string: str) -> str:
    dt = datetime.fromisoformat(iso_string)
    delta = datetime.now(dt.tzinfo) - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} hr ago"
    return f"{seconds // 86400} day(s) ago"


def truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    return f"{text[: max_length - 3]}..."


def generate_chat_id(peer_id_a: str, peer_id_b: str) -> str:
    return "_".join(sorted([peer_id_a, peer_id_b]))


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fingerprint_text(value: str, length: int = 12) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest().upper()
    groups = [digest[i : i + 4] for i in range(0, min(length, len(digest)), 4)]
    return "-".join(groups)


def safety_number(parts: Iterable[str]) -> str:
    digest = hashlib.sha256("".join(sorted(parts)).encode("utf-8")).hexdigest()
    return " ".join(digest[i : i + 5] for i in range(0, 25, 5))


def format_bytes(size: int) -> str:
    value = float(size)
    for unit in ["B", "KB", "MB", "GB"]:
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{int(size)} B"


def ensure_initials(value: str) -> str:
    cleaned = "".join(ch for ch in value.strip() if ch.isalnum() or ch.isspace())
    words = [part for part in cleaned.split() if part]
    if not words:
        return "LL"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def slugify_filename(path: str) -> str:
    return Path(path).name.replace(" ", "_")
