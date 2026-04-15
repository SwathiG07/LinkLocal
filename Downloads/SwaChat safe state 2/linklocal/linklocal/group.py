import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from . import storage
from .crypto import encrypt_message
from .utils import build_invite_link, extract_group_code, extract_invite_token, generate_group_code, generate_invite_token, now_iso


def _hash_password(password: Optional[str]) -> Optional[str]:
    if not password:
        return None
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


@dataclass
class Group:
    group_id: str
    group_name: str
    admin_peer_id: str
    members: List[Dict[str, Any]] = field(default_factory=list)
    persist_history: bool = False
    password: Optional[str] = None
    co_admin_ids: List[str] = field(default_factory=list)
    announcement_only: bool = False
    description: str = ""
    rules: str = ""
    pinned_message_id: Optional[str] = None
    invite_links: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        group_name: str,
        admin_peer_id: str,
        password: Optional[str] = None,
        persist: bool = False,
        admin_display_name: Optional[str] = None,
        description: str = "",
        rules: str = "",
    ) -> "Group":
        while True:
            group_id = generate_group_code()
            try:
                storage.load_group_meta(group_id)
            except FileNotFoundError:
                break
        group = cls(
            group_id=group_id,
            group_name=group_name,
            admin_peer_id=admin_peer_id,
            members=[{"peer_id": admin_peer_id, "display_name": admin_display_name or admin_peer_id, "joined_at": now_iso()}],
            persist_history=persist,
            password=_hash_password(password),
            description=description,
            rules=rules,
        )
        storage.save_group_meta(group.group_id, group.to_dict())
        return group

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Group":
        return cls(
            group_id=data["group_id"],
            group_name=data["group_name"],
            admin_peer_id=data["admin_peer_id"],
            members=list(data.get("members", [])),
            persist_history=bool(data.get("persist_history", False)),
            password=data.get("password"),
            co_admin_ids=list(data.get("co_admin_ids", [])),
            announcement_only=bool(data.get("announcement_only", False)),
            description=data.get("description", ""),
            rules=data.get("rules", ""),
            pinned_message_id=data.get("pinned_message_id"),
            invite_links=list(data.get("invite_links", [])),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "group_name": self.group_name,
            "admin_peer_id": self.admin_peer_id,
            "members": self.members,
            "persist_history": self.persist_history,
            "password": self.password,
            "co_admin_ids": self.co_admin_ids,
            "announcement_only": self.announcement_only,
            "description": self.description,
            "rules": self.rules,
            "pinned_message_id": self.pinned_message_id,
            "invite_links": self.invite_links,
        }

    def save(self) -> None:
        storage.save_group_meta(self.group_id, self.to_dict())

    def is_admin(self, peer_id: str) -> bool:
        return peer_id == self.admin_peer_id or peer_id in self.co_admin_ids

    def validate_invite(self, candidate: str) -> bool:
        token = extract_invite_token(candidate)
        if not token:
            return False
        now = datetime.now()
        for invite in self.invite_links:
            if invite["token"] == token and datetime.fromisoformat(invite["expires_at"]) > now:
                return True
        return False

    def generate_invite(self, expiry_minutes: int = 30) -> str:
        token = generate_invite_token()
        self.invite_links.append(
            {
                "token": token,
                "expires_at": (datetime.now() + timedelta(minutes=expiry_minutes)).isoformat(timespec="seconds"),
            }
        )
        self.save()
        return build_invite_link(self.group_id, token)

    def join(self, requesting_peer: Dict[str, str], password: Optional[str] = None, invite_candidate: Optional[str] = None) -> Dict[str, Any]:
        if self.password and self.password != _hash_password(password):
            if not invite_candidate or not self.validate_invite(invite_candidate):
                raise PermissionError("Invalid group password or invite link")
        if requesting_peer["peer_id"] not in {member["peer_id"] for member in self.members}:
            self.members.append(
                {
                    "peer_id": requesting_peer["peer_id"],
                    "display_name": requesting_peer["display_name"],
                    "joined_at": now_iso(),
                }
            )
            self.save()
        return self.to_dict()

    def leave(self, peer_id: str) -> Dict[str, Any]:
        self.members = [member for member in self.members if member["peer_id"] != peer_id]
        if peer_id in self.co_admin_ids:
            self.co_admin_ids.remove(peer_id)
        self.save()
        return self.to_dict()

    def kick(self, target_peer_id: str, requester_peer_id: str) -> Dict[str, Any]:
        if not self.is_admin(requester_peer_id):
            raise PermissionError("Only an admin can kick members")
        self.members = [member for member in self.members if member["peer_id"] != target_peer_id]
        if target_peer_id in self.co_admin_ids:
            self.co_admin_ids.remove(target_peer_id)
        self.save()
        return self.to_dict()

    def rename(self, new_name: str, requester_peer_id: str) -> Dict[str, Any]:
        if not self.is_admin(requester_peer_id):
            raise PermissionError("Only an admin can rename the group")
        self.group_name = new_name
        self.save()
        return self.to_dict()

    def promote(self, target_peer_id: str, requester_peer_id: str) -> Dict[str, Any]:
        if requester_peer_id != self.admin_peer_id:
            raise PermissionError("Only the admin can promote co-admins")
        if target_peer_id not in self.co_admin_ids:
            self.co_admin_ids.append(target_peer_id)
        self.save()
        return self.to_dict()

    def set_announcement_only(self, enabled: bool, requester_peer_id: str) -> Dict[str, Any]:
        if not self.is_admin(requester_peer_id):
            raise PermissionError("Only an admin can change announcement mode")
        self.announcement_only = enabled
        self.save()
        return self.to_dict()

    def set_meta(self, *, description: Optional[str] = None, rules: Optional[str] = None, requester_peer_id: str) -> Dict[str, Any]:
        if not self.is_admin(requester_peer_id):
            raise PermissionError("Only an admin can update group details")
        if description is not None:
            self.description = description
        if rules is not None:
            self.rules = rules
        self.save()
        return self.to_dict()

    def pin_message(self, message_id: str, requester_peer_id: str) -> Dict[str, Any]:
        if not self.is_admin(requester_peer_id):
            raise PermissionError("Only an admin can pin messages")
        self.pinned_message_id = message_id
        self.save()
        return self.to_dict()

    def get_members(self, discovery_registry: Dict[str, Dict[str, Any]], local_peer_id: Optional[str] = None) -> List[Dict[str, Any]]:
        online_ids = set(discovery_registry.keys())
        return [
            {
                **member,
                "online": member["peer_id"] in online_ids or member["peer_id"] == local_peer_id,
                "is_admin": self.is_admin(member["peer_id"]),
            }
            for member in self.members
        ]


class GroupManager:
    def __init__(self, peer) -> None:
        self.peer = peer
        self.groups: Dict[str, Group] = {}
        self.load_groups()
        self.peer.set_group_handler(self.handle_payload)

    def load_groups(self) -> None:
        self.groups = {}
        for data in storage.list_group_meta():
            try:
                group = Group.from_dict(data)
            except KeyError:
                continue
            self.groups[group.group_id] = group

    def list_groups(self) -> List[Group]:
        return list(self.groups.values())

    def get_group(self, group_id_or_link: str) -> Group:
        group_id = extract_group_code(group_id_or_link)
        if group_id not in self.groups:
            self.groups[group_id] = Group.from_dict(storage.load_group_meta(group_id))
        return self.groups[group_id]

    def delete_group(self, group_id: str) -> None:
        if group_id in self.groups:
            del self.groups[group_id]
        storage.delete_group_meta(group_id)
        storage.delete_history(group_id)

    def create_group(
        self,
        group_name: str,
        password: Optional[str] = None,
        persist: bool = False,
        *,
        description: str = "",
        rules: str = "",
    ) -> Group:
        group = Group.create(
            group_name=group_name,
            admin_peer_id=self.peer.peer_id,
            password=password,
            persist=persist,
            admin_display_name=self.peer.display_name,
            description=description,
            rules=rules,
        )
        self.groups[group.group_id] = group
        return group

    async def join_group(self, group_id_or_link: str, password: Optional[str] = None) -> Group:
        group_id = extract_group_code(group_id_or_link)
        invite_candidate = group_id_or_link if group_id_or_link.startswith("linklocal://join/") else None
        for peer_info in self.peer.discover():
            payload = self.peer._base_payload("group_meta")
            payload.update(
                {
                    "action": "join_request",
                    "group_id": group_id,
                    "requesting_peer": {"peer_id": self.peer.peer_id, "display_name": self.peer.display_name},
                    "password": password,
                    "invite_candidate": invite_candidate,
                }
            )
            try:
                response = await self.peer.send_command(peer_info["peer_id"], payload, require_encryption=False, expect_response=True)
            except Exception:
                continue
            if response and response.get("ok"):
                group = Group.from_dict(response["group"])
                self.groups[group.group_id] = group
                storage.save_group_meta(group.group_id, group.to_dict())
                return group
        raise FileNotFoundError(f"Group {group_id} was not found on the local network")

    async def leave_group(self, group_id: str) -> None:
        group = self.get_group(group_id)
        if group.admin_peer_id == self.peer.peer_id:
            group.leave(self.peer.peer_id)
            self.groups[group_id] = group
            return
        payload = self.peer._base_payload("group_meta")
        payload.update({"action": "leave_request", "group_id": group_id, "peer_id": self.peer.peer_id})
        await self.peer.send_command(group.admin_peer_id, payload, require_encryption=False)
        group.leave(self.peer.peer_id)
        storage.save_group_meta(group_id, group.to_dict())

    async def rename_group(self, group_id: str, new_name: str) -> None:
        await self._send_admin_action(group_id, "rename_request", {"new_name": new_name})

    async def promote_member(self, group_id: str, target_peer_id: str) -> None:
        await self._send_admin_action(group_id, "promote_request", {"target_peer_id": target_peer_id})

    async def kick_member(self, group_id: str, target_peer_id: str) -> None:
        await self._send_admin_action(group_id, "kick_request", {"target_peer_id": target_peer_id})

    async def toggle_announcement_only(self, group_id: str, enabled: bool) -> None:
        await self._send_admin_action(group_id, "announcement_request", {"enabled": enabled})

    async def update_group_meta(self, group_id: str, *, description: Optional[str] = None, rules: Optional[str] = None) -> None:
        await self._send_admin_action(group_id, "meta_request", {"description": description, "rules": rules})

    async def pin_message(self, group_id: str, message_id: str) -> None:
        await self._send_admin_action(group_id, "pin_request", {"message_id": message_id})

    async def create_invite_link(self, group_id: str, expiry_minutes: int = 30) -> str:
        group = self.get_group(group_id)
        if group.admin_peer_id == self.peer.peer_id:
            return group.generate_invite(expiry_minutes)
        payload = self.peer._base_payload("group_meta")
        payload.update({"action": "invite_request", "group_id": group_id, "expiry_minutes": expiry_minutes})
        response = await self.peer.send_command(group.admin_peer_id, payload, require_encryption=False, expect_response=True)
        if not response or not response.get("ok"):
            raise PermissionError(response.get("error", "Unable to create invite"))
        return response["invite_link"]

    async def send_group_text(
        self,
        group_id: str,
        text: str,
        reply_to_id: Optional[str] = None,
        *,
        forwarded_from: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        delete_on_seen: bool = False,
        message_type: str = "group_message",
    ) -> Dict[str, Any]:
        group = self.get_group(group_id)
        if group.announcement_only and not group.is_admin(self.peer.peer_id):
            raise PermissionError("This group is announcement-only")
        message_id = str(uuid.uuid4())
        timestamp = now_iso()
        record = self.peer._message_record(
            message_id=message_id,
            sender_id=self.peer.peer_id,
            sender_name=self.peer.display_name,
            content=text if group.persist_history else None,
            display_content=text,
            timestamp=timestamp,
            message_type=message_type,
            reply_to_id=reply_to_id,
            group_id=group_id,
            chat_id=group_id,
            forwarded_from=forwarded_from,
            ttl_seconds=ttl_seconds,
            delete_on_seen=delete_on_seen,
        )
        storage.save_message(group_id, record)
        for member in group.members:
            if member["peer_id"] == self.peer.peer_id:
                continue
            await self.peer.send_group_message(
                group_id,
                text,
                member["peer_id"],
                message_id=message_id,
                reply_to_id=reply_to_id,
                message_type=message_type,
                forwarded_from=forwarded_from,
                ttl_seconds=ttl_seconds,
                delete_on_seen=delete_on_seen,
            )
        self.peer._emit("message", record)
        return record

    async def send_group_poll(self, group_id: str, question: str, options: List[str]) -> Dict[str, Any]:
        group = self.get_group(group_id)
        message_id = str(uuid.uuid4())
        record = self.peer._message_record(
            message_id=message_id,
            sender_id=self.peer.peer_id,
            sender_name=self.peer.display_name,
            content=question,
            display_content=question,
            timestamp=now_iso(),
            message_type="poll",
            group_id=group_id,
            chat_id=group_id,
        )
        record["poll"] = {"question": question, "options": options}
        storage.save_message(group_id, record)
        for member in group.members:
            if member["peer_id"] == self.peer.peer_id:
                continue
            await self.peer.send_poll(question, options, member["peer_id"], group_id=group_id, message_id=message_id)
        self.peer._emit("message", record)
        return record

    async def send_group_reaction(self, group_id: str, message_id: str, emoji: str) -> None:
        group = self.get_group(group_id)
        for member in group.members:
            if member["peer_id"] == self.peer.peer_id:
                continue
            await self.peer.send_reaction(message_id, emoji, member["peer_id"], group_id=group_id)
        self.peer._apply_reaction(group_id, message_id, emoji, self.peer.peer_id)
        self.peer._emit("reaction", {"message_id": message_id, "emoji": emoji, "sender_id": self.peer.peer_id, "chat_id": group_id, "group_id": group_id})

    async def edit_group_message(self, group_id: str, message_id: str, new_text: str) -> None:
        group = self.get_group(group_id)
        for member in group.members:
            if member["peer_id"] == self.peer.peer_id:
                continue
            await self.peer.edit_message(message_id, new_text, member["peer_id"], group_id=group_id)
        previous = self.peer._find_message(group_id, message_id)
        edit_history = list(previous.get("edit_history", []))
        previous_text = previous.get("display_content") or previous.get("content")
        if previous_text:
            edit_history.append(previous_text)
        storage.update_message(group_id, message_id, {"content": new_text if group.persist_history else None, "display_content": new_text, "is_edited": True, "edit_history": edit_history})
        self.peer._emit("message", {"message_id": message_id, "content": new_text, "display_content": new_text, "chat_id": group_id, "group_id": group_id, "is_edited": True})

    async def delete_group_message(self, group_id: str, message_id: str) -> None:
        group = self.get_group(group_id)
        for member in group.members:
            if member["peer_id"] == self.peer.peer_id:
                continue
            await self.peer.delete_message(message_id, member["peer_id"], group_id=group_id)
        storage.delete_message_record(group_id, message_id)
        self.peer._emit("message", {"message_id": message_id, "chat_id": group_id, "group_id": group_id, "deleted": True})

    async def send_group_typing(self, group_id: str) -> None:
        group = self.get_group(group_id)
        for member in group.members:
            if member["peer_id"] == self.peer.peer_id:
                continue
            await self.peer.send_typing(member["peer_id"], group_id=group_id)

    async def vote_group_poll(self, group_id: str, poll_id: str, option: str) -> None:
        group = self.get_group(group_id)
        for member in group.members:
            if member["peer_id"] == self.peer.peer_id:
                continue
            await self.peer.vote_poll(poll_id, option, member["peer_id"], group_id=group_id)
        message = self.peer._find_message(group_id, poll_id)
        votes = dict(message.get("poll_votes", {}))
        votes[self.peer.peer_id] = option
        storage.update_message(group_id, poll_id, {"poll_votes": votes})
        self.peer._emit("message", {"message_id": poll_id, "chat_id": group_id, "group_id": group_id, "poll_votes": votes})

    async def broadcast_announcement(self, text: str) -> None:
        for group in self.list_groups():
            if group.admin_peer_id == self.peer.peer_id:
                await self.send_group_text(group.group_id, text, message_type="announcement")

    async def handle_payload(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        message_type = payload.get("type")
        if message_type == "group_meta":
            return await self._handle_group_meta(payload)
        if message_type == "superuser_query":
            return await self._handle_superuser_query(payload)
        return None

    async def _send_admin_action(self, group_id: str, action: str, extra: Dict[str, Any]) -> None:
        group = self.get_group(group_id)
        if group.admin_peer_id == self.peer.peer_id:
            await self._apply_local_admin_action(group, action, extra)
            return
        payload = self.peer._base_payload("group_meta")
        payload.update({"action": action, "group_id": group_id, **extra})
        response = await self.peer.send_command(group.admin_peer_id, payload, require_encryption=False, expect_response=True)
        if not response or not response.get("ok"):
            raise PermissionError(response.get("error", "Group action failed"))

    async def _apply_local_admin_action(self, group: Group, action: str, extra: Dict[str, Any]) -> None:
        if action == "rename_request":
            group.rename(extra["new_name"], self.peer.peer_id)
        elif action == "promote_request":
            group.promote(extra["target_peer_id"], self.peer.peer_id)
        elif action == "kick_request":
            group.kick(extra["target_peer_id"], self.peer.peer_id)
        elif action == "announcement_request":
            group.set_announcement_only(extra["enabled"], self.peer.peer_id)
        elif action == "meta_request":
            group.set_meta(description=extra.get("description"), rules=extra.get("rules"), requester_peer_id=self.peer.peer_id)
        elif action == "pin_request":
            group.pin_message(extra["message_id"], self.peer.peer_id)
        self.groups[group.group_id] = group
        await self._broadcast_state(group, action="state_update")

    async def _handle_group_meta(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        action = payload.get("action")
        group_id = payload.get("group_id")
        if not group_id:
            return {"ok": False, "error": "Missing group_id"}
        try:
            group = self.get_group(group_id)
        except FileNotFoundError:
            group = None

        if action == "join_request":
            if group is None:
                return {"ok": False, "error": "Unknown group"}
            if group.admin_peer_id != self.peer.peer_id:
                return {"ok": False, "error": "Not group host"}
            try:
                group.join(payload["requesting_peer"], payload.get("password"), payload.get("invite_candidate"))
            except PermissionError as exc:
                return {"ok": False, "error": str(exc)}
            self.groups[group_id] = group
            await self._broadcast_state(group, action="state_update")
            return {"ok": True, "group": group.to_dict()}

        if action == "leave_request" and group is not None:
            if payload["peer_id"] != payload["sender_id"] and not group.is_admin(payload["sender_id"]):
                return {"ok": False, "error": "Not authorized"}
            if group.admin_peer_id == self.peer.peer_id:
                group.leave(payload["peer_id"])
                self.groups[group_id] = group
                await self._broadcast_state(group, action="state_update")
            return {"ok": True}

        if action in {"rename_request", "promote_request", "kick_request", "announcement_request", "meta_request", "pin_request"} and group is not None:
            try:
                if action == "rename_request":
                    group.rename(payload["new_name"], payload["sender_id"])
                elif action == "promote_request":
                    group.promote(payload["target_peer_id"], payload["sender_id"])
                elif action == "kick_request":
                    group.kick(payload["target_peer_id"], payload["sender_id"])
                elif action == "announcement_request":
                    group.set_announcement_only(payload["enabled"], payload["sender_id"])
                elif action == "meta_request":
                    group.set_meta(description=payload.get("description"), rules=payload.get("rules"), requester_peer_id=payload["sender_id"])
                elif action == "pin_request":
                    group.pin_message(payload["message_id"], payload["sender_id"])
            except PermissionError as exc:
                return {"ok": False, "error": str(exc)}
            self.groups[group_id] = group
            await self._broadcast_state(group, action="state_update")
            return {"ok": True, "group": group.to_dict()}

        if action == "invite_request" and group is not None:
            if not group.is_admin(payload["sender_id"]):
                return {"ok": False, "error": "Only admins can create invites"}
            return {"ok": True, "invite_link": group.generate_invite(int(payload.get("expiry_minutes", 30)))}

        if action == "send_scheduled_message" and group is not None:
            await self.send_group_text(group_id, payload["text"])
            return {"ok": True}

        if action == "state_update" and payload.get("group"):
            group = Group.from_dict(payload["group"])
            self.groups[group.group_id] = group
            storage.save_group_meta(group.group_id, group.to_dict())
            return {"ok": True}

        return {"ok": False, "error": f"Unsupported action {action}"}

    async def _handle_superuser_query(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        action = payload.get("action", "group_status")
        group_id = payload.get("group_id")
        if action == "list_groups":
            groups = [group.to_dict() for group in self.list_groups() if group.admin_peer_id == self.peer.peer_id]
            return {"ok": True, "groups": groups}
        if not group_id:
            return {"ok": False, "error": "Missing group_id"}
        group = self.get_group(group_id)
        if action == "group_status":
            data = group.to_dict()
            data["members"] = group.get_members(self.peer.discovery.get_peers(), self.peer.peer_id)
            response = {"ok": True, "group": data}
            if payload.get("include_chat_log") and payload.get("public_key"):
                public_key = self.peer.known_peer_public_keys.get(payload["sender_id"])
                if public_key is None:
                    public_key = self.peer._cache_public_key(payload["sender_id"], payload["public_key"])
                response.update(encrypt_message(json.dumps(storage.load_history(group_id)), public_key))
            return response
        if action == "kick_member":
            try:
                group.kick(payload["target_peer_id"], payload["sender_id"])
            except PermissionError as exc:
                return {"ok": False, "error": str(exc)}
            self.groups[group_id] = group
            await self._broadcast_state(group, action="state_update")
            return {"ok": True}
        if action == "broadcast_announcement":
            if not group.is_admin(payload["sender_id"]):
                return {"ok": False, "error": "Only admins can broadcast announcements"}
            await self.send_group_text(group_id, payload["text"], message_type="announcement")
            return {"ok": True}
        return {"ok": False, "error": f"Unsupported action {action}"}

    async def _broadcast_state(self, group: Group, action: str) -> None:
        payload = self.peer._base_payload("group_meta")
        payload.update({"action": action, "group_id": group.group_id, "group": group.to_dict()})
        for member in group.members:
            if member["peer_id"] == self.peer.peer_id:
                continue
            try:
                await self.peer.send_command(member["peer_id"], dict(payload), require_encryption=False)
            except Exception:
                continue
        storage.save_group_meta(group.group_id, group.to_dict())
