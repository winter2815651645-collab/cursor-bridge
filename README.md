# Cursor Bridge

A Windows clipboard bridge that fixes CJK text encoding when pasting into [Cursor](https://cursor.com) editor.

## What It Does

Copy Chinese/CJK text from anywhere → Cursor Bridge auto-fixes encoding → paste into Cursor without garbled characters.

Cursor's Chromium WebView mangles CJK clipboard text in two ways:

| Pattern | What happens | Recovery |
|---------|-------------|----------|
| **A** | UTF-8 bytes expanded into UTF-16LE with `0x00` alternation | Reverse byte-expansion |
| **B** | Raw UTF-8 bytes stuffed into `CF_UNICODETEXT` | Decode as UTF-8 + alpha ratio guard (>50%) |

## Features

- **Auto monitor** — polls clipboard every 500ms, fixes encoding on the fly
- **Win+Shift+V** — manual hotkey to fix current clipboard content
- **System tray** — runs in background with context menu (pause, about, exit)
- **Popup window** — dark Slate theme, toggle auto-fix on/off
- **Zero dependencies** — Python 3 stdlib only (tkinter + ctypes)

## Installation

```bash
# Download cursor_bridge.pyw
# Run it (no console window):
pythonw cursor_bridge.pyw
```

### Auto-start on boot

Put `cursor-bridge-startup.vbs` in your Startup folder:

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\
```

## Requirements

- Windows 10/11
- Python 3.10+

No pip install needed. Uses only tkinter and ctypes from the standard library.

## How It Works

```
Any app (browser, WeChat, Notepad...)
    │  Ctrl+C
    ▼
Windows Clipboard (CF_UNICODETEXT)
    │  Cursor Bridge polls every 500ms
    ▼
Encoding detection (Pattern A vs Pattern B)
    │  Recovery
    ▼
Clipboard written back with correct UTF-16LE
    │  Ctrl+V
    ▼
Cursor editor — Chinese displays correctly
```

## Tech Stack

| Layer | Tech |
|-------|------|
| UI | tkinter (tray icon + popup) |
| Clipboard | Win32 API via ctypes (`OpenClipboard`, `GetClipboardData`, `SetClipboardData`) |
| Hotkey | `GetAsyncKeyState` polling |
| Tray icon | `Shell_NotifyIconW` + GDI custom drawing |
| Encoding | Pure Python byte-level recovery |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).

## Author

[winter2815651645-collab](https://github.com/winter2815651645-collab)
