import asyncio
import shlex
import uuid
import webbrowser
from pathlib import Path
from typing import Optional

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

from . import storage
from .config import load_config, save_config, set_app_dir
from .discovery import DiscoveryService
from .group import GroupManager
from .peer import Peer
from .utils import format_timestamp, generate_chat_id


def _apply_profile(profile: str) -> None:
    if profile and profile != "default":
        set_app_dir(str(Path.home() / ".linklocal" / "profiles" / profile))
    else:
        set_app_dir(None)


def _message_text(message: dict) -> str:
    if message.get("is_deleted") or message.get("deleted"):
        return "This message was deleted"
    return message.get("display_content") or message.get("content") or "[ephemeral message]"


async def _interactive_chat(peer: Peer, groups: GroupManager, initial_group: Optional[str] = None) -> None:
    session = PromptSession("> ")
    state = {"peer_id": None, "group_id": initial_group}

    def handle_message(data: dict) -> None:
        active = state["group_id"] or (generate_chat_id(peer.peer_id, state["peer_id"]) if state["peer_id"] else None)
        target = data.get("group_id") or data.get("chat_id")
        marker = "*" if target == active else " "
        text = _message_text(data)
        line = f"{marker} [{format_timestamp(data['timestamp'])}] {data['sender_name']}: {text}"
        if data.get("is_edited"):
            line += " (edited)"
        click.echo(line)

    def handle_reaction(data: dict) -> None:
        click.echo(f"  [reaction] {data['sender_id']} reacted {data['emoji']} to {data['message_id']}")

    def handle_typing(data: dict) -> None:
        click.echo(f"  [typing] {data['sender_id']} is typing...")

    def handle_seen(data: dict) -> None:
        click.echo(f"  [seen] {data['sender_id']} saw {data['message_id']}")

    def handle_online(data: dict) -> None:
        click.echo(f"  [online] {data['name']} ({data['peer_id']})")

    def handle_offline(data: dict) -> None:
        click.echo(f"  [offline] {data['name']} ({data['peer_id']})")

    peer.on_message(handle_message)
    peer.on_reaction(handle_reaction)
    peer.on_typing(handle_typing)
    peer.on_seen(handle_seen)
    peer.on_peer_online(handle_online)
    peer.on_peer_offline(handle_offline)

    help_text = (
        "Commands: /help /peers /groups /use-peer <peer_id> /use-group <group_id> "
        "/react <message_id> <emoji> /edit <message_id> <text> /delete <message_id> "
        "/reply <message_id> <text> /rename-group <new name> /kick <peer_id> /leave-group /quit"
    )
    click.echo(help_text)

    with patch_stdout():
        while True:
            raw = await session.prompt_async()
            if not raw.strip():
                continue
            if raw.startswith("/"):
                args = shlex.split(raw)
                command = args[0]
                if command == "/help":
                    click.echo(help_text)
                elif command == "/peers":
                    for found in peer.discover():
                        click.echo(f"{found['peer_id']}  {found['name']}  {found['ip']}:{found['tcp_port']}")
                elif command == "/groups":
                    groups.load_groups()
                    for group in groups.list_groups():
                        click.echo(f"{group.group_id}  {group.group_name}  members={len(group.members)}")
                elif command == "/use-peer" and len(args) > 1:
                    state["peer_id"] = args[1]
                    state["group_id"] = None
                    click.echo(f"Active direct chat: {args[1]}")
                elif command == "/use-group" and len(args) > 1:
                    state["group_id"] = args[1]
                    state["peer_id"] = None
                    click.echo(f"Active group chat: {args[1]}")
                elif command == "/react" and len(args) > 2:
                    if state["group_id"]:
                        click.echo("Group reactions are not available from the terminal UI yet.")
                    elif state["peer_id"]:
                        await peer.send_reaction(args[1], args[2], state["peer_id"])
                elif command == "/edit" and len(args) > 2 and state["peer_id"]:
                    await peer.edit_message(args[1], " ".join(args[2:]), state["peer_id"])
                elif command == "/delete" and len(args) > 1 and state["peer_id"]:
                    await peer.delete_message(args[1], state["peer_id"])
                elif command == "/reply" and len(args) > 2:
                    if state["group_id"]:
                        await groups.send_group_text(state["group_id"], " ".join(args[2:]), reply_to_id=args[1])
                    elif state["peer_id"]:
                        await peer.reply_to(args[1], " ".join(args[2:]), state["peer_id"])
                elif command == "/rename-group" and len(args) > 1 and state["group_id"]:
                    await groups.rename_group(state["group_id"], " ".join(args[1:]))
                elif command == "/kick" and len(args) > 1 and state["group_id"]:
                    await groups.kick_member(state["group_id"], args[1])
                elif command == "/leave-group" and state["group_id"]:
                    await groups.leave_group(state["group_id"])
                    state["group_id"] = None
                elif command == "/quit":
                    break
                else:
                    click.echo("Unknown command or missing arguments. Use /help.")
                continue

            if state["group_id"]:
                await groups.send_group_text(state["group_id"], raw)
            elif state["peer_id"]:
                await peer.send(raw, state["peer_id"])
            else:
                click.echo("Choose a conversation first with /use-peer or /use-group.")


@click.group()
def cli() -> None:
    """LinkLocal command line interface."""


@cli.command("start")
@click.option("--name", required=False, help="Display name for this peer.")
@click.option("--gui", is_flag=True, help="Launch the Tkinter GUI.")
@click.option("--profile", default="default", show_default=True, help="Optional local profile name.")
def start_command(name: Optional[str], gui: bool, profile: str) -> None:
    _apply_profile(profile)
    if gui:
        from linklocal.gui import run_gui

        run_gui(name=name, profile=profile)
        return

    async def runner() -> None:
        peer = Peer(name)
        groups = GroupManager(peer)
        await peer.start()
        try:
            await _interactive_chat(peer, groups)
        finally:
            await peer.stop()

    asyncio.run(runner())


@cli.command("list")
@click.option("--profile", default="default", show_default=True, help="Optional local profile name.")
def list_command(profile: str) -> None:
    _apply_profile(profile)

    async def runner() -> None:
        service = DiscoveryService(
            display_name="LinkLocal Lister",
            peer_id=str(uuid.uuid4()),
            tcp_port=0,
        )
        await service.start()
        try:
            await asyncio.sleep(3)
            peers = service.get_peers()
        finally:
            await service.stop()
        if not peers:
            click.echo("No peers discovered.")
            return
        for peer_id, info in peers.items():
            click.echo(f"{peer_id}  {info['name']}  {info['ip']}:{info['tcp_port']}")

    asyncio.run(runner())


@cli.command("join")
@click.option("--group", "group_code", required=True, help="Group code to join.")
@click.option("--name", required=True, help="Display name for this peer.")
@click.option("--profile", default="default", show_default=True, help="Optional local profile name.")
def join_command(group_code: str, name: str, profile: str) -> None:
    _apply_profile(profile)

    async def runner() -> None:
        peer = Peer(name)
        groups = GroupManager(peer)
        await peer.start()
        try:
            await asyncio.sleep(3)
            joined = await groups.join_group(group_code)
            click.echo(f"Joined {joined.group_name} ({joined.group_id})")
            await _interactive_chat(peer, groups, initial_group=joined.group_id)
        finally:
            await peer.stop()

    asyncio.run(runner())


@cli.command("create-group")
@click.option("--name", "group_name", required=True, help="Name of the group to create.")
@click.option("--display-name", required=False, help="Display name for this peer.")
@click.option("--password", required=False, help="Optional group password.")
@click.option("--persist/--no-persist", default=False, help="Persist group chat history.")
@click.option("--profile", default="default", show_default=True, help="Optional local profile name.")
def create_group_command(group_name: str, display_name: Optional[str], password: Optional[str], persist: bool, profile: str) -> None:
    _apply_profile(profile)

    async def runner() -> None:
        peer = Peer(display_name or group_name + " Admin")
        groups = GroupManager(peer)
        await peer.start()
        try:
            group = groups.create_group(group_name, password=password or None, persist=persist)
            click.echo(f"Group created: {group.group_name}")
            click.echo(f"Join code: {group.group_id}")
            await _interactive_chat(peer, groups, initial_group=group.group_id)
        finally:
            await peer.stop()

    asyncio.run(runner())


@cli.command("superuser")
@click.option("--profile", default="default", show_default=True, help="Optional local profile name.")
def superuser_command(profile: str) -> None:
    _apply_profile(profile)
    webbrowser.open("http://127.0.0.1:5050/")
    from .superuser.dashboard import run_dashboard

    run_dashboard()


@cli.command("history")
@click.argument("target_id")
@click.option("--profile", default="default", show_default=True)
@click.option("--limit", default=25, show_default=True)
def history_command(target_id: str, profile: str, limit: int) -> None:
    _apply_profile(profile)
    chat_id = target_id if target_id in {group["group_id"] for group in storage.list_group_meta()} else generate_chat_id(load_config()["peer_id"], target_id)
    for message in storage.load_history(chat_id)[-limit:]:
        click.echo(f"[{format_timestamp(message['timestamp'])}] {message['sender_name']}: {_message_text(message)}")


@cli.command("export")
@click.argument("target_id")
@click.option("--profile", default="default", show_default=True)
@click.option("--format", "export_format", type=click.Choice(["txt", "md"]), default="txt", show_default=True)
def export_command(target_id: str, profile: str, export_format: str) -> None:
    _apply_profile(profile)
    chat_id = target_id if target_id in {group["group_id"] for group in storage.list_group_meta()} else generate_chat_id(load_config()["peer_id"], target_id)
    history = storage.load_history(chat_id)
    suffix = "md" if export_format == "md" else "txt"
    output_path = Path.cwd() / f"{chat_id}.{suffix}"
    lines = []
    for message in history:
        line = f"[{format_timestamp(message['timestamp'])}] {message['sender_name']}: {_message_text(message)}"
        lines.append(f"- {line}" if export_format == "md" else line)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    click.echo(f"Exported to {output_path}")


@cli.group("config")
def config_group() -> None:
    """Manage local config."""


@config_group.command("set")
@click.argument("key")
@click.argument("value")
@click.option("--profile", default="default", show_default=True)
def config_set_command(key: str, value: str, profile: str) -> None:
    _apply_profile(profile)
    config = load_config()
    if value.lower() in {"true", "false"}:
        parsed_value = value.lower() == "true"
    else:
        try:
            parsed_value = int(value)
        except ValueError:
            parsed_value = value
    config[key] = parsed_value
    save_config(config)
    click.echo(f"Set {key} = {parsed_value}")


@cli.command("ping")
@click.argument("peer_id")
@click.option("--name", default=None)
@click.option("--profile", default="default", show_default=True)
def ping_command(peer_id: str, name: Optional[str], profile: str) -> None:
    _apply_profile(profile)

    async def runner() -> None:
        peer = Peer(name)
        GroupManager(peer)
        await peer.start()
        try:
            await asyncio.sleep(1)
            latency = await peer.ping(peer_id)
            click.echo(f"{peer_id}: {latency:.2f} ms" if latency is not None else f"{peer_id}: no response")
        finally:
            await peer.stop()

    asyncio.run(runner())


@cli.command("simulate-peer")
@click.option("--name", default="SimPeer", show_default=True)
@click.option("--profile", default="simulator", show_default=True)
@click.option("--message", default="hello from simulator", show_default=True)
def simulate_peer_command(name: str, profile: str, message: str) -> None:
    _apply_profile(profile)
    from .simulator import run_simulated_peer

    asyncio.run(run_simulated_peer(name=name, scripted_message=message))
