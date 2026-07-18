# Feishu Remote Agent — Design Spec

**Date:** 2026-06-06
**Status:** Draft
**Summary:** Control home PC via Feishu messages. Phone sends task → Anthropic API executes with tools → Feishu replies result.

---

## 1. Architecture

```
📱 Feishu App                    🖥️ Home PC (Windows 11)
    │                                  │
    ├─ User sends message ──────────→  feishu.poll (pulls via Feishu REST API)
    │                                  │
    │                                  ├─→ Anthropic API (Claude Sonnet)
    │                                  │     Tools: list_dir, read_file, write_file,
    │                                  │            run_command, search_files
    │                                  │
    │                                  ├─ Multi-turn tool loop until task done
    │                                  │
    ├─ Result ←────────────────────── feishu.send (Feishu REST API)
```

Key design decisions:
- **No webhook, no ngrok.** Uses Feishu REST API polling (active pull), works from any network.
- **No Claude Code CLI.** Uses Anthropic API directly for reliable tool calling.
- **Single Python daemon.** One `agent.py` process handles everything.

---

## 2. Components

### 2.1 Feishu Poller (`poller.py`)

Polls Feishu `/im/v1/messages` every 5 seconds for new messages to the bot.
Reuses existing app credentials (`cli_aaa9135baa385bdf`).

- Get tenant access token
- List conversations → get latest messages
- Deduplicate by message_id
- Return new messages to agent loop

### 2.2 Agent Core (`agent.py`)

Main loop that ties everything together:
1. Poll for new Feishu messages
2. For each message → call Anthropic API with tool definitions
3. Anthropic returns either a text response OR a tool call request
4. If tool call → execute locally → feed result back to Anthropic → loop
5. Once Anthropic responds with text → send to Feishu

### 2.3 Tool Executor (`tools.py`)

Tools exposed to the AI model:

| Tool | Implementation | Safety |
|------|---------------|--------|
| `list_directory` | `pathlib.Path.iterdir()` | Read-only |
| `read_file` | `open().read()` | Read-only |
| `write_file` | `open().write()` | Logged |
| `search_files` | `glob` or `Path.rglob()` | Read-only |
| `run_command` | `subprocess.run()` | Path restrictions, logged |

Safety constraints:
- `run_command` restricted to `C:\Users\Harry` by default
- Destructive operations (delete/move/overwrite many files) require confirmation
- All tool calls logged to `~/.claude/feishu-agent/logs/`

### 2.4 Message Sender (`sender.py`)

Sends messages back to user via Feishu `/im/v1/messages` API.
Supports text messages (and optionally card-based results for structured output).

### 2.5 Context Store (`store.py`)

Per-conversation message history stored as JSON files.
Keeps last N messages for context, enabling follow-up conversations like "redo that thing from before."

---

## 3. Data Flow

### 3.1 Single Task Execution

```
1. User: "sort my Downloads folder"
2. Poller detects new message in conversation
3. Agent builds context: [system_prompt, history, new_message]
4. Call Anthropic API with tools
5. AI: tool_call → list_directory("C:/Users/Harry/Downloads")
6. Python executes, returns file list
7. AI: tool_call → run_command("move *.pdf Documents/PDFs") + more moves
8. Python executes each
9. AI: "Done. Sorted 23 files: 5 PDFs → Documents, 8 images → Pictures, ..."
10. Sender delivers message to Feishu
```

### 3.2 Multi-turn Conversation

```
Turn 1: User: "clean desktop"
        AI: sorts files, replies with summary. Saves context.

Turn 2: User: "undo the icon move"
        AI: has context from Turn 1, knows what was moved, can undo.
```

---

## 4. Configuration

Stored in `~/.claude/feishu-agent/config.json`:

```json
{
  "feishu": {
    "app_id": "cli_aaa9135baa385bdf",
    "app_secret": "...",
    "bot_open_id": "ou_1904d3f8aeffac94aa7007c8e1e2f6e0"
  },
  "anthropic": {
    "api_key": "sk-ant-...",
    "model": "claude-sonnet-4-6"
  },
  "agent": {
    "poll_interval_seconds": 5,
    "max_context_messages": 20,
    "max_tool_rounds": 10,
    "command_timeout_seconds": 300
  }
}
```

---

## 5. Error Handling

| Scenario | Handling |
|----------|----------|
| Anthropic API down | Retry 3 times with backoff, reply "AI 暂时不可用" |
| Feishu API rate limit | Backoff, continue polling |
| Tool execution timeout | Return timeout error to AI, let it decide next step |
| Network loss | Log and retry, no crash |
| API key exhausted | Send warning to user via Feishu |

---

## 6. Startup

`pythonw agent.py` — set as Windows startup task.
Runs silently in background (no console window).

---

## 7. File Structure

```
~/.claude/feishu-agent/
├── agent.py          # Main loop
├── poller.py         # Feishu message polling
├── sender.py         # Feishu message sending
├── tools.py          # Tool definitions + execution
├── store.py          # Conversation context storage
├── config.json       # Configuration (gitignored for secrets)
├── state.json        # Last seen message IDs
└── logs/             # Tool execution logs
```

---

## 8. Dependencies

```
anthropic>=0.39.0
requests>=2.28
python-docx  (for Word files)
openpyxl     (for Excel files)
python-pptx  (for PowerPoint files)
reportlab    (for PDF generation)
```

---

## 9. Limitations & Scope

- **In scope:** File management, code writing, document generation, general PC tasks
- **Out of scope:** GUI automation (clicking buttons), real-time streaming, video/audio processing
- **Security:** Only executes commands in user home directory by default
