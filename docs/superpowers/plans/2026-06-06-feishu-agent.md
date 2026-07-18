# Feishu Remote Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python daemon that lets the user control their home PC via Feishu messages, powered by Anthropic API with tool calling.

**Architecture:** Polling-based Feishu message receiver → Anthropic API with tool loop (list_directory, read_file, write_file, search_files, run_command) → Feishu message sender. Single `agent.py` process with 5 supporting modules.

**Tech Stack:** Python 3.10+, anthropic SDK, requests, Windows 11

---

## File Map

```
~/.claude/feishu-agent/
├── agent.py       # Main loop: poll → process → send
├── poller.py      # Feishu REST API polling (get messages)
├── sender.py      # Feishu REST API (send messages)
├── tools.py       # Anthropic tool definitions + local execution
├── store.py       # Conversation context (JSON file per chat)
├── config.py      # Load/validate config.json
├── config.json    # Secrets (app_id, app_secret, api_key, model)
├── state.json     # Auto-managed: last seen message_id per conversation
└── logs/          # Auto-created: tool execution logs
```

---

### Task 1: Project Scaffold & Config

**Files:**
- Create: `~/.claude/feishu-agent/config.py`
- Create: `~/.claude/feishu-agent/config.json`

- [ ] **Step 1: Create project directory**

```bash
mkdir -p ~/.claude/feishu-agent/logs
```

- [ ] **Step 2: Write config.json with Feishu credentials**

File: `~/.claude/feishu-agent/config.json`
```json
{
  "feishu": {
    "app_id": "cli_aaa9135baa385bdf",
    "app_secret": "REDACTED",
    "bot_open_id": "ou_1904d3f8aeffac94aa7007c8e1e2f6e0"
  },
  "anthropic": {
    "api_key": "PLACEHOLDER_GET_FROM_CONSOLE",
    "model": "claude-sonnet-4-6"
  },
  "agent": {
    "poll_interval_seconds": 5,
    "max_context_messages": 30,
    "max_tool_rounds": 15,
    "command_timeout_seconds": 300
  }
}
```

- [ ] **Step 3: Write config.py loader**

File: `~/.claude/feishu-agent/config.py`
```python
"""Load and validate configuration from config.json."""
import json
import os

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


def load_config():
    """Load config.json, return dict. Exit with message if missing or invalid."""
    if not os.path.exists(CONFIG_PATH):
        print(f"[ERROR] config.json not found at {CONFIG_PATH}")
        print("Copy config.example.json to config.json and fill in your keys.")
        exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Validate required keys
    required = [
        ("feishu", "app_id"),
        ("feishu", "app_secret"),
        ("anthropic", "api_key"),
    ]
    for section, key in required:
        if cfg.get(section, {}).get(key, "").startswith("PLACEHOLDER"):
            print(f"[ERROR] config.json: {section}.{key} is still a placeholder.")
            print("Fill in your real credentials.")
            exit(1)

    return cfg
```

- [ ] **Step 4: Verify config loads**

```bash
cd ~/.claude/feishu-agent
python -c "from config import load_config; print(load_config()['feishu']['app_id'])"
```
Expected: prints `cli_aaa9135baa385bdf`

- [ ] **Step 5: Commit**

```bash
git add ~/.claude/feishu-agent/config.py ~/.claude/feishu-agent/config.json
git commit -m "feat: project scaffold + config module"
```

---

### Task 2: Conversation Context Store

**Files:**
- Create: `~/.claude/feishu-agent/store.py`

- [ ] **Step 1: Write store.py**

```python
"""Conversation context store — one JSON file per Feishu chat."""
import json
import os
import time

STORE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contexts")


def _ensure_dir():
    os.makedirs(STORE_DIR, exist_ok=True)


def _path(chat_id):
    safe = chat_id.replace("/", "_").replace("\\", "_")
    return os.path.join(STORE_DIR, f"{safe}.json")


def load(chat_id, max_messages=30):
    """Return list of messages for a chat, newest last. [] if no history."""
    _ensure_dir()
    p = _path(chat_id)
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("messages", [])[-max_messages:]
    except Exception:
        return []


def save(chat_id, messages):
    """Persist message list for a chat (full replace)."""
    _ensure_dir()
    with open(_path(chat_id), "w", encoding="utf-8") as f:
        json.dump({
            "chat_id": chat_id,
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "messages": messages,
        }, f, ensure_ascii=False, indent=2)


def append(chat_id, role, content):
    """Append one message (role=user|assistant, content=blocks list) to history."""
    msgs = load(chat_id)
    msgs.append({"role": role, "content": content})
    save(chat_id, msgs)
    return msgs
```

- [ ] **Step 2: Verify store works**

```bash
cd ~/.claude/feishu-agent
python -c "
from store import save, load, append
save('test_chat', [])
msgs = append('test_chat', 'user', 'hello')
assert len(msgs) == 1
assert msgs[0]['role'] == 'user'
print('[OK] store works')
"
```
Expected: `[OK] store works`

- [ ] **Step 3: Commit**

```bash
git add ~/.claude/feishu-agent/store.py
git commit -m "feat: conversation context store"
```

---

### Task 3: Tool Definitions & Execution

**Files:**
- Create: `~/.claude/feishu-agent/tools.py`

- [ ] **Step 1: Write tools.py — tool schemas for Anthropic API**

```python
"""Tool definitions (Anthropic schema) + local execution."""
import glob
import os
import subprocess
import time
from pathlib import Path

HOME = os.path.expanduser("~")
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# ── Anthropic tool definitions (sent to API) ──────────────────────

TOOL_SCHEMAS = [
    {
        "name": "list_directory",
        "description": "List the contents of a directory. Returns files and subdirectories with names, sizes, and modification times.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the directory to list."
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file. Supports text files and common formats. Returns the file contents as text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file to read."
                },
                "limit_lines": {
                    "type": "integer",
                    "description": "Optional: only return the first N lines (default 500)."
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file with the given content. Creates parent directories if needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path where the file should be written."
                },
                "content": {
                    "type": "string",
                    "description": "The full text content to write to the file."
                }
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "search_files",
        "description": "Search for files matching a glob pattern. Returns matching file paths.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern, e.g. '**/*.pdf' or '*.tmp'. Searches recursively from the given directory."
                },
                "directory": {
                    "type": "string",
                    "description": "Absolute path to start searching from."
                }
            },
            "required": ["pattern", "directory"]
        }
    },
    {
        "name": "run_command",
        "description": "Execute a shell command on the Windows computer. Use for file operations (move, copy, delete), running Python scripts, installing packages, or any terminal task. Commands run in the user's home directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute. Uses cmd.exe /C on Windows. Example: 'dir C:\\Users\\Harry\\Downloads' or 'python script.py'."
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional: directory to run the command in. Defaults to home directory."
                }
            },
            "required": ["command"]
        }
    },
]

# ── Local execution ───────────────────────────────────────────────

def execute(tool_name, tool_input):
    """Execute a tool locally. Return string result."""
    _log(f"tool={tool_name} input={tool_input}")

    if tool_name == "list_directory":
        return _list_directory(tool_input["path"])
    elif tool_name == "read_file":
        return _read_file(tool_input["path"], tool_input.get("limit_lines", 500))
    elif tool_name == "write_file":
        return _write_file(tool_input["path"], tool_input["content"])
    elif tool_name == "search_files":
        return _search_files(tool_input["pattern"], tool_input["directory"])
    elif tool_name == "run_command":
        return _run_command(tool_input["command"], tool_input.get("working_dir", HOME))
    else:
        return f"Unknown tool: {tool_name}"


def _list_directory(path):
    p = Path(path)
    if not p.exists():
        return f"Error: path '{path}' does not exist."
    if not p.is_dir():
        return f"Error: '{path}' is not a directory."
    items = []
    try:
        for entry in sorted(p.iterdir()):
            try:
                stat = entry.stat()
                size = _fmt_size(stat.st_size)
                mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))
                tag = "[DIR] " if entry.is_dir() else "[FILE]"
                items.append(f"{tag} {entry.name}  ({size})  {mtime}")
            except OSError:
                items.append(f"??? {entry.name}")
    except PermissionError:
        return f"Error: permission denied for '{path}'."
    if not items:
        return f"Directory '{path}' is empty."
    return f"Contents of '{path}' ({len(items)} items):\n" + "\n".join(items)


def _read_file(path, limit_lines):
    p = Path(path)
    if not p.exists():
        return f"Error: file '{path}' does not exist."
    if p.is_dir():
        return f"Error: '{path}' is a directory, not a file."
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= limit_lines:
                    lines.append(f"... (truncated, showing first {limit_lines} lines)")
                    break
                lines.append(line.rstrip("\n"))
            return "\n".join(lines) if lines else "(file is empty)"
    except Exception as e:
        return f"Error reading '{path}': {e}"


def _write_file(path, content):
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return f"File written: {path} ({len(content)} chars)"
    except Exception as e:
        return f"Error writing '{path}': {e}"


def _search_files(pattern, directory):
    try:
        matches = []
        for match in Path(directory).rglob(pattern):
            if match.is_file():
                matches.append(str(match))
        if not matches:
            return f"No files matching '{pattern}' found in '{directory}'."
        return f"Found {len(matches)} files matching '{pattern}':\n" + "\n".join(matches[:100])
    except Exception as e:
        return f"Error searching: {e}"


def _run_command(command, working_dir):
    if not os.path.isdir(working_dir):
        working_dir = HOME
    try:
        result = subprocess.run(
            ["cmd.exe", "/C", command],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=300,
            shell=False,
        )
        out = result.stdout.strip() or "(no output)"
        err = result.stderr.strip()
        if err:
            out += f"\n[stderr]: {err}"
        if result.returncode != 0:
            out += f"\n[exit code]: {result.returncode}"
        return out
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after 300s."
    except Exception as e:
        return f"Error executing command: {e}"


def _fmt_size(bytes_val):
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_val < 1024:
            return f"{bytes_val:.1f}{unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f}TB"


def _log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    log_file = os.path.join(LOG_DIR, f"tools-{time.strftime('%Y-%m-%d')}.log")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
```

- [ ] **Step 2: Verify tools work locally**

```bash
cd ~/.claude/feishu-agent
python -c "
from tools import execute
# Test list_directory
r = execute('list_directory', {'path': 'C:/Users/Harry/Downloads'})
print(r[:200])
# Test search_files
r2 = execute('search_files', {'pattern': '*.py', 'directory': 'C:/Users/Harry/Downloads'})
print(r2[:200])
print('[OK]')
"
```

- [ ] **Step 3: Commit**

```bash
git add ~/.claude/feishu-agent/tools.py
git commit -m "feat: tool definitions and local execution"
```

---

### Task 4: Feishu Message Sender

**Files:**
- Create: `~/.claude/feishu-agent/sender.py`

- [ ] **Step 1: Write sender.py**

```python
"""Send messages to Feishu users via the IM API."""
import json
import time
import urllib.request
from config import load_config


class FeishuSender:
    def __init__(self):
        cfg = load_config()
        self.app_id = cfg["feishu"]["app_id"]
        self.app_secret = cfg["feishu"]["app_secret"]
        self.base = "https://open.feishu.cn/open-apis"
        self._token = None
        self._token_expiry = 0

    def _get_token(self):
        if self._token and time.time() < self._token_expiry:
            return self._token
        data = json.dumps({
            "app_id": self.app_id,
            "app_secret": self.app_secret,
        }).encode()
        req = urllib.request.Request(
            f"{self.base}/auth/v3/tenant_access_token/internal",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        self._token = resp["tenant_access_token"]
        self._token_expiry = time.time() + resp.get("expire", 7200) - 300
        return self._token

    def _api(self, method, path, body=None):
        token = self._get_token()
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json; charset=utf-8")
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            return json.loads(resp.read())
        except Exception as e:
            print(f"[sender] API error: {e}")
            return None

    def send_text(self, receive_id, content):
        """Send a text message to a user or chat.
        receive_id: open_id of user or chat_id of group.
        """
        body = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": content}, ensure_ascii=False),
        }
        return self._api("POST", "/im/v1/messages?receive_id_type=open_id", body)

    def send_text_to_chat(self, chat_id, content):
        """Send a text message to a group chat."""
        body = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": content}, ensure_ascii=False),
        }
        return self._api("POST", "/im/v1/messages?receive_id_type=chat_id", body)


# Quick test
if __name__ == "__main__":
    s = FeishuSender()
    result = s.send_text("ou_1904d3f8aeffac94aa7007c8e1e2f6e0", "👋 Feishu Agent is online!")
    print(result)
```

- [ ] **Step 2: Test sender sends a message**

```bash
cd ~/.claude/feishu-agent
python sender.py
```
Expected: JSON response with `code: 0`. Check your phone — the bot should have sent "👋 Feishu Agent is online!"

- [ ] **Step 3: Commit**

```bash
git add ~/.claude/feishu-agent/sender.py
git commit -m "feat: feishu message sender"
```

---

### Task 5: Feishu Message Poller

**Files:**
- Create: `~/.claude/feishu-agent/poller.py`

- [ ] **Step 1: Write poller.py**

```python
"""Poll Feishu API for new messages to the bot."""
import json
import os
import time
import urllib.request
from config import load_config

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")


class FeishuPoller:
    def __init__(self):
        cfg = load_config()
        self.app_id = cfg["feishu"]["app_id"]
        self.app_secret = cfg["feishu"]["app_secret"]
        self.base = "https://open.feishu.cn/open-apis"
        self._token = None
        self._token_expiry = 0
        self._seen = self._load_state()

    # ── Token ──────────────────────────────────────────────────

    def _get_token(self):
        if self._token and time.time() < self._token_expiry:
            return self._token
        data = json.dumps({
            "app_id": self.app_id,
            "app_secret": self.app_secret,
        }).encode()
        req = urllib.request.Request(
            f"{self.base}/auth/v3/tenant_access_token/internal",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        self._token = resp["tenant_access_token"]
        self._token_expiry = time.time() + resp.get("expire", 7200) - 300
        return self._token

    def _api(self, method, path, params=None):
        token = self._get_token()
        url = f"{self.base}{path}"
        if params:
            qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
            url += "?" + qs
        req = urllib.request.Request(url, method=method)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json; charset=utf-8")
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            return json.loads(resp.read())
        except Exception as e:
            print(f"[poller] API error: {e}")
            return None

    # ── State ──────────────────────────────────────────────────

    def _load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_state(self):
        with open(STATE_FILE, "w") as f:
            json.dump(self._seen, f, indent=2)

    # ── Poll ────────────────────────────────────────────────────

    def poll(self):
        """Return list of (chat_id, chat_type, user_name, text) for new messages."""
        results = []

        # 1. List recent conversations
        convs = self._api("GET", "/im/v1/conversations", {"page_size": 20})
        if not convs or convs.get("code") != 0:
            return results

        for conv in convs.get("data", {}).get("items", []):
            chat_id = conv.get("chat_id", "")
            chat_type = conv.get("chat_type", "private")  # private or group

            # 2. Get messages for this conversation
            msgs = self._api("GET", "/im/v1/messages", {
                "container_id_type": "chat",
                "container_id": chat_id,
                "page_size": 5,
                "sort_type": "ByCreateTimeDesc",
            })
            if not msgs or msgs.get("code") != 0:
                continue

            for msg in msgs.get("data", {}).get("items", []):
                msg_id = msg.get("message_id", "")
                if msg_id in self._seen:
                    continue

                self._seen[msg_id] = time.strftime("%Y-%m-%d %H:%M:%S")

                # 3. Extract text
                msg_type = msg.get("msg_type", "")
                if msg_type != "text":
                    continue

                content_str = msg.get("body", {}).get("content", "{}")
                try:
                    content = json.loads(content_str) if isinstance(content_str, str) else content_str
                    text = content.get("text", "").strip()
                except Exception:
                    text = ""

                if text:
                    # Get sender info
                    sender_id = msg.get("sender", {}).get("id", "unknown")
                    sender_type = msg.get("sender", {}).get("id_type", "open_id")
                    user_name = self._get_user_name(sender_id) if sender_type == "open_id" else sender_id

                    results.append({
                        "chat_id": chat_id,
                        "chat_type": chat_type,
                        "sender_id": sender_id,
                        "user_name": user_name,
                        "text": text,
                        "msg_id": msg_id,
                    })

        # Prune old seen IDs (keep max 1000)
        if len(self._seen) > 1000:
            sorted_ids = sorted(self._seen.items(), key=lambda x: x[1], reverse=True)
            self._seen = dict(sorted_ids[:1000])

        self._save_state()
        return results

    def _get_user_name(self, open_id):
        """Try to get user name, fall back to truncated open_id."""
        try:
            resp = self._api("GET", f"/contact/v3/users/{open_id}")
            if resp and resp.get("code") == 0:
                user = resp.get("data", {}).get("user", {})
                return user.get("name", open_id[:8])
        except Exception:
            pass
        return open_id[:8]


# Quick test
if __name__ == "__main__":
    p = FeishuPoller()
    print(f"[poller] Starting poll... seen {len(p._seen)} messages")
    msgs = p.poll()
    for m in msgs:
        print(f"[poller] NEW: [{m['user_name']}] {m['text'][:80]}")
    if not msgs:
        print("[poller] No new messages.")
```

- [ ] **Step 2: Test poller detects messages**

```bash
cd ~/.claude/feishu-agent
python poller.py
```
Expected: prints `[poller] No new messages.` (since none pending). Then send a message to the bot in Feishu and run again — should print the message.

- [ ] **Step 3: Commit**

```bash
git add ~/.claude/feishu-agent/poller.py
git commit -m "feat: feishu message poller"
```

---

### Task 6: Agent Core — Main Loop

**Files:**
- Create: `~/.claude/feishu-agent/agent.py`

- [ ] **Step 1: Write agent.py**

```python
#!/usr/bin/env python3
"""Feishu Remote Agent — process messages via Anthropic API with tools."""
import json
import os
import sys
import time
import traceback

# Fix Windows UTF-8 console output
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from config import load_config
from poller import FeishuPoller
from sender import FeishuSender
from tools import TOOL_SCHEMAS, execute
from store import load as load_history, append as append_history

# Anthropic SDK
try:
    from anthropic import Anthropic, APIStatusError
except ImportError:
    print("[ERROR] anthropic SDK not installed. Run: pip install anthropic")
    exit(1)

HOME = os.path.expanduser("~")
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))

SYSTEM_PROMPT = f"""You are a helpful AI assistant running on Harry's Windows 11 computer.
You receive tasks from Feishu messages and execute them using the tools provided.

Key information:
- The user's name is Harry (王宇非)
- Home directory: {HOME}
- Operating system: Windows 11
- You have full access to files and commands under {HOME}
- You can create and edit documents (docx, xlsx, pptx, pdf) using Python scripts

Guidelines:
- Execute tasks directly without asking for unnecessary confirmations
- For dangerous operations (deleting many files, modifying system settings), ask for confirmation
- When generating documents, write Python scripts using python-docx, openpyxl, python-pptx, or reportlab
- Keep responses concise but informative
- If a command fails, try an alternative approach or explain what went wrong
- Respond in Chinese if the user messages in Chinese"""


class Agent:
    def __init__(self):
        cfg = load_config()
        self.poller = FeishuPoller()
        self.sender = FeishuSender()
        self.client = Anthropic(api_key=cfg["anthropic"]["api_key"])
        self.model = cfg["anthropic"].get("model", "claude-sonnet-4-6")
        self.max_tool_rounds = cfg["agent"].get("max_tool_rounds", 15)
        self.poll_interval = cfg["agent"].get("poll_interval_seconds", 5)

    def run(self):
        print(f"[{time.strftime('%H:%M:%S')}] Agent started. Polling every {self.poll_interval}s.")
        print(f"    Model: {self.model}")
        print(f"    PID: {os.getpid()}")

        while True:
            try:
                new_messages = self.poller.poll()
                for msg_data in new_messages:
                    print(f"\n[{time.strftime('%H:%M:%S')}] [{msg_data['user_name']}] {msg_data['text'][:100]}")

                    # Mark "typing" — process the task
                    start = time.time()
                    reply = self.process(msg_data["chat_id"], msg_data["text"])
                    elapsed = time.time() - start
                    print(f"[{time.strftime('%H:%M:%S')}] Done in {elapsed:.1f}s")

                    # Send reply to Feishu
                    self._send_reply(msg_data, reply)

            except KeyboardInterrupt:
                print("\n[STOP] Agent stopped.")
                break
            except Exception as e:
                print(f"[ERROR] Main loop: {e}")
                traceback.print_exc()

            time.sleep(self.poll_interval)

    def process(self, chat_id, user_text):
        """Run the Anthropic API tool loop. Return final text reply."""
        # Load conversation history
        history = load_history(chat_id)

        # Build messages for API
        messages = []

        # Include recent history (last N messages from store)
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        # Add new user message
        messages.append({"role": "user", "content": user_text})

        # Tool loop
        for round_num in range(self.max_tool_rounds):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                )
            except APIStatusError as e:
                print(f"[API ERROR] {e.status_code}: {e.message}")
                return f"❌ AI 服务出错: {e.status_code} — 请稍后重试"
            except Exception as e:
                print(f"[API ERROR] {e}")
                return f"❌ 连接 AI 服务失败: {e}"

            # Check stop reason
            if response.stop_reason == "end_turn":
                # Text response — done
                reply_text = ""
                for block in response.content:
                    if block.type == "text":
                        reply_text += block.text

                # Save to history
                append_history(chat_id, "user", user_text)
                append_history(chat_id, "assistant", reply_text)

                return reply_text

            elif response.stop_reason == "tool_use":
                # AI wants to use tools
                # First, add assistant message with tool_use blocks
                assistant_blocks = []
                tool_results = []

                for block in response.content:
                    if block.type == "text":
                        assistant_blocks.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        tool_name = block.name
                        tool_input = block.input
                        tool_id = block.id

                        print(f"  [{round_num+1}] 🔧 {tool_name}({json.dumps(tool_input, ensure_ascii=False)[:80]})")

                        # Execute the tool
                        result_text = execute(tool_name, tool_input)
                        print(f"  [{round_num+1}]    → {result_text[:100]}")

                        assistant_blocks.append({
                            "type": "tool_use",
                            "id": tool_id,
                            "name": tool_name,
                            "input": tool_input,
                        })

                        tool_results.append({
                            "tool_use_id": tool_id,
                            "content": result_text[:4000],  # Truncate very long results
                        })

                # Add assistant message (with tool_use blocks)
                messages.append({"role": "assistant", "content": assistant_blocks})

                # Add tool results as user message
                messages.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": r["tool_use_id"], "content": r["content"]}
                    for r in tool_results
                ]})

                # Continue loop — AI will process tool results
                continue

            else:
                # stop_reason is something unexpected
                print(f"  [!] Unexpected stop_reason: {response.stop_reason}")
                return "⚠️ AI 返回了意外状态，请重试。"

        # Exceeded max tool rounds
        return "⚠️ 任务步骤太多，超时了。请拆分成更小的任务。"

    def _send_reply(self, msg_data, reply):
        """Send reply back to the correct chat."""
        chat_id = msg_data["chat_id"]
        chat_type = msg_data.get("chat_type", "private")

        # Truncate very long replies
        if len(reply) > 4000:
            reply = reply[:4000] + "\n\n... (内容过长已截断)"

        if chat_type == "group":
            result = self.sender.send_text_to_chat(chat_id, reply)
        else:
            result = self.sender.send_text(msg_data["sender_id"], reply)

        if result and result.get("code") == 0:
            print(f"  [SENT] OK")
        else:
            print(f"  [SENT] FAILED: {result}")


def main():
    Agent().run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify agent.py syntax and imports**

```bash
cd ~/.claude/feishu-agent
python -c "from agent import Agent; print('[OK] agent imports successful')"
```
Expected: `[OK] agent imports successful`

- [ ] **Step 3: Commit**

```bash
git add ~/.claude/feishu-agent/agent.py
git commit -m "feat: agent core — main loop with tool calling"
```

---

### Task 7: Install Dependencies

- [ ] **Step 1: Install Python packages**

```bash
pip install anthropic requests python-docx openpyxl python-pptx reportlab
```

- [ ] **Step 2: Verify installs**

```bash
python -c "
import anthropic; print('anthropic:', anthropic.__version__)
import requests; print('requests:', requests.__version__)
import docx; print('python-docx: OK')
import openpyxl; print('openpyxl: OK')
import pptx; print('python-pptx: OK')
import reportlab; print('reportlab: OK')
print('[OK] all deps installed')
"
```

---

### Task 8: End-to-End Test

- [ ] **Step 1: Fill in real API key**

Edit `~/.claude/feishu-agent/config.json` — replace `PLACEHOLDER_GET_FROM_CONSOLE` with your actual Anthropic API key (`sk-ant-...`).

- [ ] **Step 2: Start agent in test mode**

```bash
cd ~/.claude/feishu-agent
python agent.py
```

Expected: prints `Agent started. Polling every 5s.`

- [ ] **Step 3: Send a test message from Feishu**

Open Feishu on your phone → find the bot → send: `"hello 你是谁"`

Expected:
- Agent prints the message it received
- Agent calls Anthropic API
- Agent sends reply to Feishu
- You see the bot's response on your phone

- [ ] **Step 4: Test a file operation**

Send: `"看看我桌面有什么东西"`

Expected:
- Agent calls `list_directory` tool
- Agent replies with a list of files on your desktop

- [ ] **Step 5: Test a command**

Send: `"帮我写一个Hello World的Python脚本放在桌面上"`

Expected:
- Agent calls `write_file` tool
- File appears on desktop
- Agent confirms

- [ ] **Step 6: Commit**

```bash
git add ~/.claude/feishu-agent/ && git commit -m "test: e2e verification complete"
```

---

### Task 9: Auto-Start Setup

- [ ] **Step 1: Create startup script**

File: `~/.claude/feishu-agent/start-agent.bat`
```bat
@echo off
cd /d %USERPROFILE%\.claude\feishu-agent
start /B pythonw agent.py > agent.log 2>&1
```

- [ ] **Step 2: Add to Windows Startup**

Press `Win+R` → type `shell:startup` → enter. Copy `start-agent.bat` shortcut to the Startup folder.

Or via command:
```bash
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([Environment]::GetFolderPath('Startup') + '\feishu-agent.lnk'); $s.TargetPath = '%USERPROFILE%\.claude\feishu-agent\start-agent.bat'; $s.WindowStyle = 7; $s.Save()"
```

- [ ] **Step 3: Verify auto-start works**

Reboot and confirm the agent is running:
```bash
tasklist /FI "IMAGENAME eq pythonw.exe"
```

---

### Task 10: Final Verification

- [ ] **Step 1: Run full workflow from phone**

Send from Feishu: `"帮我整理下载文件夹，按文件类型分到不同子文件夹"`

- [ ] **Step 2: Confirm complete**

Check: files are actually sorted, bot replied with the summary.

- [ ] **Step 3: Commit final state**

```bash
git add -A && git commit -m "feat: feishu remote agent — complete"
```
