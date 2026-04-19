import asyncio
import base64
import threading
import tkinter as tk
from concurrent.futures import Future
from tkinter import filedialog, messagebox, simpledialog
from tkinter import ttk
from typing import Dict, Optional
import webbrowser
import sys
from pathlib import Path

try:
    import winsound
except ImportError:
    winsound = None

from .config import load_config

from . import storage
from .group import GroupManager
from .peer import Peer
from .utils import format_relative_time, format_timestamp, generate_chat_id, hash_text, now_iso, truncate


EMOJIS = ["👍", "❤️", "😂", "🔥", "👏", "😮", "🎉", "💯", "🤔", "👀", "🙌", "😢", "😡"]

# ── Clean color palette ──────────────────────────────────────────────
LIGHT_THEME = {
    "root": "#f5f5f5",
    "sidebar": "#1e293b",
    "sidebar_fg": "#f1f5f9",
    "muted_sidebar": "#94a3b8",
    "panel": "#ffffff",
    "composer": "#f8fafc",
    "text": "#1e293b",
    "muted": "#64748b",
    "accent": "#3b82f6",
    "self_bubble": "#dbeafe",
    "other_bubble": "#f1f5f9",
    "border": "#e2e8f0",
    "online": "#22c55e",
    "offline": "#94a3b8",
    "hover": "#334155",
    "send_btn": "#3b82f6",
}

DARK_THEME = {
    "root": "#0f172a",
    "sidebar": "#020617",
    "sidebar_fg": "#e2e8f0",
    "muted_sidebar": "#64748b",
    "panel": "#1e293b",
    "composer": "#0f172a",
    "text": "#e2e8f0",
    "muted": "#94a3b8",
    "accent": "#60a5fa",
    "self_bubble": "#1e3a5f",
    "other_bubble": "#334155",
    "border": "#334155",
    "online": "#4ade80",
    "offline": "#64748b",
    "hover": "#475569",
    "send_btn": "#3b82f6",
}


class LinkLocalGUI:
    def __init__(self, name: str) -> None:
        self.peer = Peer(name)
        self.groups = GroupManager(self.peer)
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self.loop_thread.start()
        self._run_async(self.peer.start()).result()

        self.root = tk.Tk()
        self.root.title(f"LinkLocal — {self.peer.display_name}")
        self.root.geometry("1100x700")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.peer_statuses: Dict[str, Dict] = {}
        self.current_kind: Optional[str] = None
        self.current_id: Optional[str] = None
        self.reply_to_id: Optional[str] = None
        self.typing_after_id = None
        self.dashboard_thread: Optional[threading.Thread] = None
        self.unread_counts: Dict[str, int] = {}
        self.search_results = []
        self.theme_name = self.peer.config.get("theme", "light")
        self.colors = DARK_THEME if self.theme_name == "dark" else LIGHT_THEME
        self._last_peer_ids: set = set()
        self._discovery_counter: int = 0

        self._build_layout()
        self._bind_events()
        self._refresh_sidebar()
        self.root.after(100, self._poll_events)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _run_async(self, coro) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    # ── Layout ────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        c = self.colors
        self.root.configure(bg=c["root"])
        container = tk.PanedWindow(self.root, sashrelief=tk.FLAT, sashwidth=1, bg=c["border"])
        container.pack(fill=tk.BOTH, expand=True)

        self.sidebar = tk.Frame(container, bg=c["sidebar"], width=280)
        self.chat_panel = tk.Frame(container, bg=c["panel"])
        container.add(self.sidebar, minsize=240)
        container.add(self.chat_panel)

        self._build_sidebar()
        self._build_chat_panel()

    def _build_sidebar(self) -> None:
        c = self.colors

        # ── Header
        header = tk.Frame(self.sidebar, bg=c["sidebar"], padx=16, pady=14)
        header.pack(fill=tk.X)
        tk.Label(header, text="LinkLocal", bg=c["sidebar"], fg=c["sidebar_fg"], font=("Segoe UI", 16, "bold"), anchor="w").pack(fill=tk.X)
        tk.Label(header, text=self.peer.display_name, bg=c["sidebar"], fg=c["muted_sidebar"], font=("Segoe UI", 10), anchor="w").pack(fill=tk.X)

        # ── Action buttons (compact row)
        btn_frame = tk.Frame(self.sidebar, bg=c["sidebar"], padx=12, pady=6)
        btn_frame.pack(fill=tk.X)
        for text, cmd in [("+ Group", self._create_group_dialog), ("Join", self._join_group_dialog), ("⚙", self._open_settings_dialog)]:
            tk.Button(btn_frame, text=text, command=cmd, bg=c["hover"], fg=c["sidebar_fg"],
                      relief=tk.FLAT, padx=8, pady=5, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=2, expand=True, fill=tk.X)

        # ── Search bar
        search_frame = tk.Frame(self.sidebar, bg=c["sidebar"], padx=12, pady=6)
        search_frame.pack(fill=tk.X)
        self.search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=self.search_var, relief=tk.FLAT,
                                bg=c["hover"], fg=c["sidebar_fg"], insertbackground=c["sidebar_fg"],
                                font=("Segoe UI", 10))
        search_entry.insert(0, "")
        search_entry.pack(fill=tk.X, ipady=5)
        search_entry.bind("<Return>", lambda event: self._search_messages())

        # ── Scrollable peer + group list
        list_container = tk.Frame(self.sidebar, bg=c["sidebar"])
        list_container.pack(fill=tk.BOTH, expand=True)

        self.sidebar_canvas = tk.Canvas(list_container, bg=c["sidebar"], highlightthickness=0, bd=0)
        self.sidebar_scroll = tk.Scrollbar(list_container, orient="vertical", command=self.sidebar_canvas.yview)
        self.sidebar_inner = tk.Frame(self.sidebar_canvas, bg=c["sidebar"])
        self.sidebar_inner.bind("<Configure>", lambda e: self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox("all")))
        self.sidebar_canvas.create_window((0, 0), window=self.sidebar_inner, anchor="nw", tags="inner")
        self.sidebar_canvas.configure(yscrollcommand=self.sidebar_scroll.set)
        self.sidebar_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.sidebar_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.sidebar_canvas.bind("<Configure>", lambda e: self.sidebar_canvas.itemconfig("inner", width=e.width))

        # Peer and group frames inside the scrollable area
        peers_label = tk.Label(self.sidebar_inner, text="PEERS", bg=c["sidebar"], fg=c["muted_sidebar"],
                 font=("Segoe UI", 9, "bold"), anchor="w", padx=16)
        peers_label.pack(fill=tk.X, pady=(8, 4))
        self.peers_frame = tk.Frame(self.sidebar_inner, bg=c["sidebar"])
        self.peers_frame.pack(fill=tk.X)

        groups_label = tk.Label(self.sidebar_inner, text="GROUPS", bg=c["sidebar"], fg=c["muted_sidebar"],
                 font=("Segoe UI", 9, "bold"), anchor="w", padx=16)
        groups_label.pack(fill=tk.X, pady=(12, 4))
        self.groups_frame = tk.Frame(self.sidebar_inner, bg=c["sidebar"])
        self.groups_frame.pack(fill=tk.X)

        # ── Bottom buttons
        bottom = tk.Frame(self.sidebar, bg=c["sidebar"], padx=12, pady=8)
        bottom.pack(fill=tk.X, side=tk.BOTTOM)
        for text, cmd in [("Add Peer", self._add_manual_peer_dialog), ("Dashboard", self._open_dashboard)]:
            tk.Button(bottom, text=text, command=cmd, bg=c["hover"], fg=c["sidebar_fg"],
                      relief=tk.FLAT, padx=8, pady=5, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=2, expand=True, fill=tk.X)

    def _build_chat_panel(self) -> None:
        c = self.colors
        self.title_var = tk.StringVar(value="Select a conversation")
        self.reply_var = tk.StringVar(value="")
        self.typing_var = tk.StringVar(value="")
        self.pin_var = tk.StringVar(value="")

        # ── Title bar
        title_bar = tk.Frame(self.chat_panel, bg=c["panel"], padx=20, pady=12)
        title_bar.pack(fill=tk.X)
        tk.Frame(title_bar, bg=c["border"], height=1).pack(fill=tk.X, side=tk.BOTTOM)
        tk.Label(title_bar, textvariable=self.title_var, bg=c["panel"], fg=c["text"],
                 font=("Segoe UI", 14, "bold")).pack(anchor="w")
        tk.Label(title_bar, textvariable=self.pin_var, bg=c["panel"], fg=c["accent"],
                 font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(title_bar, textvariable=self.reply_var, bg=c["panel"], fg=c["muted"],
                 font=("Segoe UI", 9)).pack(anchor="w")

        # ── Messages area
        msg_area = tk.Frame(self.chat_panel, bg=c["panel"])
        msg_area.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(msg_area, bg=c["panel"], highlightthickness=0)
        self.scrollbar = tk.Scrollbar(msg_area, orient="vertical", command=self.canvas.yview)
        self.messages_container = tk.Frame(self.canvas, bg=c["panel"])
        
        self.messages_container.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.messages_container, anchor="nw")
        
        def _on_canvas_resize(event):
            if event.width > 10:
                self.canvas.itemconfig(self.canvas_window, width=event.width)
        self.canvas.bind("<Configure>", _on_canvas_resize)
        
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # ── Typing indicator
        typing_bar = tk.Frame(self.chat_panel, bg=c["panel"], padx=20, pady=2)
        typing_bar.pack(fill=tk.X)
        tk.Label(typing_bar, textvariable=self.typing_var, bg=c["panel"], fg=c["muted"],
                 font=("Segoe UI", 9, "italic")).pack(anchor="w")

        # ── Toolbar (File, Audio, Poll, Clear)
        toolbar = tk.Frame(self.chat_panel, bg=c["composer"], padx=16, pady=4)
        toolbar.pack(fill=tk.X)
        tk.Frame(toolbar, bg=c["border"], height=1).pack(fill=tk.X, side=tk.TOP, pady=(0, 4))
        
        cmds = [("📎 File", self._send_file_dialog), ("🎤 Audio", self._send_audio_dialog), ("📊 Poll", self._create_poll_dialog), ("😊 Emoji", self._composer_emoji_picker)]
        for text, cmd in cmds:
            tk.Button(toolbar, text=text, command=cmd, bg=c["composer"], fg=c["muted"],
                      relief=tk.FLAT, font=("Segoe UI", 9), padx=6, cursor="hand2").pack(side=tk.LEFT, padx=2)
                      
        tk.Button(toolbar, text="🗑️ Clear", command=self._clear_chat_dialog, bg=c["composer"], fg="#ef4444",
                  relief=tk.FLAT, font=("Segoe UI", 9), padx=6, cursor="hand2").pack(side=tk.RIGHT, padx=2)
        self.leave_group_btn = tk.Button(toolbar, text="❌ Leave Group", command=self._delete_group_dialog, bg=c["composer"], fg="#ef4444",
                  relief=tk.FLAT, font=("Segoe UI", 9), padx=6, cursor="hand2")

        # ── Composer
        composer = tk.Frame(self.chat_panel, bg=c["composer"], padx=16, pady=10)
        composer.pack(fill=tk.X)
        self.input_var = tk.StringVar()
        self.entry = tk.Entry(composer, textvariable=self.input_var, font=("Segoe UI Emoji", 11),
                              relief=tk.FLAT, bg=c["panel"], fg=c["text"], insertbackground=c["text"])
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10), ipady=8)
        self.entry.bind("<Return>", lambda event: self._send_current())
        self.entry.bind("<KeyRelease>", self._maybe_send_typing)
        self.send_button = tk.Button(composer, text="Send ➤", command=self._send_current,
                                     bg=c["send_btn"], fg="white", relief=tk.FLAT,
                                     padx=16, pady=8, font=("Segoe UI", 10, "bold"), cursor="hand2")
        self.send_button.pack(side=tk.RIGHT)

    # ── Events ────────────────────────────────────────────────────────

    def _bind_events(self) -> None:
        self.peer.on_peer_online(self._remember_peer_online)
        self.peer.on_peer_offline(self._remember_peer_offline)
        self.root.bind("<Control-f>", lambda event: self._search_messages())
        self.root.bind("<Control-k>", lambda event: self._jump_to_chat())
        self.root.bind("<Control-o>", lambda event: self._send_file_dialog())
        self.root.bind("<Escape>", lambda event: self._clear_reply())

    def _remember_peer_online(self, data: Dict) -> None:
        self.peer_statuses[data["peer_id"]] = {**data, "online": True}

    def _remember_peer_offline(self, data: Dict) -> None:
        self.peer_statuses[data["peer_id"]] = {**data, "online": False}

    def _launch_async(self, coro, on_success=None, ignore_errors=False) -> Future:
        future = self._run_async(coro)

        def done_callback(done: Future) -> None:
            try:
                result = done.result()
            except Exception as exc:
                if not ignore_errors:
                    error_message = str(exc)
                    self.root.after(0, lambda msg=error_message: messagebox.showerror("LinkLocal", msg, parent=self.root))
                return
            if on_success is not None:
                self.root.after(0, lambda value=result: on_success(value))

        future.add_done_callback(done_callback)
        return future

    def _clear_reply(self) -> None:
        self.reply_to_id = None
        self.reply_var.set("")

    def _play_notification(self, sender_name: str = "", preview: str = "") -> None:
        if self.peer.config.get("do_not_disturb", False):
            return
        # Play Windows notification sound
        if winsound is not None and sys.platform.startswith("win"):
            try:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
        # Show toast popup
        if sender_name:
            self._show_toast(sender_name, preview)

    def _show_toast(self, title: str, body: str) -> None:
        c = self.colors
        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg=c["accent"])
        
        sw = self.root.winfo_screenwidth()
        toast_x = sw - 340
        toast.geometry(f"320x72+{toast_x}+-100")  # Start off-screen
        
        inner = tk.Frame(toast, bg=c["accent"], padx=12, pady=8)
        inner.pack(fill=tk.BOTH, expand=True)
        tk.Label(inner, text=f"💬  {title}", bg=c["accent"], fg="white",
                 font=("Segoe UI", 10, "bold"), anchor="w").pack(fill=tk.X)
        tk.Label(inner, text=truncate(body, 45), bg=c["accent"], fg="white",
                 font=("Segoe UI", 9), anchor="w").pack(fill=tk.X)
                 
        # Animate slide in
        def slide_in(y_pos=-100):
            if y_pos < 20:
                toast.geometry(f"320x72+{toast_x}+{y_pos}")
                self.root.after(10, slide_in, y_pos + (20 - y_pos) // 4 + 2)
            else:
                self.root.after(3000, lambda: slide_out(20))
                
        # Animate slide out
        def slide_out(y_pos=20):
            if y_pos > -100:
                toast.geometry(f"320x72+{toast_x}+{y_pos}")
                self.root.after(10, slide_out, y_pos - (y_pos + 100) // 4 - 2)
            else:
                toast.destroy()
                
        slide_in()

    # ── Sidebar ───────────────────────────────────────────────────────

    def _refresh_sidebar(self) -> None:
        c = self.colors
        for widget in self.peers_frame.winfo_children():
            widget.destroy()
        for widget in self.groups_frame.winfo_children():
            widget.destroy()

        # Merge discovered peers into statuses
        discovered = {info["peer_id"]: info for info in self.peer.discover()}
        for peer_id, info in discovered.items():
            self.peer_statuses[peer_id] = {**info, "peer_id": peer_id, "online": True}

        # Render peer list
        for peer_id, info in sorted(self.peer_statuses.items(), key=lambda item: item[1].get("name", "")):
            row = tk.Frame(self.peers_frame, bg=c["sidebar"], padx=12, pady=4, cursor="hand2")
            row.pack(fill=tk.X)

            is_online = info.get("online", False)
            dot_color = c["online"] if is_online else c["offline"]
            tk.Label(row, text="●", fg=dot_color, bg=c["sidebar"], font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(4, 8))

            name = info.get("name", peer_id)
            unread = self.unread_counts.get(generate_chat_id(self.peer.peer_id, peer_id), 0)
            display = name
            status = info.get("status_message", "")

            name_frame = tk.Frame(row, bg=c["sidebar"])
            name_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
            tk.Label(name_frame, text=display, bg=c["sidebar"], fg=c["sidebar_fg"],
                     font=("Segoe UI", 10), anchor="w").pack(fill=tk.X)
            if status and status != "Available":
                tk.Label(name_frame, text=status, bg=c["sidebar"], fg=c["muted_sidebar"],
                         font=("Segoe UI", 8), anchor="w").pack(fill=tk.X)

            if unread:
                tk.Label(row, text=str(unread), bg=c["accent"], fg="white",
                         font=("Segoe UI", 8, "bold"), padx=6, pady=1).pack(side=tk.RIGHT, padx=4)

            # Bind click on entire row
            for widget in [row, name_frame] + name_frame.winfo_children():
                widget.bind("<Button-1>", lambda e, pid=peer_id, n=name: self._open_conversation("peer", pid, n))

        # Render group list
        self.groups.load_groups()
        for group in sorted(self.groups.list_groups(), key=lambda item: item.group_name.lower()):
            unread = self.unread_counts.get(group.group_id, 0)

            row = tk.Frame(self.groups_frame, bg=c["sidebar"], padx=12, pady=4, cursor="hand2")
            row.pack(fill=tk.X)
            tk.Label(row, text="👥", bg=c["sidebar"], font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(4, 8))

            name_frame = tk.Frame(row, bg=c["sidebar"])
            name_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
            tk.Label(name_frame, text=group.group_name, bg=c["sidebar"], fg=c["sidebar_fg"],
                     font=("Segoe UI", 10), anchor="w").pack(fill=tk.X)
            tk.Label(name_frame, text=f"{len(group.members)} members", bg=c["sidebar"], fg=c["muted_sidebar"],
                     font=("Segoe UI", 8), anchor="w").pack(fill=tk.X)

            if unread:
                tk.Label(row, text=str(unread), bg=c["accent"], fg="white",
                         font=("Segoe UI", 8, "bold"), padx=6, pady=1).pack(side=tk.RIGHT, padx=4)

            for widget in [row, name_frame] + name_frame.winfo_children():
                widget.bind("<Button-1>", lambda e, gid=group.group_id, gname=group.group_name: self._open_conversation("group", gid, gname))

    # ── Conversation ──────────────────────────────────────────────────

    def _open_conversation(self, kind: str, conversation_id: str, title: str) -> None:
        self.current_kind = kind
        self.current_id = conversation_id
        if hasattr(self, 'leave_group_btn'):
            if kind == "group":
                self.leave_group_btn.config(text="❌ Leave Group", command=self._delete_group_dialog)
            else:
                self.leave_group_btn.config(text="❌ Delete Peer", command=self._delete_peer_dialog)
            self.leave_group_btn.pack(side=tk.RIGHT, padx=2)
        self.reply_to_id = None
        self.reply_var.set("")
        self.typing_var.set("")
        self.title_var.set(title)
        self.unread_counts[self._current_chat_id() or conversation_id] = 0
        self._refresh_sidebar()
        self._update_pin_banner()
        self._render_messages()

    def _current_chat_id(self) -> Optional[str]:
        if not self.current_kind or not self.current_id:
            return None
        if self.current_kind == "group":
            return self.current_id
        return generate_chat_id(self.peer.peer_id, self.current_id)

    def _render_messages(self) -> None:
        c = self.colors
        for widget in self.messages_container.winfo_children():
            widget.destroy()
        chat_id = self._current_chat_id()
        if not chat_id:
            return
        messages = storage.load_history(chat_id)
        
        # Send read receipts for unseen messages
        unseen = [m for m in messages if m["sender_id"] != self.peer.peer_id and self.peer.peer_id not in m.get("seen_by", [])]
        if unseen:
            for message in unseen:
                message.setdefault("seen_by", []).append(self.peer.peer_id)
                self._launch_async(self.peer.send_seen(message["message_id"], message["sender_id"], group_id=message.get("group_id")), ignore_errors=True)
            storage.save_history(chat_id, messages)

        lookup = {message["message_id"]: message for message in messages}

        for message in messages:
            outer = tk.Frame(self.messages_container, bg=c["panel"], padx=16, pady=3)
            outer.pack(fill=tk.X)
            is_self = message["sender_id"] == self.peer.peer_id
            anchor = "e" if is_self else "w"
            bg = c["self_bubble"] if is_self else c["other_bubble"]
            bubble = tk.Frame(outer, bg=bg, bd=0, padx=12, pady=8)
            bubble.pack(anchor=anchor, ipadx=4)

            if message.get("reply_to_id") and message["reply_to_id"] in lookup:
                original = lookup[message["reply_to_id"]]
                tk.Label(bubble, text=f"↩ {truncate(_message_body(original), 50)}", bg=bg,
                         fg=c["muted"], justify=tk.LEFT, font=("Segoe UI Emoji", 9, "italic"),
                         wraplength=400).pack(anchor="w", pady=(0, 4))

            header = tk.Frame(bubble, bg=bg)
            header.pack(fill=tk.X)
            sender_label = message["sender_name"]
            if message.get("forwarded_from"):
                sender_label += " ↗ forwarded"
            tk.Label(header, text=sender_label, bg=bg, fg=c["text"],
                     font=("Segoe UI Emoji", 9, "bold")).pack(side=tk.LEFT)
            meta = format_timestamp(message["timestamp"])
            if message.get("is_edited"):
                meta += " · edited"
            if is_self:
                meta += " ✓✓" if message.get("seen_by") else " ✓"
            tk.Label(header, text=meta, bg=bg, fg=c["muted"],
                     font=("Segoe UI Emoji", 8)).pack(side=tk.RIGHT)

            body_text = _message_body(message)
            body_fg = c["muted"] if message.get("is_deleted") else c["text"]
            body_font = ("Segoe UI Emoji", 10, "italic" if message.get("is_deleted") else "normal")
            body = tk.Label(bubble, text=body_text, bg=bg, fg=body_fg, font=body_font,
                            justify=tk.LEFT, wraplength=440)
            body.pack(anchor="w", pady=(4, 0))

            file_info = message.get("file_meta") or message.get("audio_meta")
            if file_info:
                saved_path = file_info.get("saved_path")
                from pathlib import Path
                if saved_path and Path(saved_path).exists():
                    action_frame = tk.Frame(bubble, bg=bg)
                    action_frame.pack(anchor="w", pady=(4, 0))
                    tk.Button(
                        action_frame, 
                        text="⬇️ Save As...", 
                        command=lambda p=saved_path, n=file_info.get("filename", "file"): self._save_file_as(p, n),
                        bg=c["accent"], fg="white", relief=tk.FLAT, font=("Segoe UI", 8, "bold"), padx=6, cursor="hand2"
                    ).pack(side=tk.LEFT)

            if message.get("poll"):
                poll_data = message["poll"]
                votes = message.get("poll_votes", {})
                total_votes = len(votes)
                my_vote = votes.get(self.peer.peer_id)

                poll_card = tk.Frame(bubble, bg=bg, pady=4)
                poll_card.pack(anchor="w", fill=tk.X, pady=(6, 0))

                # Poll question header
                tk.Label(poll_card, text=f"📊  {poll_data['question']}", bg=bg, fg=c["text"],
                         font=("Segoe UI", 10, "bold"), anchor="w", wraplength=380).pack(fill=tk.X, pady=(0, 6))

                for option in poll_data["options"]:
                    count = sum(1 for choice in votes.values() if choice == option)
                    pct = int(count / total_votes * 100) if total_votes > 0 else 0
                    is_mine = (my_vote == option)

                    opt_frame = tk.Frame(poll_card, bg=bg, cursor="hand2")
                    opt_frame.pack(fill=tk.X, pady=4)

                    # Text row
                    text_row = tk.Frame(opt_frame, bg=bg)
                    text_row.pack(fill=tk.X, padx=4)
                    
                    check = "● " if is_mine else "○ "
                    lbl = tk.Label(text_row, text=f"{check}{option}", bg=bg, fg=c["text"],
                                   font=("Segoe UI", 9, "bold" if is_mine else "normal"),
                                   anchor="w")
                    lbl.pack(side=tk.LEFT)
                    
                    pct_label = tk.Label(text_row, text=f"{pct}%", bg=bg, fg=c["muted"],
                                         font=("Segoe UI", 9, "bold"))
                    pct_label.pack(side=tk.RIGHT)

                    # Progress bar row (thin line underneath)
                    bar_bg = tk.Frame(opt_frame, bg="#e2e8f0", height=6)
                    bar_bg.pack(fill=tk.X, padx=4, pady=(2, 0))
                    bar_bg.pack_propagate(False)

                    if pct > 0:
                        bar_fill_color = c["accent"] if is_mine else "#60a5fa"
                        bar_fill = tk.Frame(bar_bg, bg=bar_fill_color)
                        bar_fill.place(x=0, y=0, relwidth=(pct / 100.0), relheight=1.0)

                    # Bind click to vote
                    for w in [opt_frame, text_row, lbl, pct_label, bar_bg]:
                        w.bind("<Button-1>", lambda e, opt=option, msg=message: self._vote_on_poll(msg, opt))

                # Footer: total votes
                tk.Label(poll_card, text=f"{total_votes} vote{'s' if total_votes != 1 else ''}",
                         bg=bg, fg=c["muted"], font=("Segoe UI", 8), anchor="w").pack(fill=tk.X, pady=(4, 0))

            if message.get("reactions"):
                reaction_bar = tk.Frame(bubble, bg=bg)
                reaction_bar.pack(anchor="w", pady=(4, 0))
                for emoji, peer_ids in message["reactions"].items():
                    tk.Label(reaction_bar, text=f"{emoji} {len(peer_ids)}", bg=c["panel"],
                             fg=c["text"], padx=4, pady=1, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 4))

            for widget in [outer, bubble, body]:
                widget.bind("<Button-3>", lambda event, msg=message: self._open_context_menu(event, msg))

        self.canvas.update_idletasks()
        self.canvas.yview_moveto(1.0)

    # ── Context menu ──────────────────────────────────────────────────

    def _open_context_menu(self, event, message: Dict) -> None:
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="React", command=lambda: self._show_emoji_picker(message))
        menu.add_command(label="Reply", command=lambda: self._set_reply_target(message))
        menu.add_command(label="Forward", command=lambda: self._forward_message(message))
        if self.current_kind == "group":
            menu.add_command(label="Pin", command=lambda: self._pin_message(message))
        if message["sender_id"] == self.peer.peer_id:
            menu.add_command(label="Edit", command=lambda: self._edit_message(message))
            menu.add_command(label="Delete", command=lambda: self._delete_message(message))
        menu.tk_popup(event.x_root, event.y_root)

    def _show_emoji_picker(self, message: Dict) -> None:
        picker = tk.Toplevel(self.root)
        picker.title("React")
        picker.configure(bg=self.colors["panel"])
        for emoji in EMOJIS:
            tk.Button(picker, text=emoji, font=("Segoe UI Emoji", 16), relief=tk.FLAT, bg=self.colors["panel"],
                      command=lambda e=emoji: self._react_to_message(message, e, picker)).pack(side=tk.LEFT, padx=6, pady=10)

    def _react_to_message(self, message: Dict, emoji: str, picker: tk.Toplevel) -> None:
        picker.destroy()
        if self.current_kind == "group" and self.current_id:
            self._launch_async(self.groups.send_group_reaction(self.current_id, message["message_id"], emoji))
        elif self.current_kind == "peer" and self.current_id:
            self._launch_async(self.peer.send_reaction(message["message_id"], emoji, self.current_id))

    def _composer_emoji_picker(self) -> None:
        picker = tk.Toplevel(self.root)
        picker.title("Insert Emoji")
        picker.configure(bg=self.colors["panel"])
        for emoji in EMOJIS:
            tk.Button(picker, text=emoji, font=("Segoe UI Emoji", 16), relief=tk.FLAT, bg=self.colors["panel"],
                      command=lambda e=emoji: [self.input_var.set(self.input_var.get() + e), picker.destroy()]).pack(side=tk.LEFT, padx=3, pady=6)


    def _vote_on_poll(self, message: Dict, option: str) -> None:
        if self.current_kind == "group" and self.current_id:
            self._launch_async(self.groups.vote_group_poll(self.current_id, message["message_id"], option), on_success=lambda _: self._render_messages())
        elif self.current_kind == "peer" and self.current_id:
            self._launch_async(self.peer.vote_poll(message["message_id"], option, self.current_id), on_success=lambda _: self._render_messages())

    def _set_reply_target(self, message: Dict) -> None:
        self.reply_to_id = message["message_id"]
        preview = truncate(_message_body(message), 50)
        self.reply_var.set(f"↩ Replying to {message['sender_name']}: {preview}")

    def _edit_message(self, message: Dict) -> None:
        current = message.get("display_content") or message.get("content") or ""
        new_text = simpledialog.askstring("Edit message", "Update your message:", initialvalue=current, parent=self.root)
        if not new_text:
            return
        if self.current_kind == "group" and self.current_id:
            self._launch_async(self.groups.edit_group_message(self.current_id, message["message_id"], new_text))
        elif self.current_kind == "peer" and self.current_id:
            self._launch_async(self.peer.edit_message(message["message_id"], new_text, self.current_id))

    def _delete_message(self, message: Dict) -> None:
        if self.current_kind == "group" and self.current_id:
            self._launch_async(self.groups.delete_group_message(self.current_id, message["message_id"]))
        elif self.current_kind == "peer" and self.current_id:
            self._launch_async(self.peer.delete_message(message["message_id"], self.current_id))

    def _forward_message(self, message: Dict) -> None:
        target = simpledialog.askstring("Forward Message", "Peer ID or Group ID:", parent=self.root)
        if not target:
            return
        if target in {group.group_id for group in self.groups.list_groups()}:
            self._launch_async(self.groups.send_group_text(target, _message_body(message), forwarded_from=message.get("sender_name")))
        else:
            self._launch_async(self.peer.forward_message(message, target))

    def _pin_message(self, message: Dict) -> None:
        if self.current_kind == "group" and self.current_id:
            self._launch_async(self.groups.pin_message(self.current_id, message["message_id"]), on_success=lambda _: self._update_pin_banner())

    # ── Typing / Send ─────────────────────────────────────────────────

    def _maybe_send_typing(self, _event) -> None:
        if not self.current_id:
            return
        if self.current_kind == "group":
            self._launch_async(self.groups.send_group_typing(self.current_id), ignore_errors=True)
        elif self.current_kind == "peer":
            self._launch_async(self.peer.send_typing(self.current_id), ignore_errors=True)

    def _send_current(self) -> None:
        text = self.input_var.get().strip()
        if not text or not self.current_id:
            return
        self.input_var.set("")
        if self.current_kind == "group":
            self._launch_async(self.groups.send_group_text(self.current_id, text, reply_to_id=self.reply_to_id), on_success=lambda _: self._render_messages())
        else:
            if self.reply_to_id:
                self._launch_async(self.peer.reply_to(self.reply_to_id, text, self.current_id), on_success=lambda _: self._render_messages())
            else:
                self._launch_async(self.peer.send(text, self.current_id), on_success=lambda _: self._render_messages())
        self.reply_to_id = None
        self.reply_var.set("")

    # ── Dialogs ───────────────────────────────────────────────────────

    def _create_group_dialog(self) -> None:
        group_name = simpledialog.askstring("Create Group", "Group name:", parent=self.root)
        if not group_name:
            return
        password = simpledialog.askstring("Create Group", "Optional password:", parent=self.root, show="*")
        persist = messagebox.askyesno("Create Group", "Persist chat history for this group?", parent=self.root)
        description = simpledialog.askstring("Create Group", "Description (optional):", parent=self.root) or ""
        rules = simpledialog.askstring("Create Group", "Rules (optional):", parent=self.root) or ""
        group = self.groups.create_group(group_name.strip(), password=password or None, persist=persist, description=description, rules=rules)
        self._refresh_sidebar()
        self._open_conversation("group", group.group_id, group.group_name)
        self._show_copyable_dialog("Group Created", "Share this join code:", group.group_id)

    def _join_group_dialog(self) -> None:
        group_code = simpledialog.askstring("Join Group", "Group code:", parent=self.root)
        if not group_code:
            return
        password = simpledialog.askstring("Join Group", "Password if required:", parent=self.root, show="*")

        def on_joined(group) -> None:
            self._refresh_sidebar()
            self._open_conversation("group", group.group_id, group.group_name)

        self._launch_async(self.groups.join_group(group_code.strip().upper(), password=password or None), on_success=on_joined)

    def _add_manual_peer_dialog(self) -> None:
        name = simpledialog.askstring("Add Peer", "Peer name label:", parent=self.root)
        if not name:
            return
        ip = simpledialog.askstring("Add Peer", "Peer IP address:", parent=self.root)
        if not ip:
            return
        port = simpledialog.askinteger("Add Peer", "Peer TCP port:", initialvalue=55556, parent=self.root)
        if not port:
            return
        peer_id = self.peer.add_manual_peer(name, ip, port)
        self._refresh_sidebar()
        self._open_conversation("peer", peer_id, name)

    def _open_settings_dialog(self) -> None:
        top = tk.Toplevel(self.root)
        top.title("Settings")
        top.geometry("300x250")
        top.resizable(False, False)
        top.configure(bg=self.colors["panel"])
        
        tk.Label(top, text="Status Message", bg=self.colors["panel"], fg=self.colors["text"]).pack(pady=(10, 0))
        status_var = tk.StringVar(value=self.peer.config.get("status_message", "Available"))
        tk.Entry(top, textvariable=status_var, bg=self.colors["composer"], fg=self.colors["text"], insertbackground=self.colors["text"]).pack(fill=tk.X, padx=20, pady=5)
        
        tk.Label(top, text="Avatar / Initials", bg=self.colors["panel"], fg=self.colors["text"]).pack(pady=(5, 0))
        avatar_var = tk.StringVar(value=self.peer.config.get("avatar", "LL"))
        tk.Entry(top, textvariable=avatar_var, bg=self.colors["composer"], fg=self.colors["text"], insertbackground=self.colors["text"]).pack(fill=tk.X, padx=20, pady=5)
        
        dnd_var = tk.BooleanVar(value=self.peer.config.get("do_not_disturb", False))
        tk.Checkbutton(top, text="Do Not Disturb", variable=dnd_var, bg=self.colors["panel"], fg=self.colors["text"], selectcolor=self.colors["panel"], activebackground=self.colors["panel"]).pack(pady=5)
        
        theme_frame = tk.Frame(top, bg=self.colors["panel"])
        theme_frame.pack(fill=tk.X, padx=20, pady=5)
        tk.Label(theme_frame, text="Theme:", bg=self.colors["panel"], fg=self.colors["text"]).pack(side=tk.LEFT)
        theme_var = tk.StringVar(value=self.peer.config.get("theme", "dark"))
        from tkinter import ttk
        theme_cb = ttk.Combobox(theme_frame, textvariable=theme_var, values=["dark", "light"], state="readonly", width=10)
        theme_cb.pack(side=tk.RIGHT)
        
        def save():
            self.peer.update_profile(status_message=status_var.get(), avatar=avatar_var.get(), do_not_disturb=dnd_var.get(), theme=theme_var.get())
            if theme_var.get() != self.theme_name:
                messagebox.showinfo("Theme Updated", "Restart the app to fully apply the new theme.", parent=top)
            top.destroy()
            
        tk.Button(top, text="Save Settings", command=save, bg=self.colors["accent"], fg="white", relief=tk.FLAT).pack(pady=10)

    def _send_file_dialog(self) -> None:
        if not self.current_id:
            return
        path = filedialog.askopenfilename(parent=self.root)
        if not path:
            return
        progress = self._progress_popup("Sending file")

        def on_progress(value: int) -> None:
            progress["var"].set(value)

        def finish(_: object) -> None:
            progress["window"].destroy()

        if self.current_kind == "group":
            self._launch_async(self._send_group_file(path, on_progress), on_success=finish)
        else:
            self._launch_async(self.peer.send_file(path, self.current_id, progress_cb=on_progress), on_success=finish)

    def _send_audio_dialog(self) -> None:
        if not self.current_id:
            return
        path = filedialog.askopenfilename(parent=self.root, filetypes=[("Audio", "*.wav *.mp3 *.m4a *.ogg"), ("All files", "*.*")])
        if not path:
            return
        progress = self._progress_popup("Sending audio")

        def on_progress(value: int) -> None:
            progress["var"].set(value)

        def finish(_: object) -> None:
            progress["window"].destroy()

        if self.current_kind == "group":
            self._launch_async(self._send_group_audio(path, on_progress), on_success=finish)
        else:
            self._launch_async(self.peer.send_audio(path, self.current_id, progress_cb=on_progress), on_success=finish)

    def _save_file_as(self, source_path: str, filename: str) -> None:
        import shutil
        target = filedialog.asksaveasfilename(
            parent=self.root,
            initialfile=filename,
            title="Save File As",
            defaultextension="*.*",
            filetypes=[("All files", "*.*")]
        )
        if target:
            try:
                shutil.copy2(source_path, target)
                messagebox.showinfo("Saved", f"File saved successfully!", parent=self.root)
            except Exception as e:
                messagebox.showerror("Error", f"Could not save file:\n{e}", parent=self.root)

    def _create_poll_dialog(self) -> None:
        if not self.current_id:
            return
        question = simpledialog.askstring("New Poll", "Question:", parent=self.root)
        if not question:
            return
        options_raw = simpledialog.askstring("New Poll", "Options (comma separated):", parent=self.root)
        if not options_raw:
            return
        options = [part.strip() for part in options_raw.split(",") if part.strip()]
        if self.current_kind == "group":
            self._launch_async(self.groups.send_group_poll(self.current_id, question, options), on_success=lambda _: self._render_messages())
        else:
            self._launch_async(self.peer.send_poll(question, options, self.current_id), on_success=lambda _: self._render_messages())

    def _clear_chat_panel(self) -> None:
        self.current_id = None
        self.current_kind = None
        self.title_var.set("Select a conversation")
        self.pin_var.set("")
        self.reply_var.set("")
        self.typing_var.set("")
        for widget in self.messages_container.winfo_children():
            widget.destroy()
        if hasattr(self, 'leave_group_btn'):
            self.leave_group_btn.pack_forget()

    def _delete_group_dialog(self) -> None:
        if self.current_kind != "group" or not self.current_id:
            messagebox.showinfo("Not a Group", "This action is only available for groups.", parent=self.root)
            return
        if messagebox.askyesno("Leave Group", "Are you sure you want to completely delete your membership and history for this group? This cannot be undone.", parent=self.root):
            group_id = self.current_id
            self._launch_async(self.groups.leave_group(group_id), ignore_errors=True)
            self.groups.delete_group(group_id)
            self.unread_counts.pop(group_id, None)
            self._refresh_sidebar()
            self._clear_chat_panel()

    def _delete_peer_dialog(self) -> None:
        if not self.current_id or self.current_kind != "peer":
            return
        if messagebox.askyesno("Delete Peer", "Are you sure you want to completely delete this peer from your network and erase all chat history?", parent=self.root):
            if self.current_id in self.peer.manual_peers:
                self.peer.remove_manual_peer(self.current_id)
            storage.delete_history(self._current_chat_id() or self.current_id)
            if self.current_id in self.peer_statuses:
                del self.peer_statuses[self.current_id]
            self.unread_counts.pop(self._current_chat_id() or self.current_id, None)
            self._refresh_sidebar()
            self._clear_chat_panel()

    def _clear_chat_dialog(self) -> None:
        if not self.current_id:
            return
        if messagebox.askyesno("Clear Chat", "Are you sure you want to delete all local history for this chat?\nThis cannot be undone.", parent=self.root):
            chat_id = self._current_chat_id()
            if chat_id:
                storage.delete_history(chat_id)
                self.unread_counts[chat_id] = 0
                self._render_messages()
                self._refresh_sidebar()

    def _search_messages(self) -> None:
        query = self.search_var.get().strip()
        if not query:
            return
        results = storage.search_messages(query)
        lines = []
        for item in results[:20]:
            message = item["message"]
            lines.append(f"{item['chat_id']} | {message['sender_name']} | {truncate(_message_body(message), 60)}")
        if not lines:
            lines = ["No matches found."]
        messagebox.showinfo("Search Results", "\n".join(lines), parent=self.root)

    def _jump_to_chat(self) -> None:
        options = [peer_id for peer_id in self.peer_statuses.keys()] + [group.group_id for group in self.groups.list_groups()]
        target = simpledialog.askstring("Jump to Chat", "Enter peer ID or group ID:\n" + "\n".join(options[:20]), parent=self.root)
        if not target:
            return
        if target in self.peer_statuses:
            self._open_conversation("peer", target, self.peer_statuses[target].get("name", target))
        else:
            try:
                group = self.groups.get_group(target)
            except Exception:
                messagebox.showerror("LinkLocal", "Unknown peer or group", parent=self.root)
                return
            self._open_conversation("group", group.group_id, group.group_name)

    def _progress_popup(self, title: str) -> Dict[str, object]:
        popup = tk.Toplevel(self.root)
        popup.title(title)
        popup.configure(bg=self.colors["panel"])
        var = tk.IntVar(value=0)
        ttk.Progressbar(popup, maximum=100, variable=var, length=260).pack(padx=16, pady=16)
        return {"window": popup, "var": var}

    def _show_copyable_dialog(self, title: str, label: str, value: str) -> None:
        """Show a dialog with a selectable/copyable text field."""
        c = self.colors
        popup = tk.Toplevel(self.root)
        popup.title(title)
        popup.configure(bg=c["panel"])
        popup.geometry("360x160")
        popup.resizable(False, False)
        tk.Label(popup, text=label, bg=c["panel"], fg=c["text"],
                 font=("Segoe UI", 11)).pack(padx=20, pady=(16, 8))
        entry = tk.Entry(popup, font=("Consolas", 14, "bold"), justify="center",
                         relief=tk.FLAT, bg=c["other_bubble"], fg=c["text"],
                         readonlybackground=c["other_bubble"])
        entry.insert(0, value)
        entry.configure(state="readonly")
        entry.pack(padx=20, fill=tk.X)
        entry.select_range(0, tk.END)
        entry.focus_set()

        def copy_and_close():
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
            popup.destroy()

        tk.Button(popup, text="📋 Copy & Close", command=copy_and_close,
                  bg=c["accent"], fg="white", relief=tk.FLAT,
                  font=("Segoe UI", 10, "bold"), padx=12, pady=6,
                  cursor="hand2").pack(pady=12)

    # ── Group file/audio send ─────────────────────────────────────────

    async def _send_group_file(self, path: str, progress_cb) -> None:
        group = self.groups.get_group(self.current_id)
        timestamp = now_iso()
        message_id = hash_text(path + timestamp)[:24]
        data = Path(path).read_bytes()
        record = self.peer._message_record(
            message_id=message_id,
            sender_id=self.peer.peer_id,
            sender_name=self.peer.display_name,
            content=None,
            display_content=Path(path).name,
            timestamp=timestamp,
            message_type="file",
            group_id=self.current_id,
            chat_id=self.current_id,
        )
        self.peer._populate_record_from_payload(
            record,
            {"filename": Path(path).name, "mime_type": "application/octet-stream", "size": len(data), "blob_b64": base64.b64encode(data).decode("ascii")},
            message_id,
        )
        storage.save_message(self.current_id, record)
        self.peer._emit("message", record)
        progress_cb(40)
        for member in group.members:
            if member["peer_id"] == self.peer.peer_id:
                continue
            try:
                await self.peer.send_file(path, member["peer_id"], group_id=self.current_id, progress_cb=progress_cb)
            except Exception:
                pass
        progress_cb(100)

    async def _send_group_audio(self, path: str, progress_cb) -> None:
        group = self.groups.get_group(self.current_id)
        timestamp = now_iso()
        message_id = hash_text(path + timestamp)[:24]
        data = Path(path).read_bytes()
        record = self.peer._message_record(
            message_id=message_id,
            sender_id=self.peer.peer_id,
            sender_name=self.peer.display_name,
            content=None,
            display_content=Path(path).name,
            timestamp=timestamp,
            message_type="audio",
            group_id=self.current_id,
            chat_id=self.current_id,
        )
        self.peer._populate_record_from_payload(
            record,
            {"filename": Path(path).name, "mime_type": "audio/wav", "size": len(data), "blob_b64": base64.b64encode(data).decode("ascii")},
            message_id,
        )
        storage.save_message(self.current_id, record)
        self.peer._emit("message", record)
        for member in group.members:
            if member["peer_id"] == self.peer.peer_id:
                continue
            try:
                await self.peer.send_audio(path, member["peer_id"], group_id=self.current_id, progress_cb=progress_cb)
            except Exception:
                pass

    # ── Dashboard ─────────────────────────────────────────────────────

    def _open_dashboard(self) -> None:
        if self.dashboard_thread is None or not self.dashboard_thread.is_alive():
            def runner() -> None:
                from .superuser.dashboard import run_dashboard
                run_dashboard()
            self.dashboard_thread = threading.Thread(target=runner, daemon=True)
            self.dashboard_thread.start()
        token = load_config()["superuser_token"]
        webbrowser.open("http://127.0.0.1:5050/")
        self._show_copyable_dialog("Dashboard", "Login token:", token)

    def _update_pin_banner(self) -> None:
        if self.current_kind != "group" or not self.current_id:
            self.pin_var.set("")
            return
        try:
            group = self.groups.get_group(self.current_id)
        except Exception:
            self.pin_var.set("")
            return
        if not group.pinned_message_id:
            self.pin_var.set("")
            return
        pinned = next((msg for msg in storage.load_history(self.current_id) if msg["message_id"] == group.pinned_message_id), None)
        if pinned:
            self.pin_var.set(f"📌 {truncate(_message_body(pinned), 72)}")
        else:
            self.pin_var.set("📌 Pinned message")

    # ── Event polling ─────────────────────────────────────────────────

    def _poll_events(self) -> None:
        needs_sidebar_refresh = False

        while not self.peer.event_queue.empty():
            event = self.peer.event_queue.get()
            name = event["event"]
            data = event["data"]
            if name in {"message", "reaction", "seen"}:
                chat_id = data.get("group_id") or data.get("chat_id")
                if chat_id and chat_id != self._current_chat_id():
                    if name == "message":
                        self.unread_counts[chat_id] = self.unread_counts.get(chat_id, 0) + 1
                    needs_sidebar_refresh = True
                    if name == "message" and data.get("sender_id") != self.peer.peer_id:
                        sender = data.get("sender_name", "Someone")
                        preview = _message_body(data)
                        self._play_notification(sender, preview)
                if chat_id and chat_id == self._current_chat_id():
                    self._render_messages()
                    self._update_pin_banner()
                    if name == "message" and data.get("sender_id") != self.peer.peer_id:
                        self._play_notification()

            if name in {"peer_online", "peer_offline"}:
                needs_sidebar_refresh = True
            if name == "typing":
                expected = self.current_id
                if expected and (data.get("group_id") == expected or data.get("sender_id") == expected):
                    display = self.peer_statuses.get(data["sender_id"], {}).get("name", data["sender_id"])
                    self.typing_var.set(f"{display} is typing...")
                    if self.typing_after_id:
                        self.root.after_cancel(self.typing_after_id)
                    self.typing_after_id = self.root.after(1500, lambda: self.typing_var.set(""))

            if name == "identity_changed":
                old_id = data["old_id"]
                new_id = data["new_id"]
                if self.current_id == old_id:
                    self.current_id = new_id
                    self._render_messages()
                if old_id in self.unread_counts:
                    self.unread_counts[new_id] = self.unread_counts.pop(old_id)
                needs_sidebar_refresh = True


        # Check for new/lost peers every ~3 seconds (30 poll cycles * 100ms)
        self._discovery_counter += 1
        if self._discovery_counter >= 30:
            self._discovery_counter = 0
            current_ids = set(info["peer_id"] for info in self.peer.discover())
            if current_ids != self._last_peer_ids:
                self._last_peer_ids = current_ids
                needs_sidebar_refresh = True

        if needs_sidebar_refresh:
            self._refresh_sidebar()

        self.root.after(100, self._poll_events)

    def _on_close(self) -> None:
        try:
            self._run_async(self.peer.stop()).result(timeout=5)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def _message_body(message: Dict) -> str:
    if message.get("is_deleted"):
        return "This message was deleted"
    return message.get("display_content") or message.get("content") or "[ephemeral message]"


def run_gui(name: Optional[str], profile: str = "default") -> None:
    resolved_name = name
    if not resolved_name:
        bootstrap = tk.Tk()
        bootstrap.withdraw()
        default_name = load_config().get("display_name", "LinkLocal User")
        resolved_name = simpledialog.askstring(
            "LinkLocal",
            "Enter your display name:",
            initialvalue=default_name,
            parent=bootstrap,
        ) or default_name
        bootstrap.destroy()
    app = LinkLocalGUI(resolved_name)
    app.run()
