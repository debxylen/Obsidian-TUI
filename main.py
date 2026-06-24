import os
import re
import sys
import json
import time
import uuid
import json
import httpx
import random
import base64
import hashlib
import asyncio
import keyring

from html.parser import HTMLParser
from curl_cffi.requests import AsyncSession
from datetime import datetime, timedelta, timezone

from textual import on, work
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
        "token": get("TOKEN") or "",
        "cookies": get("COOKIES") or "",
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

def get_hdrs(token: str, cookie: str) -> dict[str, str]:
    h = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"}

    if token:  h["authorization"] = f"Bearer {token}"
    if cookie: h["cookie"]        = cookie.replace("^%", "%").replace("^&", "&").replace("^\"", "\"")

    return h

def get_headers(token=None, ua=None, cookies=None):
    headers = {
        'accept':                      '*/*',
        'accept-language':             'en-PH,en-GB;q=0.9,en-US;q=0.8,en;q=0.7,fil;q=0.6',
        'cache-control':               'no-cache',
        'oai-client-build-number':     '4480993',
        'oai-client-version':          'prod-7c2e8d83df2cf0b6eaa11ba7b37f1605384da182',
        'oai-device-id':               'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx',
        'oai-language':                'en-US',
        'pragma':                      'no-cache',
        'origin':                      'https://chatgpt.com',
        'priority':                    'u=1, i',
        'referer':                     'https://chatgpt.com/',
        'sec-ch-ua':                   '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
        'sec-ch-ua-arch':              '"x86"',
        'sec-ch-ua-bitness':           '"64"',
        'sec-ch-ua-full-version':      '"144.0.7559.133"',
        'sec-ch-ua-full-version-list': '"Not(A:Brand";v="8.0.0.0", "Chromium";v="144.0.7559.133", "Google Chrome";v="144.0.7559.133"',
        'sec-ch-ua-mobile':            '?0',
        'sec-ch-ua-model':             '""',
        'sec-ch-ua-platform':          '"Windows"',
        'sec-ch-ua-platform-version':  '"10.0.0"',
        'sec-fetch-dest':              'empty',
        'sec-fetch-mode':              'cors',
        'sec-fetch-site':              'same-origin',
        'user-agent':                  ua or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
    }
    if token:   headers['authorization'] = f'Bearer {token}'
    headers['cookie'] = cookies if cookies else 'oai-did=xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'
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
        m = re.search(r"c/[^/]*/_", d["src"])
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

async def stream_chat(token, message, conv_id=None, parent_id=None, message_id=None, cookies=None):
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
    
    async with AsyncSession(impersonate="chrome110") as s:
        dpl, scripts = await get_sentinel_data(s, cookies=cookies)
        conf = get_pow_config(ua, dpl, scripts)
        
        p_tok = await get_req_token(conf)
        res = await s.post("https://chatgpt.com/backend-api/sentinel/chat-requirements", headers=get_headers(token, ua, cookies=cookies), json={'p': p_tok})
        if res.status_code != 200: yield f"Error: {res.text}"; return
            
        data, proof = res.json(), None
        pow_d = data.get('proofofwork', {})
        
        if pow_d.get('required'):
            ans, ok = solve_pow(pow_d.get('seed'), pow_d.get('difficulty'), conf)
            if ok: proof = "gAAAAAB" + ans
        
        payload = {
            "action": "next", "parent_message_id": parent_id or str(uuid.uuid4()),
            "model": "auto", "timezone_offset_min": -480, "history_and_training_disabled": False,
            "force_paragen": False, "force_rate_limit": False, "force_use_sse": True,
            "messages": [{"id": message_id or str(uuid.uuid4()), "author": {"role": "user"}, "content": {"content_type": "text", "parts": [message]}}],
            "conversation_mode": {"kind": "primary_assistant"}, "websocket_request_id": str(uuid.uuid4())
        }

        if conv_id: payload["conversation_id"] = conv_id

        h = get_headers(token, ua, cookies=cookies)
        h.update({'accept': 'text/event-stream', 'openai-sentinel-chat-requirements-token': data.get('token'), 'openai-sentinel-proof-token': proof})

        resp = await s.post("https://chatgpt.com/backend-api/conversation", headers=h, json=payload, stream=True)
        async for line in resp.aiter_lines():
            line = line.decode("utf-8")

            if line.startswith("data: "):
                if "[DONE]" in line: break
                yield line + "\n\n"

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

            with Horizontal(id="settings-actions"):
                yield Button("Cancel", id="cancel-btn", classes="settings-btn")
                yield Button("Save", variant="primary", id="save-btn", classes="settings-btn")

    @on(Button.Pressed, "#save-btn")
    def on_save(self) -> None:
        tok  = self.query_one("#token-input", Input).value.strip()
        cook = self.query_one("#cookies-input", Input).value.strip()
        self.dismiss({"token": tok, "cookies": cook})

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel(self) -> None:
        self.dismiss(self.cfg)

# --- components ---------------------------------------------------------------

class MessageInput(TextArea):
    def on_key(self, event) -> None:
        if event.key == "enter":
            event.prevent_default()
            self.app.action_submit_message()
            return

        if event.key in ("shift+enter", "ctrl+enter", "ctrl+j"):
            event.prevent_default()
            self.insert("\n")

class ConvItem(Static):
    class Selected(Message):
        def __init__(self, cid: str) -> None:
            self.cid = cid
            super().__init__()

    def __init__(self, label: str, cid: str, title: str, active: bool = False):
        cls = "conv-item" + (" -active" if active else "")
        super().__init__(label, classes=cls)
        self.cid       = cid
        self.title     = title
        self.tooltip   = title
        self.can_focus = True

    def on_click(self) -> None:
        self.post_message(self.Selected(self.cid))

    def on_key(self, event) -> None:
        if event.key in ("enter", "space"): self.post_message(self.Selected(self.cid))

class ChatMessage(Container):
    def __init__(self, sender: str, content: str, is_ai: bool, **kwargs):
        super().__init__(**kwargs)
        self.sender  = sender
        self.content = content
        self.is_ai   = is_ai

    def compose(self) -> ComposeResult:
        cls = "user-msg" if not self.is_ai else "assistant-msg"
        with Container(classes=f"message-container {cls}"):
            hdr_cls = "user-msg-header" if not self.is_ai else "assistant-msg-header"
            yield Label(f" {self.sender} ", classes=f"message-header {hdr_cls}")
            yield Static(Markdown(self.content) if self.is_ai else self.content, classes=f"message-body {cls}-body")

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
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.cfg           = load_cfg()
        self.convs         = []
        self.active_cid    = None
        self.active_pid    = str(uuid.uuid4())
        self.stream_widget = None

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
                    yield Static("No active conversation", id="chat-header")
                    yield Button("📋", id="copy-url-btn")
                with VerticalScroll(id="chat-scroll"): pass
                with Container(id="input-container"):
                    yield MessageInput(placeholder="Type message here... (Enter to send, Shift+Enter/Ctrl+Enter for newline)", id="message-input")
                    yield Button("Send", id="send-btn")

        yield Footer()

    def on_mount(self) -> None:
        self.title = "Obsidian TUI"
        if not self.cfg.get("token"): return self.action_open_settings()
        self.load_convs()

    # --- funcs ----------------------------------------------------------------

    @work(exclusive=True)
    async def load_convs(self) -> None:
        if not self.cfg.get("token"): return

        url  = "https://chatgpt.com/backend-api/conversations?offset=0&limit=40&order=updated&is_archived=false"
        hdrs = get_hdrs(self.cfg["token"], self.cfg["cookies"])

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
        
        if not self.active_cid:
            hdr.update("New Conversation")
            copy.disabled = True
            return

        title = "ChatGPT Conversation"
        for item in self.convs:
            if item.get("id") == self.active_cid:
                title = item.get("title", title)
                break

        hdr.update(f"Chat: {title}")
        copy.disabled = False

    @on(ConvItem.Selected)
    def on_sel(self, event: ConvItem.Selected) -> None:
        self.load_conv(event.cid)

    @on(Button.Pressed)
    def on_btn(self, event: Button.Pressed) -> None:
        btn, bid = event.button, event.button.id or ""
        
        if hasattr(btn, "cid"):          return self.load_conv(btn.cid)
        if bid == "new-chat-btn":        return self.action_new_chat()
        if bid == "settings-btn":        return self.action_open_settings()
        if bid == "send-btn":            return self.action_submit_message()
        if bid == "copy-url-btn":        return self.action_copy_url()

    def action_copy_url(self) -> None:
        if not self.active_cid: return
        self.copy_to_clipboard(f"https://chatgpt.com/c/{self.active_cid}")
        self.notify("Copied conversation URL to clipboard!", severity="info")

    @work(exclusive=True)
    async def load_conv(self, cid: str) -> None:
        self.active_cid = cid
        self.draw_sidebar()

        url  = f"https://chatgpt.com/backend-api/conversation/{cid}"
        hdrs = get_hdrs(self.cfg["token"], self.cfg["cookies"])

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

                    txt = "".join([p for p in parts if isinstance(p, str)]).strip()
                    if txt: thread.append({"id": msg.get("id"), "role": role, "content": txt})

                thread.reverse()
                self.active_pid = thread[-1]["id"] if thread else str(uuid.uuid4())

                for msg in thread:
                    sender = "You" if msg["role"] == "user" else "ChatGPT"
                    scroll.mount(ChatMessage(sender, msg["content"], msg["role"] == "assistant"))
                
                scroll.scroll_end(animate=False)

        except Exception as e:
            scroll.remove_children()
            scroll.mount(Label(f"Error loading details: {e}"))

    def action_submit_message(self) -> None:
        inp = self.query_one("#message-input", MessageInput)
        txt = inp.text.strip()
        if not txt: return

        inp.text = ""
        scroll   = self.query_one("#chat-scroll", VerticalScroll)

        for node in scroll.query(".loading-msg"): node.remove()

        scroll.mount(ChatMessage("You", txt, is_ai=False))

        self.stream_widget = ChatMessage("ChatGPT", "...", is_ai=True)
        scroll.mount(self.stream_widget)
        scroll.scroll_end()

        self.stream_resp(txt)

    @work(exclusive=True)
    async def stream_resp(self, prompt: str) -> None:
        text, mid, new_cid = "", "", self.active_cid

        try:
            generator = stream_chat(
                token=self.cfg["token"],
                message=prompt,
                conv_id=self.active_cid,
                parent_id=self.active_pid,
                message_id=str(uuid.uuid4()),
                cookies=self.cfg["cookies"]
            )

            async for line in generator:
                line = line.strip()
                if not line or not line.startswith("data:"): continue

                data_str = line[5:].strip()
                if data_str == "[DONE]": break

                try:
                    data = json.loads(data_str)
                    if data.get("conversation_id"): new_cid = data["conversation_id"]

                    op, val = data.get("o"), data.get("v")
                    p_path  = data.get("p") or ""

                    if data.get("p") is not None and op in ("add", "append", "patch"):
                        if op == "add" and val and val.get("message"):
                            mdata = val["message"]
                            if mdata.get("author", {}).get("role") != "assistant": continue

                            mid  = mdata.get("id", "")
                            text = mdata.get("content", {}).get("parts", [""])[0] or ""

                            if val.get("conversation_id"): new_cid = val["conversation_id"]

                        elif op == "append" and "/content/parts/0" in p_path:
                            if mid: text += val

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
            self.load_convs()

        except Exception as e:
            self.stream_widget.upd_content(f"\n*Exception: {e}*")

    def action_open_settings(self) -> None:
        def on_dismiss(new_cfg: dict[str, str]) -> None:
            self.cfg = new_cfg
            save_cfg(new_cfg)
            self.load_convs()

        self.push_screen(SettingsScreen(self.cfg), on_dismiss)

    def action_new_chat(self) -> None:
        self.active_cid = None
        self.active_pid = str(uuid.uuid4())
        
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        scroll.remove_children()
        scroll.mount(Label("Send a message to start a new chat...", classes="loading-msg"))
        self.draw_sidebar()

if __name__ == "__main__":
    app = ObsidianTUI()
    app.run()
