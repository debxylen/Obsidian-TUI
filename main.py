# pyright: reportOptionalMemberAccess=warning, reportAttributeAccessIssue=warning, reportUnnecessaryTypeIgnoreComment=error

import os
import re
import io
import sys
import json
import time
import uuid
import httpx
import random
import base64
import hashlib
import asyncio
import keyring
import tempfile
import mimetypes
import subprocess

import tkinter as tk
from PIL import Image
from tkinter import filedialog

from html.parser import HTMLParser
from curl_cffi.requests import AsyncSession
from datetime import datetime, timedelta, timezone

from textual import on, work
from textual.worker import Worker
from rich.markdown import Markdown
from textual.message import Message
from textual.screen import ModalScreen
from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll, Horizontal
from textual.widgets import Header, Footer, Static, Input, Button, Label, TextArea

if sys.platform == 'win32': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

SERVICE = "ObsidianTUI"

# --- keyring splitting --------------------------------------------------------

def get(key: str) -> str:
    i = 0; out = []

    while True:
        v = keyring.get_password(SERVICE, f"{key}_{i}")
        if v is None: break

        out.append(v)
        i += 1

    return "".join(out)

def set(key: str, value: str):
    i = 0

    while True:
        try: keyring.delete_password(SERVICE, f"{key}_{i}"); i += 1
        except keyring.errors.PasswordDeleteError: break

    for i in range(0, len(value), 1000):
        keyring.set_password(SERVICE, f"{key}_{i//1000}", value[i:i+1000])

# --- credentials --------------------------------------------------------------

def load_cfg() -> dict[str, str]:
    return {
        "token":            get("TOKEN")            or "",
        "cookies":          get("COOKIES")          or "",
        "header_overrides": get("HEADER_OVERRIDES") or "",
    }

def save_cfg(cfg: dict[str, str]):
    for k, v in cfg.items():
        k = k.upper()

        if v: set(k, v)
        else: set(k, "")

def resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

# --- headers ------------------------------------------------------------------

def get_headers(token=None, ua=None, cookies=None, overrides=None):
    headers = {
        'accept':                      '*/*',
        'accept-language':             'en-PH,en-GB;q=0.9,en-US;q=0.8,en;q=0.7,fil;q=0.6',
        'oai-client-build-number':     '4480993',
        'oai-client-version':          'prod-7c2e8d83df2cf0b6eaa11ba7b37f1605384da182',
        'oai-device-id':               'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx',
        'user-agent':                  ua or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
    }
    if token: headers['authorization'] = f'Bearer {token}'
    if overrides: headers.update(overrides)

    return headers

# --- sentinel stuff -----------------------------------------------------------

class ScriptParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts, self.depl_path = [], ""

    def handle_starttag(self, tag, attrs):
        if tag != "script": return

        d = dict(attrs)
        if "src" not in d: return

        self.scripts.append(d["src"])
        m = re.search(r"c/[^/]*/_", d["src"]) # type: ignore
        if m: self.depl_path = m.group(0)

async def get_sentinel_data(session, cookies=None):
    r = await session.get("https://chatgpt.com/", headers=get_headers(cookies=cookies))
    r.raise_for_status()

    p = ScriptParser()
    p.feed(r.text)

    match = re.search(r'data-build="([^"]*)"', r.text)

    if p.depl_path: depl_path = p.depl_path
    elif match:     depl_path = match.group(1)
    else:           depl_path = "prod-f501fe933b3edf57aea882da888e1a544df99840"

    scripts = p.scripts or ["https://chatgpt.com/backend-api/sentinel/sdk.js"]
    return depl_path, scripts

# --- proof of work ------------------------------------------------------------

def get_pow_config(ua, dpl, scripts):
    now = datetime.now(timezone(timedelta(hours=-5))).strftime("%a %b %d %Y %H:%M:%S") + " GMT-0500 (Eastern Standard Time)"
    return [
        random.choice([3000, 4000]), now, 4294705152, 0, ua,
        random.choice(scripts), dpl, "en-US", "en-US,en", 0,
        "webdriver−false", "location", "window", time.perf_counter() * 1000,
        str(uuid.uuid4()), "", random.choice([8, 16, 32]), 
        time.time() * 1000 - (time.perf_counter() * 1000)
    ]

def solve_pow(seed, diff, config):
    d_len, s_enc, t_diff = len(diff), seed.encode(), bytes.fromhex(diff)
    
    p1 = (json.dumps(config[:3], separators=(',', ':'))[:-1] + ',').encode()
    p2 = (',' + json.dumps(config[4:9], separators=(',', ':'))[1:-1] + ',').encode()
    p3 = (',' + json.dumps(config[10:], separators=(',', ':'))[1:]).encode()

    for i in range(500000):
        final = p1 + str(i).encode() + p2 + str(i >> 1).encode() + p3
        enc = base64.b64encode(final)
        if hashlib.sha3_512(s_enc + enc).digest()[:d_len] <= t_diff: return enc.decode(), True
    return "", False

async def get_req_token(config):
    ans, _ = solve_pow(str(random.random()), "0fffff", config)
    return 'gAAAAAC' + ans

# --- stream chat --------------------------------------------------------------

async def stream_chat(token, message, conv_id=None, parent_id=None, message_id=None, cookies=None, attachments=None, temp_chat=False, conduit_token=None, header_overrides=None):
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"

    async with AsyncSession(impersonate="chrome110") as s:
        dpl, scripts = await get_sentinel_data(s, cookies=cookies)
        conf = get_pow_config(ua, dpl, scripts)
        
        p_tok = await get_req_token(conf)
        res = await s.post("https://chatgpt.com/backend-api/sentinel/chat-requirements", headers=get_headers(token, ua, cookies=cookies, overrides=header_overrides), json={'p': p_tok})
        if res.status_code != 200: yield f"Error: {res.text}"; return
            
        data, proof = res.json(), None
        pow_d = data.get('proofofwork', {})
        
        if pow_d.get('required'):
            ans, ok = solve_pow(pow_d.get('seed'), pow_d.get('difficulty'), conf)
            if ok: proof = "gAAAAAB" + ans

        msg_parts = [message]
        metadata  = {}
        c_type    = "text"

        if attachments:
            c_type = "multimodal_text"
            metadata["attachments"] = attachments

            for att in attachments:
                if att.get("mime_type", "").startswith("image/"):
                    msg_parts.append({
                        "content_type":  "image_asset_pointer",
                        "asset_pointer": f"file-service://{att['id']}",
                        "size_bytes":    att.get("size", 0),
                        "width":         att.get("width", 800),
                        "height":        att.get("height", 600)
                    })

        msg_meta = {"serialization_metadata": {"custom_symbol_offsets": []}}
        if metadata: msg_meta.update(metadata)

        msg_obj = {
            "id":          message_id or str(uuid.uuid4()),
            "author":      {"role": "user"},
            "create_time": time.time(),
            "content":     {"content_type": c_type, "parts": msg_parts},
            "metadata":    msg_meta,
        }

        if temp_chat:
            payload = {
                "action":                              "next",
                "messages":                            [msg_obj],
                "parent_message_id":                   parent_id or "client-created-root",
                "model":                               "auto",
                "client_prepare_state":                "success",
                "timezone_offset_min":                 -480,
                "timezone":                            "Asia/Shanghai",
                "history_and_training_disabled":       True,
                "conversation_mode":                   {"kind": "primary_assistant"},
                "enable_message_followups":            True,
                "system_hints":                        [],
                "supports_buffering":                  True,
                "supported_encodings":                 ["v1"],
                "paragen_cot_summary_display_override": "allow",
                "force_parallel_switch":               "auto",
            }
        else:
            payload = {
                "action":                        "next",
                "parent_message_id":             parent_id or str(uuid.uuid4()),
                "model":                         "auto",
                "timezone_offset_min":           -480,
                "history_and_training_disabled": False,
                "force_paragen":                 False,
                "force_rate_limit":              False,
                "force_use_sse":                 True,
                "messages":                      [msg_obj],
                "conversation_mode":             {"kind": "primary_assistant"},
                "websocket_request_id":          str(uuid.uuid4()),
            }

        if conv_id: payload["conversation_id"] = conv_id

        h = get_headers(token, ua, cookies=cookies, overrides=header_overrides)
        h.update({'accept': 'text/event-stream', 'openai-sentinel-chat-requirements-token': data.get('token'), 'openai-sentinel-proof-token': proof})

        if conduit_token: h['x-conduit-token'] = conduit_token
        else:
            prep_payload = payload.copy()
            prep_payload.pop("messages", None)
            prep_payload.pop("websocket_request_id", None)

            prep_h = dict(h)
            prep_h['accept'] = '*/*'

            prep_resp = await s.post("https://chatgpt.com/backend-api/f/conversation/prepare", headers=prep_h, json=prep_payload)
            if prep_resp.status_code == 200:
                new_token = prep_resp.json().get("conduit_token")
                if new_token:
                    h['x-conduit-token'] = new_token
                    yield f"data: {{\"new_conduit\": \"{new_token}\"}}\n\n"

        endpoint = "https://chatgpt.com/backend-api/f/conversation" if temp_chat else "https://chatgpt.com/backend-api/conversation"
        resp = await s.post(endpoint, headers=h, json=payload, stream=True)

        if resp.status_code != 200:
            try: await resp.read()
            except Exception: pass
            yield f"data: {{\"message\": {{\"author\": {{\"role\": \"assistant\"}}, \"content\": {{\"content_type\": \"text\", \"parts\": [\"HTTP ERROR {resp.status_code}: {resp.text}\"]}}}}}}\n\n"
            return

        async for line in resp.aiter_lines():
            line = line.decode("utf-8")

            if line.startswith("data: "):
                if "[DONE]" in line: break

                if "conversation_id" in line and temp_chat and not conv_id:
                    try:
                        d = json.loads(line[6:])
                        if d.get("conversation_id") == None: raise Exception

                        conv_id = d["conversation_id"]
                        payload["conversation_id"] = conv_id

                    except: pass

                yield line + "\n\n"

        if temp_chat and conv_id and h.get('x-conduit-token'):
            try:
                prep_payload = payload.copy()
                prep_payload.pop("messages", None)
                prep_payload.pop("partial_query", None)
                prep_payload.pop("websocket_request_id", None)

                prep_h = dict(h)
                prep_h['accept'] = '*/*'

                ka_resp = await s.post("https://chatgpt.com/backend-api/f/conversation/prepare", headers=prep_h, json=prep_payload)
                if ka_resp.status_code == 200:
                    ka_token = ka_resp.json().get("conduit_token")
                    if ka_token: yield f"data: {{\"new_conduit\": \"{ka_token}\"}}\n\n"

            except: pass

# --- settings modal -----------------------------------------------------------

class SettingsScreen(ModalScreen[dict[str, str]]):
    def __init__(self, cfg: dict[str, str], **kwargs):
        super().__init__(**kwargs)
        self.cfg = cfg

    def compose(self) -> ComposeResult:
        with Container(id="settings-panel"):
            yield Label("Obsidian TUI Settings", classes="settings-title")

            yield Label("ChatGPT Access Token:", classes="settings-label")
            yield Input(self.cfg.get("token", ""), id="token-input", placeholder="ey...", classes="settings-input")

            yield Label("Browser Cookies (optional):", classes="settings-label")
            yield Input(self.cfg.get("cookies", ""), id="cookies-input", placeholder="oai-did=...", classes="settings-input")

            yield Label("Header Overrides (JSON, optional):", classes="settings-label")
            yield TextArea(self.cfg.get("header_overrides", ""), id="header-overrides-input", classes="settings-input settings-textarea")

            with Horizontal(id="settings-actions"):
                yield Button("Cancel", id="cancel-btn", classes="settings-btn")
                yield Button("Save", variant="primary", id="save-btn", classes="settings-btn")

    @on(Button.Pressed, "#save-btn")
    def on_save(self) -> None:
        tok       = self.query_one("#token-input", Input).value.strip()
        cook      = self.query_one("#cookies-input", Input).value.strip()
        overrides = self.query_one("#header-overrides-input", TextArea).text.strip()

        if overrides:
            try: json.loads(overrides)
            except json.JSONDecodeError as e:
                self.notify(f"Invalid JSON in Header Overrides: {e}", severity="error"); return

        self.dismiss({"token": tok, "cookies": cook, "header_overrides": overrides})

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel(self) -> None:
        self.dismiss(self.cfg)

# --- components ---------------------------------------------------------------

class MessageInput(TextArea):
    BINDINGS = [
        ("ctrl+u", "app.upload_file", "Upload File"),
    ]

    def on_key(self, event) -> None:
        if event.key == "enter":
            event.prevent_default()
            self.app.action_submit_message()
            return

        if event.key in ("shift+enter", "ctrl+enter", "ctrl+j"):
            event.prevent_default()
            self.insert("\n")
            return

class StagedAttachmentLabel(Static):
    def __init__(self, filename: str, att_id: str):
        super().__init__(filename, classes="staged-att")
        self.att_id = att_id

    def on_click(self) -> None:
        self.app.remove_pending_attachment(self.att_id)

class ChatOptionsScreen(ModalScreen):
    def __init__(self, cid: str, title: str):
        super().__init__()
        self.cid   = cid
        self.title = title

    def compose(self) -> ComposeResult:
        with Container(id="options-panel"):
            yield Label(f"Options: {self.title}", id="options-title")
            yield Button("Delete Conversation", id="delete-chat-btn", variant="error")
            yield Button("Cancel", id="cancel-options-btn")

    @on(Button.Pressed, "#cancel-options-btn")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#delete-chat-btn")
    def on_delete(self) -> None:
        self.dismiss(self.cid)

class ConvItem(Static):
    class Selected(Message):
        def __init__(self, cid: str) -> None:
            self.cid = cid
            super().__init__()

    class RightClicked(Message):
        def __init__(self, cid: str, title: str) -> None:
            self.cid   = cid
            self.title = title
            super().__init__()

    def __init__(self, label: str, cid: str, title: str, active: bool = False):
        cls = "conv-item" + (" -active" if active else "")
        super().__init__(label, classes=cls)
        self.cid       = cid
        self.title     = title
        self.tooltip   = title
        self.can_focus = True

    def on_click(self, event) -> None:
        if event.button == 3: self.post_message(self.RightClicked(self.cid, self.title))
        else: self.post_message(self.Selected(self.cid))

    def on_key(self, event) -> None:
        if event.key in ("enter", "space"): self.post_message(self.Selected(self.cid))

class ChatMessage(Container):
    def __init__(self, sender: str, content: str, is_ai: bool, attachments=None, **kwargs):
        super().__init__(**kwargs)
        self.sender      = sender
        self.content     = content
        self.is_ai       = is_ai
        self.attachments = attachments or []

    def compose(self) -> ComposeResult:
        cls = "user-msg" if not self.is_ai else "assistant-msg"
        with Container(classes=f"message-container {cls}"):
            hdr_cls = "user-msg-header" if not self.is_ai else "assistant-msg-header"
            yield Label(f" {self.sender} ", classes=f"message-header {hdr_cls}")
            yield Static(Markdown(self.content) if self.is_ai else self.content, classes=f"message-body {cls}-body")

            if self.attachments:
                with Horizontal(classes="attachments-container"):
                    for att in self.attachments:
                        btn = Button(f"📎 {att['name']}", classes="attachment-btn", id=f"att_{att['id'].replace('-', '_').replace(':', '_').replace('.', '_')}")
                        btn.attachment_info = att
                        yield btn

    def upd_content(self, txt: str) -> None:
        self.content = txt
        body = self.query_one(".message-body")
        body.update(Markdown(txt) if self.is_ai else txt)

# --- main tui -----------------------------------------------------------------

class ObsidianTUI(App):
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH  = resource_path("style.tcss")

    BINDINGS = [
        ("ctrl+s", "open_settings", "Settings"),
        ("ctrl+n", "new_chat", "New Chat"),
        ("ctrl+u", "upload_file", "Upload File"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.cfg                 = load_cfg()
        self.convs               = []
        self.active_cid          = None
        self.active_pid          = str(uuid.uuid4())
        self.stream_widget       = None
        self.pending_attachments = []
        self.temporary           = False

    # --- layout ---------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()

        with Container(id="app-grid"):

            with Container(id="sidebar"):
                yield Static("OBSIDIAN CLIENT", id="sidebar-header")
                yield Button("New Chat (Ctrl+N)", id="new-chat-btn", classes="sidebar-btn")
                yield Button("Settings (Ctrl+S)", id="settings-btn", classes="sidebar-btn")
                yield Label("Conversations", classes="category-header")
                with VerticalScroll(id="conversations-scroll"): pass

            with Container(id="chat-area"):
                with Horizontal(id="chat-header-container"):
                    yield Static("New Conversation", id="chat-header")
                    yield Button("∅", id="temp-btn")
                    yield Button("🔗︎", id="copy-url-btn", classes="-hidden")
                with VerticalScroll(id="chat-scroll"): pass
                with Container(id="input-container"):
                    yield Horizontal(id="staged-attachments", classes="-hidden")
                    with Horizontal(id="input-row"):
                        yield Button("+", id="upload-btn")
                        yield MessageInput(placeholder="Type message here... (Enter to send, Shift+Enter/Ctrl+Enter for newline)", id="message-input")
                        yield Button("Send", id="send-btn")

        yield Footer()

    def on_mount(self) -> None:
        self.title = "Obsidian TUI"
        self.draw_sidebar()
        if not self.cfg.get("token"): return self.action_open_settings()
        self.load_convs()

    # --- funcs ----------------------------------------------------------------

    def get_overrides(self) -> dict | None:
        raw = self.cfg.get("header_overrides", "").strip()
        if not raw: return None

        try:    return json.loads(raw)
        except: return None

    @work(exclusive=True)
    async def load_convs(self) -> None:
        if not self.cfg.get("token"): return

        url  = "https://chatgpt.com/backend-api/conversations?offset=0&limit=40&order=updated&is_archived=false"
        hdrs = get_headers(self.cfg["token"], None, self.cfg["cookies"], overrides=self.get_overrides())

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(url, headers=hdrs)

                if res.status_code == 200:
                    self.convs = res.json().get("items", [])
                    self.call_after_refresh(self.draw_sidebar)

                elif res.status_code == 401:
                    self.notify("Unauthorized token. Please check Settings (Ctrl+S)", severity="error")

        except Exception as e:
            self.notify(f"Exception: {e}", severity="error")

    def draw_sidebar(self) -> None:
        scroll = self.query_one("#conversations-scroll", VerticalScroll)
        scroll.remove_children()

        today   = datetime.now(timezone.utc).date()
        yest    = today - timedelta(days=1)
        prev7   = today - timedelta(days=7)
        grouped = {"Today": [], "Yesterday": [], "Previous 7 Days": [], "Older": []}

        for item in self.convs:
            try:
                dt_str = item.get("update_time", "")
                if not dt_str: grouped["Older"].append(item); continue

                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).date()

                if dt == today:          grouped["Today"].append(item)
                elif dt == yest:         grouped["Yesterday"].append(item)
                elif dt >= prev7:        grouped["Previous 7 Days"].append(item)
                else:                    grouped["Older"].append(item)

            except Exception:
                grouped["Older"].append(item)

        for cat, items in grouped.items():
            if not items: continue
            scroll.mount(Label(cat, classes="category-header"))

            for item in items:
                title  = item.get("title") or "Unnamed Chat"
                cid    = item.get("id")
                active = (cid == self.active_cid)
                lbl    = title if len(title) <= 16 else title[:15] + "\u2026"
                scroll.mount(ConvItem(lbl, cid, title, active))

        hdr  = self.query_one("#chat-header", Static)
        copy = self.query_one("#copy-url-btn", Button)
        temp = self.query_one("#temp-btn", Button)

        is_new = (self.active_cid is None)

        if is_new:
            hdr.update("New Conversation")
            copy.add_class("-hidden")
            temp.remove_class("-hidden")

            if self.temporary: temp.add_class("-toggled")
            else: temp.remove_class("-toggled")
            return

        if self.temporary:
            hdr.update("Chat: Temporary Conversation")

            copy.add_class("-hidden")
            temp.remove_class("-hidden")
            temp.add_class("-toggled")

        else:
            title = "ChatGPT Conversation"
            for item in self.convs:
                if item.get("id") != self.active_cid: continue
                title = item.get("title", title); break

            hdr.update(f"Chat: {title}")
            copy.remove_class("-hidden")
            temp.add_class("-hidden")
            copy.disabled = False

    @on(ConvItem.Selected)
    def on_sel(self, event: ConvItem.Selected) -> None:
        self.temporary = False
        self.load_conv(event.cid)

    @on(Button.Pressed, "#temp-btn")
    def on_temp_btn(self) -> None:
        if self.active_cid is None:
            self.temporary = not self.temporary
            self.draw_sidebar()

    @on(ConvItem.RightClicked)
    def on_conv_right_click(self, event: ConvItem.RightClicked) -> None:
        def handle_result(cid: str | None) -> None:
            if cid: self.delete_conversation(cid)
        self.push_screen(ChatOptionsScreen(event.cid, event.title), handle_result)

    @work
    async def delete_conversation(self, cid: str) -> None:
        url  = f"https://chatgpt.com/backend-api/conversation/{cid}"
        hdrs = get_headers(self.cfg["token"], None, self.cfg["cookies"], overrides=self.get_overrides())

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.patch(url, headers=hdrs, json={"is_visible": False})

                if res.status_code == 200 and res.json().get("success") is True:
                    self.notify("Conversation deleted.", severity="information")

                    if self.active_cid == cid:
                        self.active_cid = None
                        self.active_pid = str(uuid.uuid4())
                        self.query_one("#chat-scroll", VerticalScroll).remove_children()
                        self.query_one("#chat-header", Static).update("No active conversation")
                    self.load_convs()

                else:
                    self.notify(f"Failed to delete conversation (HTTP {res.status_code})", severity="error")

        except Exception as e:
            self.notify(f"Error deleting conversation: {e}", severity="error")

    @on(Button.Pressed)
    def on_btn(self, event: Button.Pressed) -> None | Worker[None]:
        btn, bid = event.button, event.button.id or ""
        
        if hasattr(btn, "cid"):          return self.load_conv(btn.cid)
        if bid == "new-chat-btn":        return self.action_new_chat()
        if bid == "settings-btn":        return self.action_open_settings()
        if bid == "send-btn":            return self.action_submit_message()
        if bid == "copy-url-btn":        return self.action_copy_url()
        if bid.startswith("att_"):       return self.action_open_attachment(btn)

    def action_copy_url(self) -> None:
        if not self.active_cid: return
        self.copy_to_clipboard(f"https://chatgpt.com/c/{self.active_cid}")
        self.notify("Copied conversation URL to clipboard!", severity="information")

    @work
    async def action_open_attachment(self, btn: Button) -> None:
        att = getattr(btn, "attachment_info", None)
        if not att: return

        self.notify(f"Downloading {att['name']}...", severity="information")

        base_url = "https://chatgpt.com/backend-api"
        cookie   = self.cfg["cookies"].replace("^%", "%").replace("^&", "&").replace("^\"", "\"")
        hdrs     = get_headers(self.cfg["token"], cookies=cookie, overrides=self.get_overrides())

        file_id  = att.get("id")
        conv_id  = self.active_cid

        filename = att.get("name")
        dl_url   = None
        last_err = ""

        try:
            async with AsyncSession(impersonate="chrome110") as client:

                if att.get("type") == "sandbox":
                    url    = f"{base_url}/conversation/{conv_id}/interpreter/download"
                    params = {"message_id": att.get("message_id"), "sandbox_path": att.get("sandbox_path")}
                    res    = await client.get(url, headers=hdrs, params=params)

                    if res.status_code == 200: dl_url = res.json().get("download_url")
                    else: last_err = f"Interpreter HTTP {res.status_code}: {res.text[:120]}"

                else:
                    url = f"{base_url}/conversation/{conv_id}/attachment/{file_id}/download"
                    res = await client.get(url, headers=hdrs)

                    if res.status_code == 200: dl_url = res.json().get("download_url")
                    else:
                        last_err = f"Attachment HTTP {res.status_code}: {res.text[:120]}"
                        url = f"{base_url}/files/{file_id}/download"
                        res = await client.get(url, headers=hdrs)

                        if res.status_code == 200: dl_url = res.json().get("download_url")
                        else: last_err += f" | Files HTTP {res.status_code}: {res.text[:120]}"

                if not dl_url: self.notify(f"No download URL for {filename}. {last_err}", severity="error"); return

                res = await client.get(dl_url, headers=hdrs)
                if res.status_code != 200: self.notify(f"Download failed for {filename} (HTTP {res.status_code})", severity="error"); return

                with tempfile.NamedTemporaryFile(delete=False, prefix=f"{os.path.splitext(filename)[0]}_", suffix=os.path.splitext(filename)[1]) as f:
                    f.write(res.content)
                    filepath = f.name

                self.notify(f"Opening {filename}...", severity="information")

                if sys.platform == 'win32':    os.startfile(filepath)
                elif sys.platform == 'darwin': subprocess.run(["open", filepath], check=False)
                else: subprocess.run(["xdg-open", filepath], check=False)

        except Exception as e:
            self.notify(f"Error opening attachment: {e}", severity="error")

    @work
    async def action_upload_file(self) -> None:
        loop = asyncio.get_event_loop()
        filepath = await loop.run_in_executor(None, self.filepicker)
        if filepath: self.upload_attachment(filepath)

    @on(Button.Pressed, "#upload-btn")
    def on_upload_btn(self) -> None:
        self.action_upload_file()

    def filepicker(self) -> str:
        root = tk.Tk()
        
        icon_path = resource_path("favicon.ico")
        if os.path.exists(icon_path):
            try: root.iconbitmap(icon_path)
            except Exception: pass
        
        root.overrideredirect(True)
        root.attributes("-alpha", 0.0)

        root.update_idletasks()
        root.deiconify()
        root.lift()
        root.attributes("-topmost", True)

        path = filedialog.askopenfilename(parent=root, initialdir=os.getcwd(), title="Select file to upload")
        root.destroy()
        return path or ""

    @work
    async def upload_attachment(self, filepath: str) -> None:
        if not os.path.exists(filepath):
            self.notify(f"File not found: {filepath}", severity="error"); return

        filename = os.path.basename(filepath)
        size     = os.path.getsize(filepath)
        self.notify(f"Uploading {filename} ({size} bytes)...", severity="information")

        mime_type, _ = mimetypes.guess_type(filepath)
        mime_type    = mime_type or "application/octet-stream"
        use_case     = "multimodal" if mime_type.startswith("image/") else "my_files"

        try:
            with open(filepath, "rb") as f: content = f.read()
        except Exception as e:
            self.notify(f"Failed to read file: {e}", severity="error")
            return

        base_url = "https://chatgpt.com/backend-api"
        cookie   = self.cfg["cookies"].replace("^%", "%").replace("^&", "&").replace("^\"", "\"")
        hdrs     = get_headers(self.cfg["token"], cookies=cookie, overrides=self.get_overrides())

        try:
            async with AsyncSession(impersonate="chrome110") as client:
                payload = {
                    "file_name":           filename,
                    "file_size":           size,
                    "use_case":            use_case,
                    "reset_rate_limits":   False,
                    "timezone_offset_min": -480
                }

                res = await client.post(f"{base_url}/files", headers=hdrs, json=payload)
                if res.status_code != 200: self.notify(f"Failed to register file (HTTP {res.status_code}): {res.text[:100]}", severity="error"); return

                resp_json  = res.json()
                file_id    = resp_json.get("file_id")
                upload_url = resp_json.get("upload_url")
                
                if not file_id or not upload_url:
                    self.notify("Failed to retrieve upload parameters", severity="error"); return

                put_hdrs = {
                    "content-type":   mime_type,
                    "x-ms-blob-type": "BlockBlob",
                    "x-ms-version":   "2020-04-08",
                }

                res = await client.put(upload_url, headers=put_hdrs, data=content)
                if res.status_code not in (200, 201): self.notify(f"Content upload failed (HTTP {res.status_code}): {res.text[:100]}", severity="error"); return

                res = await client.post(f"{base_url}/files/{file_id}/uploaded", headers=hdrs, json={})
                if res.status_code != 200: self.notify(f"Failed to complete upload (HTTP {res.status_code}): {res.text[:100]}", severity="error"); return

                if use_case != "multimodal":
                    success = False

                    for _ in range(30):
                        res = await client.get(f"{base_url}/files/{file_id}", headers=hdrs)
                        if res.status_code == 200:
                            status = res.json().get("retrieval_index_status")

                            if status == "success":   success = True; break
                            elif status == "failed":  break

                        await asyncio.sleep(1)

                    if not success:
                        self.notify(f"File index verification timed out or failed", severity="warning")

                width, height = 800, 600
                if mime_type.startswith("image/"):
                    img, bio = None, None

                    try:
                        bio = io.BytesIO(content)
                        img = Image.open(bio)
                        img.load()
                        width, height = img.size
                    finally:
                        if img: img.close()
                        if bio: bio.close()

                self.pending_attachments.append({
                    "id":        file_id,
                    "name":      filename,
                    "size":      size,
                    "mime_type": mime_type,
                    "width":     width,
                    "height":    height
                })

                self.call_after_refresh(self.update_staged_ui)
                self.notify(f"Successfully staged {filename}!", severity="information")

        except Exception as e:
            self.notify(f"Upload error: {e}", severity="error")

    def remove_pending_attachment(self, att_id: str) -> None:
        self.pending_attachments = [a for a in self.pending_attachments if a["id"] != att_id]
        self.update_staged_ui()

    def update_staged_ui(self) -> None:
        container = self.query_one("#staged-attachments", Horizontal)
        container.query("*").remove()

        if not self.pending_attachments: container.add_class("-hidden"); return
        else: container.remove_class("-hidden")

        container.mount(Static("Staged: "))

        for i, att in enumerate(self.pending_attachments):
            if i > 0: container.mount(Static(", "))
            container.mount(StagedAttachmentLabel(att["name"], att["id"]))

    @work(exclusive=True)
    async def load_conv(self, cid: str) -> None:
        self.active_cid = cid
        self.draw_sidebar()

        url  = f"https://chatgpt.com/backend-api/conversation/{cid}"
        hdrs = get_headers(self.cfg["token"], None, self.cfg["cookies"], overrides=self.get_overrides())

        scroll = self.query_one("#chat-scroll", VerticalScroll)
        scroll.remove_children()
        scroll.mount(Label("Loading conversation messages...", classes="loading-msg"))

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(url, headers=hdrs)
                scroll.remove_children()

                if res.status_code != 200:
                    scroll.mount(Label(f"Error loading chat details: HTTP {res.status_code}"))
                    return

                data, thread = res.json(), []
                mapping, curr = data.get("mapping", {}), data.get("current_node", "")

                while curr and curr in mapping:
                    node = mapping[curr]
                    msg  = node.get("message")
                    curr = node.get("parent")
                    if not msg: continue

                    role   = msg.get("author", {}).get("role", "")
                    parts  = msg.get("content", {}).get("parts", [])
                    hidden = msg.get("metadata", {}).get("is_visually_hidden_from_conversation", False)

                    if role not in ("user", "assistant") or not parts or hidden: continue

                    atts, metadata = [], msg.get("metadata", {})
                    for att in metadata.get("attachments", []):
                        atts.append({
                            "id":        att.get("id"),
                            "name":      att.get("name") or "unnamed_file",
                            "mime_type": att.get("mime_type") or "application/octet-stream",
                            "type":      "file"
                        })

                    for p in parts:
                        if isinstance(p, dict):
                            c_type    = p.get("content_type")
                            asset_ptr = p.get("asset_pointer") or ""
                            if not (c_type == "image_asset_pointer" or asset_ptr.startswith("file-service://") or asset_ptr.startswith("sediment://")): continue

                            f_id = asset_ptr.replace("file-service://", "").replace("sediment://", "")
                            if not (f_id and not any(a["id"] == f_id for a in atts)): continue

                            atts.append({
                                "id":        f_id,
                                "name":      p.get("name") or f"image_{f_id[:8]}.png",
                                "mime_type": p.get("mime_type") or "image/png",
                                "type":      "file"
                            })

                        elif isinstance(p, str):
                            matches = re.findall(r'\(sandbox:([^\)]+)\)', p)

                            for path in matches:
                                name = os.path.basename(path)
                                if any(a.get("sandbox_path") == path for a in atts): continue

                                atts.append({
                                    "id":           f"sandbox_{msg.get('id')}_{name}",
                                    "name":         name,
                                    "mime_type":    "application/octet-stream",
                                    "type":         "sandbox",
                                    "sandbox_path": path,
                                    "message_id":   msg.get("id")
                                })

                    txt = "".join([p for p in parts if isinstance(p, str)]).strip()
                    if txt or atts:
                        thread.append({
                            "id":          msg.get("id"),
                            "role":        role,
                            "content":     txt,
                            "attachments": atts
                        })

                thread.reverse()
                self.active_pid = thread[-1]["id"] if thread else str(uuid.uuid4())

                for msg in thread:
                    sender = "You" if msg["role"] == "user" else "ChatGPT"
                    scroll.mount(ChatMessage(sender, msg["content"], msg["role"] == "assistant", attachments=msg.get("attachments")))
                
                scroll.scroll_end(animate=False)

        except Exception as e:
            scroll.remove_children()
            scroll.mount(Label(f"Error loading details: {e}"))

    def action_submit_message(self) -> None:
        if getattr(self, "is_streaming", False): return

        inp = self.query_one("#message-input", MessageInput)
        txt = inp.text.strip()
        if not txt and not getattr(self, "pending_attachments"): return

        inp.text = ""
        scroll   = self.query_one("#chat-scroll", VerticalScroll)

        for node in scroll.query(".loading-msg"): node.remove()

        atts = getattr(self, "pending_attachments", [])
        self.pending_attachments = []
        self.update_staged_ui()

        scroll.mount(ChatMessage("You", txt, is_ai=False, attachments=atts))

        self.stream_widget = ChatMessage("ChatGPT", "...", is_ai=True)
        scroll.mount(self.stream_widget)
        scroll.scroll_end()

        self.stream_resp(txt, attachments=atts)

    @work(exclusive=True)
    async def stream_resp(self, prompt: str, attachments=None) -> None:
        self.is_streaming = True

        text, mid, new_cid = "", "", self.active_cid
        last_p, last_o = "", ""

        try:
            generator = stream_chat(
                token=self.cfg["token"],
                message=prompt,
                conv_id=self.active_cid,
                parent_id=self.active_pid,
                message_id=str(uuid.uuid4()),
                cookies=self.cfg["cookies"],
                attachments=attachments,
                temp_chat=self.temporary,
                conduit_token=getattr(self, "conduit_token", None),
                header_overrides=self.get_overrides(),
            )

            async for line in generator: # type: ignore
                line = line.strip()
                if not line or not line.startswith("data:"): continue

                data_str = line[5:].strip()
                if data_str == "[DONE]": break

                try:
                    data = json.loads(data_str)
                    if data.get("conversation_id"): new_cid = data["conversation_id"]
                    if data.get("new_conduit"): self.conduit_token = data["new_conduit"]

                    op     = data.get("o", last_o)
                    val    = data.get("v")
                    p_path = data.get("p", last_p) or ""

                    if "o" in data: last_o = op
                    if "p" in data: last_p = p_path

                    if val is not None and op in ("add", "append", "patch"):
                        if op == "add" and isinstance(val, dict) and val.get("message"):
                            mdata = val["message"]
                            if mdata.get("author", {}).get("role") != "assistant": continue

                            mid  = mdata.get("id", "")
                            text = mdata.get("content", {}).get("parts", [""])[0] or ""

                            if val.get("conversation_id"): new_cid = val["conversation_id"]

                        elif op == "append" and "/content/parts/0" in p_path:
                            if isinstance(val, str) and mid: text += val

                        elif op == "patch" or (op == "append" and "/content" not in p_path):
                            if isinstance(val, str) and mid: text += val

                    elif data.get("message", {}).get("author", {}).get("role") == "assistant":
                        mdata = data["message"]
                        mid   = mdata.get("id", "")
                        text  = (mdata.get("content", {}).get("parts") or [""])[0] or ""

                    if text:
                        self.stream_widget.upd_content(text)
                        self.query_one("#chat-scroll", VerticalScroll).scroll_end()

                except Exception: pass

            if mid:     self.active_pid = mid
            if new_cid: self.active_cid = new_cid
            if not self.temporary: self.load_convs()
            else: self.draw_sidebar()

        except Exception as e:
            self.stream_widget.upd_content(f"\n*Exception: {e}*")

        finally:
            self.is_streaming = False

    def action_open_settings(self) -> None:
        def on_dismiss(new_cfg: dict[str, str] | None) -> None:
            if new_cfg == None: return
            self.cfg = new_cfg
            save_cfg(new_cfg)
            self.load_convs()

        self.push_screen(SettingsScreen(self.cfg), on_dismiss)

    def action_new_chat(self) -> None:
        self.active_cid = None
        self.active_pid = str(uuid.uuid4())
        self.temporary = False
        self.conduit_token = None
        
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        scroll.remove_children()
        scroll.mount(Label("Send a message to start a new chat...", classes="loading-msg"))
        self.draw_sidebar()

if __name__ == "__main__":
    sys.stderr.write(f"\033]0;{ "Obsidian" }\007")
    sys.stderr.flush()

    app = ObsidianTUI()
    app.run()
