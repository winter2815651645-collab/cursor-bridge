#!/usr/bin/env python3
"""
Cursor Bridge — 中文剪贴板桥
=============================
纯托盘应用，监控剪贴板中的中文文本，通过 Win32 API 以 CF_UNICODETEXT
格式重写剪贴板，解决 Cursor 编辑器对话框粘贴中文乱码的问题。

触发方式：
  - 自动模式：检测剪贴板出现中文 → 自动处理（用户只管 Ctrl+V 贴入 Cursor）
  - 左键托盘图标：弹出输入窗口，粘贴/编辑 → 自动复制
  - 全局快捷键 Win+Shift+V：即时处理当前剪贴板内容

依赖：Python 3 标准库（tkinter + ctypes），无第三方包。
启动：pythonw cursor_bridge.pyw
"""

import tkinter as tk
from tkinter import ttk
import ctypes
from ctypes import wintypes, sizeof, byref, cast, CFUNCTYPE, c_void_p
import threading
import queue
import re
import sys
import os
import time
import traceback

# ═══════════════════════════════════════════════════════════════════════════
# Win32 Constants
# ═══════════════════════════════════════════════════════════════════════════

CF_UNICODETEXT = 13
CF_TEXT        = 1
GMEM_MOVEABLE  = 0x0042

NIM_ADD    = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIF_MESSAGE = 1
NIF_ICON    = 2
NIF_TIP     = 4

WM_LBUTTONUP   = 0x0202
WM_RBUTTONUP   = 0x0205
WM_DESTROY     = 0x0002
WM_APP         = 0x8000
WM_TRAYICON    = WM_APP + 1
WM_COMMAND     = 0x0111

HWND_MESSAGE  = -3

IDI_INFORMATION = 32516

# CJK 字符检测正则（覆盖中日韩统一表意文字、标点、全角符号）
CJK_RE = re.compile(
    r'[一-鿿'          # CJK Unified Ideographs
    r'㐀-䶿'           # CJK Extension A
    r'豈-﫿'           # CJK Compatibility
    r'　-〿'           # CJK Symbols
    r'＀-￯'           # Fullwidth Forms
    r'⺀-⻿'           # CJK Radicals
    r']'
)

# Menu constants
MF_STRING    = 0x0000
MF_SEPARATOR = 0x0800
TPM_LEFTALIGN  = 0x0000
TPM_RIGHTBUTTON = 0x0002

# ═══════════════════════════════════════════════════════════════════════════
# Win32 API Bindings
# ═══════════════════════════════════════════════════════════════════════════

user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32  = ctypes.windll.shell32

# ── Clipboard function signatures (MUST set restype for 64-bit handles) ────
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
user32.EnumClipboardFormats.restype = wintypes.UINT
user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wintypes.UINT
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wintypes.BOOL
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE

kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL

# Menu functions
user32.CreatePopupMenu.argtypes = []
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR]
user32.AppendMenuW.restype = wintypes.BOOL
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
user32.TrackPopupMenu.restype = wintypes.BOOL
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.DestroyMenu.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize",           wintypes.DWORD),
        ("hWnd",             wintypes.HWND),
        ("uID",              wintypes.UINT),
        ("uFlags",           wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon",            wintypes.HICON),
        ("szTip",            wintypes.WCHAR * 128),
        ("dwState",          wintypes.DWORD),
        ("dwStateMask",      wintypes.DWORD),
        ("szInfo",           wintypes.WCHAR * 256),
        ("uVersion",         wintypes.UINT),
        ("szInfoTitle",      wintypes.WCHAR * 64),
        ("dwInfoFlags",      wintypes.DWORD),
        ("guidItem",         wintypes.BYTE * 16),
        ("hBalloonIcon",     wintypes.HICON),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize",        wintypes.UINT),
        ("style",         wintypes.UINT),
        ("lpfnWndProc",   c_void_p),
        ("cbClsExtra",    ctypes.c_int),
        ("cbWndExtra",    ctypes.c_int),
        ("hInstance",     wintypes.HINSTANCE),
        ("hIcon",         wintypes.HICON),
        ("hCursor",       wintypes.HICON),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName",  wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm",       wintypes.HICON),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd",    wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam",  wintypes.WPARAM),
        ("lParam",  wintypes.LPARAM),
        ("time",    wintypes.DWORD),
        ("pt",      POINT),
    ]


WNDPROC_T = CFUNCTYPE(wintypes.LPARAM, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

# POINT-dependent signatures (must follow POINT definition above)
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.DestroyIcon.restype = wintypes.BOOL

# Set argtypes for DefWindowProcW — ctypes defaults to 32-bit int, would overflow on 64-bit LPARAM
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype  = wintypes.LPARAM

# Other tray icon API signatures (prevent 64-bit handle truncation)
user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPVOID]  # 2nd arg = MAKEINTRESOURCE or string
user32.LoadIconW.restype = wintypes.HICON
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                    wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                    wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = wintypes.LPARAM
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None

# ── GDI for custom tray icon ──
gdi32 = ctypes.windll.gdi32

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT, wintypes.LPVOID]
gdi32.CreateBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
gdi32.CreatePen.restype = wintypes.HPEN
gdi32.MoveToEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.LPVOID]
gdi32.MoveToEx.restype = wintypes.BOOL
gdi32.LineTo.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.LineTo.restype = wintypes.BOOL
gdi32.Arc.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.Arc.restype = wintypes.BOOL
gdi32.Ellipse.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.Ellipse.restype = wintypes.BOOL
gdi32.PolyBezier.argtypes = [wintypes.HDC, ctypes.POINTER(POINT), wintypes.DWORD]
gdi32.PolyBezier.restype = wintypes.BOOL
gdi32.SetBkColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
gdi32.SetBkColor.restype = wintypes.COLORREF
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.SetBkMode.restype = ctypes.c_int
gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.GetStockObject.restype = wintypes.HGDIOBJ

gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(wintypes.HANDLE), wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP

user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
user32.FillRect.restype = ctypes.c_int

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize",          wintypes.DWORD),
        ("biWidth",         ctypes.c_long),
        ("biHeight",        ctypes.c_long),
        ("biPlanes",        wintypes.WORD),
        ("biBitCount",      wintypes.WORD),
        ("biCompression",   wintypes.DWORD),
        ("biSizeImage",     wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed",       wintypes.DWORD),
        ("biClrImportant",  wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),  # color table for bpp<=8 (unused here)
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon",     wintypes.BOOL),
        ("xHotspot",  wintypes.DWORD),
        ("yHotspot",  wintypes.DWORD),
        ("hbmMask",   wintypes.HBITMAP),
        ("hbmColor",  wintypes.HBITMAP),
    ]

user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
user32.CreateIconIndirect.restype = wintypes.HICON
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL


# ═══════════════════════════════════════════════════════════════════════════
# Clipboard Operations
# ═══════════════════════════════════════════════════════════════════════════

# HTML Format — what Chromium/Electron (Cursor) uses for rich-text copy
_CF_HTML = user32.RegisterClipboardFormatW("HTML Format")

# All known text-bearing formats to try, in priority order
_TEXT_FORMATS = [CF_UNICODETEXT, CF_TEXT]


def _extract_text_from_html(html: str) -> str | None:
    """Extract plain text from clipboard HTML fragment (Chromium style)."""
    import html as _html_mod
    try:
        # HTML Format has headers then <html><body>…</body></html>
        # Find the HTML part
        start = html.find("<html>")
        if start == -1:
            start = html.find("<HTML>")
        if start == -1:
            return None
        # Strip HTML tags with a simple regex (no stdlib HTML parser needed)
        body = html[start:]
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', body)
        # Decode HTML entities
        text = _html_mod.unescape(text)
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text if text else None
    except Exception:
        return None


def _enumerate_all_formats_locked() -> str | None:
    """Brute-force: enumerate every clipboard format, read raw bytes, look for CJK.
    Assumes clipboard is already open."""
    fmt = 0
    tried = set()
    while True:
        fmt = user32.EnumClipboardFormats(fmt)
        if fmt == 0:
            break
        if fmt in tried:
            continue
        tried.add(fmt)

        # Skip non-text formats (bitmap, DIB, etc.)
        if fmt in (2, 3, 8, 14, 15, 16, 17):
            continue

        h = user32.GetClipboardData(fmt)
        if not h:
            continue
        p = kernel32.GlobalLock(h)
        if not p:
            continue
        try:
            sz = kernel32.GlobalSize(h)
            if sz == 0 or sz > 1_000_000:
                continue
            buf = (ctypes.c_char * sz)()
            ctypes.memmove(buf, p, sz)
            raw = bytes(buf)

            # Check for UTF-8 encoded CJK
            try:
                text = raw.decode('utf-8')
                if has_cjk(text):
                    return text
            except UnicodeDecodeError:
                pass
            # Check for UTF-16LE encoded CJK
            try:
                text = raw.decode('utf-16-le')
                if has_cjk(text):
                    return text
            except UnicodeDecodeError:
                pass
        except OSError:
            pass
        finally:
            kernel32.GlobalUnlock(h)
    return None


def _recover_utf8_mojibake(text: str) -> str | None:
    """
    Detect if `text` looks like UTF-8 bytes misinterpreted as Latin-1,
    and recover the original CJK text. Returns None if not mojibake.

    Example: 'è¿è¡Œä¸­' → '运行中'
    """
    if not text or has_cjk(text):
        return None

    # Count Latin-1 accented chars; if >30% of non-ASCII chars are in 0xC0–0xFF
    # range, it's likely mojibake
    non_ascii = [c for c in text if ord(c) >= 128]
    if not non_ascii:
        return None
    latin1_high = sum(1 for c in non_ascii if 0xC0 <= ord(c) <= 0xFF)
    if latin1_high / len(non_ascii) < 0.3:
        return None

    # Try to recover: encode back as Latin-1 bytes → decode as UTF-8
    try:
        raw = text.encode('latin-1')
        recovered = raw.decode('utf-8')
        if has_cjk(recovered):
            return recovered
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return None


def _recover_utf8_in_utf16le(raw: bytes) -> str | None:
    """
    Cursor's AI chat panel (Chromium WebView) sometimes puts UTF-8 bytes
    directly into CF_UNICODETEXT. Two patterns are observed:

    Pattern A — byte-expanded: each UTF-8 byte stored as a 16-bit char
    (non-zero even bytes, 0x00 odd bytes).
      Raw:  E6 00 8E 00 A7 00 E5 00 88 00 B6 00 ...
      Even: E6 8E A7 E5 88 B6 → UTF-8 decode → 控制

    Pattern B — raw UTF-8: no padding, just the UTF-8 stream verbatim.
      Raw:  41 6E 74 68 72 6F 70 69 63 20 41 50 49
      wstring_at interprets as UTF-16LE pairs → CJK mojibake (湁桴潲楰⁣偁I)
      Fix: decode raw bytes directly as UTF-8 → Anthropic API

    Safety for Pattern B: only applied when decoded text is pure ASCII
    (English recovery). The edge case where proper UTF-16LE CJK text has
    bytes that also form valid UTF-8 is possible but rare in practice.
    """
    if len(raw) < 2:
        return None

    # ── Pattern A: byte-expanded (alternating 0x00) ──
    # At least 80% of odd bytes must be 0x00, and at least 50% of even
    # bytes non-zero, to qualify as byte-expanded UTF-8-in-UTF16LE.
    odd_zeros = sum(1 for i in range(1, min(len(raw), 100), 2) if raw[i] == 0)
    odd_total = min(len(raw), 100) // 2
    even_nonzero = sum(1 for i in range(0, min(len(raw), 100), 2) if raw[i] != 0)
    even_total = (min(len(raw), 100) + 1) // 2

    if odd_total > 0 and odd_zeros / odd_total >= 0.8:
        if even_nonzero / even_total >= 0.5:
            # Extract even bytes (the UTF-8 stream), strip trailing nulls
            extracted = bytes(raw[i] for i in range(0, len(raw), 2))
            extracted = extracted.rstrip(b'\x00')
            try:
                return extracted.decode('utf-8')
            except UnicodeDecodeError:
                pass
        return None  # too many nulls in even bytes → likely actual ASCII

    # ── Pattern B: raw UTF-8 (no 0x00 alternation) ──
    # Cursor sometimes drops raw UTF-8 into CF_UNICODETEXT. When all bytes
    # decode as valid UTF-8 yielding pure ASCII, we've recovered garbled
    # English text (e.g., "Anthropic API" → "湁桴潲楰⁣偁I" → fix back).
    #
    # NOTE: a properly-stored UTF-16LE CJK string whose bytes happen to
    # also be valid UTF-8 (e.g. "你好" bytes 60 4F 7D 59 decode as "`O}Y")
    # would be mis-corrected. This is rare — most CJK UTF-16LE code units
    # contain bytes ≥0x80 that break UTF-8 decoding.
    raw_stripped = raw.rstrip(b'\x00')
    if raw_stripped:
        try:
            recovered = raw_stripped.decode('utf-8')
            # Only recover text that looks like actual English/code content:
            # pure ASCII AND >50% alphabetic characters.
            # This prevents false positives on real UTF-16LE CJK text whose
            # bytes happen to form valid ASCII UTF-8 (e.g., "你好" →
            # "`O}Y", which has only 50% alpha and is rejected).
            if recovered.isascii():
                alpha_ratio = sum(c.isalpha() for c in recovered) / max(len(recovered), 1)
                if alpha_ratio > 0.5:
                    return recovered
        except UnicodeDecodeError:
            pass

    return None


# ── File-based debug log (console may not be visible with .pyw) ──────────
_DEBUG    = "--debug" in sys.argv
_LOG_PATH = os.path.join(os.path.expanduser("~"), "Desktop", "bridge_debug.log")

def _log(msg: str) -> None:
    """Append timestamped message to debug log file (only when --debug is passed)."""
    if not _DEBUG:
        return
    try:
        ts = time.strftime("%H:%M:%S")
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def _read_format_locked(fmt: int) -> bytes | None:
    """Read a format as raw bytes. Assumes clipboard is already open."""
    h = user32.GetClipboardData(fmt)
    if not h:
        return None
    p = kernel32.GlobalLock(h)
    if not p:
        return None
    try:
        sz = kernel32.GlobalSize(h)
        if sz == 0:
            return None
        buf = (ctypes.c_char * sz)()
        ctypes.memmove(buf, p, sz)
        return bytes(buf)
    except OSError:
        return None
    finally:
        kernel32.GlobalUnlock(h)


def _read_text_locked(fmt: int) -> str | None:
    """Read a text format as string. Assumes clipboard is already open."""
    if not user32.IsClipboardFormatAvailable(fmt):
        return None
    h = user32.GetClipboardData(fmt)
    if not h:
        return None
    p = kernel32.GlobalLock(h)
    if not p:
        return None
    try:
        if fmt == CF_UNICODETEXT:
            return ctypes.wstring_at(p)
        else:
            return ctypes.string_at(p).decode('utf-8', errors='surrogateescape')
    except (OSError, UnicodeDecodeError):
        return None
    finally:
        kernel32.GlobalUnlock(h)


def clipboard_read() -> str | None:
    """Read text from clipboard. Opens once, tries all strategies, closes."""
    if not user32.OpenClipboard(0):
        _log("clipboard_read: OpenClipboard failed")
        return None
    try:
        # Strategy 0: raw CF_UNICODETEXT → UTF-8-in-UTF16LE recovery (Cursor WebView)
        raw = _read_format_locked(CF_UNICODETEXT)
        if raw:
            recovered = _recover_utf8_in_utf16le(raw)
            if recovered:
                return recovered

        # Strategy 1+2: CF_UNICODETEXT and CF_TEXT as decoded strings
        for fmt in _TEXT_FORMATS:
            text = _read_text_locked(fmt)
            if text:
                if has_cjk(text):
                    return text
                recovered = _recover_utf8_mojibake(text)
                if recovered:
                    return recovered

        # Strategy 3: HTML Format
        text = _read_text_locked(_CF_HTML)
        if text:
            plain = _extract_text_from_html(text)
            if plain and has_cjk(plain):
                return plain
            if plain:
                recovered = _recover_utf8_mojibake(plain)
                if recovered:
                    return recovered

        # Strategy 4: brute-force enumerate all formats
        text = _enumerate_all_formats_locked()
        if text:
            return text

        # Last resort: wstring_at
        if user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            h = user32.GetClipboardData(CF_UNICODETEXT)
            if h:
                p = kernel32.GlobalLock(h)
                if p:
                    try:
                        return ctypes.wstring_at(p) or None
                    except OSError:
                        return None
                    finally:
                        kernel32.GlobalUnlock(h)
        return None
    finally:
        user32.CloseClipboard()


def clipboard_write(text: str) -> bool:
    """
    Write text to clipboard as CF_UNICODETEXT (UTF-16LE).
    Retries up to 5 times if clipboard is locked.
    """
    normalized = text.replace('\n', '\r\n')
    wstr = normalized + '\0'
    data = wstr.encode('utf-16-le')
    byte_len = len(data)

    for _ in range(5):
        if user32.OpenClipboard(0):
            break
        time.sleep(0.01)
    else:
        return False

    try:
        user32.EmptyClipboard()
        hmem = kernel32.GlobalAlloc(GMEM_MOVEABLE, byte_len)
        if not hmem:
            return False
        pmem = kernel32.GlobalLock(hmem)
        if not pmem:
            kernel32.GlobalFree(hmem)
            return False
        try:
            ctypes.memmove(pmem, data, byte_len)
        finally:
            kernel32.GlobalUnlock(hmem)
        user32.SetClipboardData(CF_UNICODETEXT, hmem)
        return True
    finally:
        user32.CloseClipboard()


def has_cjk(text: str) -> bool:
    """True if text contains CJK characters."""
    return bool(CJK_RE.search(text))


# ═══════════════════════════════════════════════════════════════════════════
# Tray Icon (runs in dedicated thread with its own message pump)
# ═══════════════════════════════════════════════════════════════════════════

def _create_bridge_icon() -> wintypes.HICON:
    """Draw a custom bridge icon with GDI + 32-bit DIBSection for alpha.

    Uses CreateDIBSection (32-bpp BGRA) for the color bitmap so we get a
    real alpha channel. The icon shape is controlled by per-pixel alpha
    rather than the AND mask. The AND mask is set to all-0s (fully opaque),
    letting alpha handle transparency.

    Design: Bold bridge silhouette on a bright accent circle.
    """
    SIZE = 32
    # BGR colorrefs (0x00BBGGRR)
    BLUE_FILL = 0xD59B5B    # #5b9bd5 accent blue
    WHITE     = 0xFFFFFF
    TR_BG     = 0x000000    # transparent bg color (won't be visible with alpha)

    hdc_screen = user32.GetDC(0)

    # ── Build 32-bpp DIBSection for the color bitmap ──
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize   = sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth  = SIZE
    bmi.bmiHeader.biHeight = -SIZE          # negative = top-down DIB (GDI compatible)
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0         # BI_RGB

    bits_ptr = wintypes.HANDLE()
    hbm_color = gdi32.CreateDIBSection(hdc_screen, byref(bmi), 0,
                                        byref(bits_ptr), 0, 0)
    if not hbm_color:
        user32.ReleaseDC(0, hdc_screen)
        return user32.LoadIconW(0, IDI_INFORMATION)

    # Get raw pixel pointer for alpha channel manipulation
    bits_ptr_val = bits_ptr.value

    # ── Monochrome mask bitmap: all-0s (opaque everywhere) ──
    # Allocate with explicit zero-filled data so mask pixels are 0 (opaque).
    mask_data = (ctypes.c_byte * (SIZE * SIZE // 8))()
    ctypes.memset(mask_data, 0, SIZE * SIZE // 8)
    hbm_mask = gdi32.CreateBitmap(SIZE, SIZE, 1, 1, mask_data)
    if not hbm_mask:
        gdi32.DeleteObject(hbm_color)
        user32.ReleaseDC(0, hdc_screen)
        return user32.LoadIconW(0, IDI_INFORMATION)

    # ── Draw on the DIBSection via GDI ──
    hdc_color = gdi32.CreateCompatibleDC(hdc_screen)
    old_color = gdi32.SelectObject(hdc_color, hbm_color)

    # Initialise image to transparent black (alpha=0)
    # CreateDIBSection initialises to undefined content, so fill manually.
    pixel_count = SIZE * SIZE
    pixel_array = ctypes.cast(bits_ptr_val, ctypes.POINTER(ctypes.c_uint32))
    for i in range(pixel_count):
        pixel_array[i] = 0

    # Draw filled circle (accent blue) using Ellipse on the DIBSection DC
    brush_bg = gdi32.CreateSolidBrush(BLUE_FILL)
    old_brush = gdi32.SelectObject(hdc_color, brush_bg)
    old_pen = gdi32.SelectObject(hdc_color, gdi32.GetStockObject(5))  # NULL_PEN
    gdi32.SetBkMode(hdc_color, 1)  # TRANSPARENT
    gdi32.Ellipse(hdc_color, 2, 2, 30, 30)

    # Bridge deck
    pen_white3 = gdi32.CreatePen(0, 3, WHITE)
    gdi32.SelectObject(hdc_color, pen_white3)
    gdi32.MoveToEx(hdc_color, 5, 22, None)
    gdi32.LineTo(hdc_color, 27, 22)

    # Towers
    gdi32.MoveToEx(hdc_color, 10, 8, None)
    gdi32.LineTo(hdc_color, 10, 24)
    gdi32.MoveToEx(hdc_color, 22, 8, None)
    gdi32.LineTo(hdc_color, 22, 24)

    # Suspension cable
    pen_white2 = gdi32.CreatePen(0, 2, WHITE)
    gdi32.SelectObject(hdc_color, pen_white2)
    gdi32.Arc(hdc_color, 10, 0, 22, 17,  10, 8,  22, 8)

    # Suspenders
    pen_white1 = gdi32.CreatePen(0, 1, WHITE)
    gdi32.SelectObject(hdc_color, pen_white1)
    for cx in (14, 18):
        gdi32.MoveToEx(hdc_color, cx, 10, None)
        gdi32.LineTo(hdc_color, cx, 21)

    # ── Set alpha channel ──
    # GDI drawing sets RGB but leaves alpha=0 (transparent).
    # After GDI drawing, walk pixels and set alpha=255 wherever
    # the pixel is not pure transparent-black (0x00000000).
    for y in range(SIZE):
        for x in range(SIZE):
            idx = y * SIZE + x
            pixel = pixel_array[idx]
            if pixel & 0x00FFFFFF:  # any non-zero BGR component = drawn pixel
                pixel_array[idx] = pixel | 0xFF000000  # set alpha=255

    # Cleanup GDI objects
    gdi32.SelectObject(hdc_color, old_brush)
    gdi32.SelectObject(hdc_color, old_pen)
    gdi32.SelectObject(hdc_color, old_color)
    gdi32.DeleteObject(brush_bg)
    gdi32.DeleteObject(pen_white3)
    gdi32.DeleteObject(pen_white2)
    gdi32.DeleteObject(pen_white1)
    gdi32.DeleteDC(hdc_color)
    user32.ReleaseDC(0, hdc_screen)

    # ── Build HICON ──
    ii = ICONINFO()
    ii.fIcon    = True
    ii.hbmMask  = hbm_mask
    ii.hbmColor = hbm_color
    hicon = user32.CreateIconIndirect(byref(ii))

    # Clean up source bitmaps -- CreateIconIndirect copies the data
    gdi32.DeleteObject(hbm_color)
    gdi32.DeleteObject(hbm_mask)

    if not hicon:
        return user32.LoadIconW(0, IDI_INFORMATION)

    return hicon


def _tray_thread_main(event_queue: queue.Queue):
    """Tray icon thread: creates message-only window, runs message loop."""

    hinst = kernel32.GetModuleHandleW(None)

    def _show_tray_menu(hwnd):
        """Show right-click context menu on tray icon."""
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, 1, "显示窗口")
        user32.AppendMenuW(menu, MF_STRING, 3, "关于")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, 2, "退出")

        user32.SetForegroundWindow(hwnd)
        pt = POINT()
        user32.GetCursorPos(byref(pt))
        user32.TrackPopupMenu(menu, TPM_LEFTALIGN | TPM_RIGHTBUTTON,
                              pt.x, pt.y, 0, hwnd, None)
        user32.DestroyMenu(menu)

    @WNDPROC_T
    def wndproc(hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            evt = lparam & 0xFFFF
            if evt == WM_LBUTTONUP:
                try: event_queue.put_nowait("toggle_popup")
                except queue.Full: pass
            elif evt == WM_RBUTTONUP:
                _show_tray_menu(hwnd)
        elif msg == WM_COMMAND:
            cmd = wparam & 0xFFFF
            if cmd == 1:  # Show window
                try: event_queue.put_nowait("show_popup")
                except queue.Full: pass
            elif cmd == 2:  # Exit
                try: event_queue.put_nowait("quit")
                except queue.Full: pass
            elif cmd == 3:  # About
                try: event_queue.put_nowait("about")
                except queue.Full: pass
        elif msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    wc = WNDCLASSEXW()
    wc.cbSize        = sizeof(WNDCLASSEXW)
    wc.lpfnWndProc   = cast(wndproc, c_void_p)
    wc.hInstance     = hinst
    wc.lpszClassName = "CursorBridgeTrayWnd"

    atom = user32.RegisterClassExW(byref(wc))
    if not atom:
        event_queue.put(("error", "RegisterClassExW failed"))
        return

    hwnd = user32.CreateWindowExW(
        0, "CursorBridgeTrayWnd", "CursorBridge", 0,
        0, 0, 0, 0,
        wintypes.HWND(HWND_MESSAGE), 0, hinst, 0
    )
    if not hwnd:
        event_queue.put(("error", "CreateWindowExW failed"))
        return

    hicon = _create_bridge_icon()

    nid = NOTIFYICONDATAW()
    nid.cbSize           = sizeof(NOTIFYICONDATAW)
    nid.hWnd             = hwnd
    nid.uID              = 1
    nid.uFlags           = NIF_ICON | NIF_MESSAGE | NIF_TIP
    nid.uCallbackMessage = WM_TRAYICON
    nid.hIcon            = hicon
    nid.szTip            = "Cursor Bridge - 中文剪贴板桥"

    if not shell32.Shell_NotifyIconW(NIM_ADD, byref(nid)):
        event_queue.put(("error", "Shell_NotifyIconW failed"))
        user32.DestroyWindow(hwnd)
        return

    event_queue.put(("ready", hwnd))

    msg = MSG()
    while True:
        ret = user32.GetMessageW(byref(msg), 0, 0, 0)
        if ret in (0, -1):
            break
        user32.TranslateMessage(byref(msg))
        user32.DispatchMessageW(byref(msg))

    shell32.Shell_NotifyIconW(NIM_DELETE, byref(nid))
    if hicon:
        user32.DestroyIcon(hicon)


# ═══════════════════════════════════════════════════════════════════════════
# Popup Window
# ═══════════════════════════════════════════════════════════════════════════

class PopupWindow:
    """Frameless popup for manual Chinese text input. Canvas-drawn Slate theme."""

    # ── Color palette (macOS dark) ─────────────────────────────────────
    CLR = {
        "outer":       "#1e1e20",
        "title_bg":    "#1e1e20",
        "edit_bg":     "#29292b",
        "text_fg":     "#cccccc",
        "accent":      "#5b9bd5",
        "success":     "#7ec87b",
        "error":       "#e05565",
        "warn":        "#d4a853",
        "border":      "#333336",
        "border_hov":  "#5b9bd5",
        "status_fg":   "#808080",
        "toggle_off":  "#3a3a3d",
        "toggle_knob": "#ffffff",
        "close_hover": "#ff5f57",
        "close_ring":  "#555559",
    }

    WIDTH, HEIGHT = 420, 250
    CORNER = 12
    PLACEHOLDER = "在此粘贴中文 (Ctrl+V)"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.win = None
        self.canvas = None
        self.text = None
        self._auto_mode = True
        self._placeholder_shown = True
        self._drag_data = (0, 0)
        self._has_content = False

        # Status state
        self._status_msg = ""
        self._status_color = self.CLR["status_fg"]

    # ── Show / hide ──────────────────────────────────────────────────

    def show(self):
        try:
            self._show_impl()
        except Exception:
            _log(f"PopupWindow.show() crash:\n{traceback.format_exc()}")

    def _show_impl(self):
        if self.win and self.win.winfo_exists():
            self._position_near_cursor()
            self.win.deiconify()
            self.win.lift()
            self._paste_clipboard_into_textarea()
            return
        self._build()
        self._position_near_cursor()
        self._paste_clipboard_into_textarea()
        self._animate_in()

    def hide(self):
        """Hide the popup. Destroys the Toplevel to avoid Tcl/Tk withdraw
        bugs on Windows (overrideredirect windows that are withdrawn and
        later deiconified can lock up the process)."""
        if self.win and self.win.winfo_exists():
            try:
                self.win.destroy()
            except Exception:
                pass
            self.win = None
            self.canvas = None
            self.text = None
            self._text_win = None

    def toggle(self):
        if self.is_visible():
            self.hide()
        else:
            self.show()

    def is_visible(self) -> bool:
        try:
            return self.win is not None and self.win.winfo_exists() and self.win.winfo_viewable()
        except Exception:
            return False

    def set_status_line(self, text: str, color: str = None):
        if color is None:
            color = self.CLR["success"]
        self._status_msg = text
        self._status_color = color
        self._redraw_status()

    def _redraw_status(self):
        if not self.canvas or not self.canvas.winfo_exists():
            return
        char_count = len(self.get_text())
        msg = self._status_msg
        display = f"{msg}  |  {char_count} 字" if msg else f"{char_count} 字"
        self.canvas.itemconfig("status_line", text=display, fill=self._status_color)

    def get_text(self) -> str:
        if self.text and self.text.winfo_exists():
            return self.text.get("1.0", "end-1c")
        return ""

    # ═══════════════════════════════════════════════════════════════════
    # Build UI  (Canvas-drawn Slate theme)
    # ═══════════════════════════════════════════════════════════════════

    def _build(self):
        self.win = tk.Toplevel(self.root)
        self.win.title("Cursor Bridge")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-toolwindow", True)
        self.win.configure(bg=self.CLR["outer"])
        self.win.geometry(f"{self.WIDTH}x{self.HEIGHT}")

        # ── Full-surface Canvas ──
        self.canvas = tk.Canvas(
            self.win, width=self.WIDTH, height=self.HEIGHT,
            bg=self.CLR["outer"], highlightthickness=0, bd=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self._draw_shell()
        self._draw_title()
        self._draw_text_area()
        self._draw_bottom()
        self._redraw_status()

        # ── Window-level bindings ──
        self.win.bind("<FocusOut>", self._on_focus_out)
        self.win.bind("<Escape>", lambda e: self.hide())

    # ── Shell ───────────────────────────────────────────────────────

    def _draw_shell(self):
        """Rounded-rect outer shell — no border, clean edge."""
        self._round_rect(0, 0, self.WIDTH, self.HEIGHT, self.CORNER,
                         fill=self.CLR["outer"], outline="", tags="shell")

    # ── Title bar ───────────────────────────────────────────────────

    def _draw_title(self):
        """Title bar: bridge logo + label + macOS traffic-light close button."""
        c = self.canvas

        # Full-width invisible drag target (drawn first = bottom of z-order)
        c.create_rectangle(0, 0, self.WIDTH, 34, fill="", outline="", tags="title_bar")

        # Logo: small bridge icon
        lx, ly = 16, 17
        c.create_rectangle(lx - 4, ly - 4, lx - 1, ly + 5,
                           fill=self.CLR["accent"], outline="", tags=("logo", "title_bar"))
        c.create_rectangle(lx + 1, ly - 4, lx + 4, ly + 5,
                           fill=self.CLR["accent"], outline="", tags=("logo", "title_bar"))
        c.create_arc(lx - 6, ly - 8, lx + 6, ly + 2, start=0, extent=180,
                     style="arc", outline=self.CLR["accent"], width=2,
                     tags=("logo", "title_bar"))

        # ── Title text (small, refined) ──
        c.create_text(34, 17, text="Cursor Bridge", anchor="w",
                      fill="#999999", font=("Segoe UI", 9),
                      tags=("logo", "title_bar"))

        # ── macOS traffic-light close button ──
        cx, cy = self.WIDTH - 17, 17
        cr = 6

        # Circle (subtle gray, turns red on hover)
        c.create_oval(cx - cr, cy - cr, cx + cr, cy + cr,
                      fill=self.CLR["close_ring"], outline="",
                      tags="close_btn_circle")

        # X mark (matches circle color when idle, white on hover)
        xs = 3
        c.create_line(cx - xs, cy - xs, cx + xs, cy + xs,
                      fill="#999999", width=1.5, tags="close_btn_x")
        c.create_line(cx + xs, cy - xs, cx - xs, cy + xs,
                      fill="#999999", width=1.5, tags="close_btn_x")

        # Invisible hit area
        hr = 10
        c.create_oval(cx - hr, cy - hr, cx + hr, cy + hr,
                      fill="", outline="", tags="close_btn")

        # Bindings
        c.tag_bind("close_btn", "<Button-1>", lambda e: self.hide())
        c.tag_bind("close_btn", "<Enter>",
                   lambda e: (c.itemconfig("close_btn_circle",
                                          fill=self.CLR["close_hover"]),
                              c.itemconfig("close_btn_x", fill="#ffffff")))
        c.tag_bind("close_btn", "<Leave>",
                   lambda e: (c.itemconfig("close_btn_circle",
                                          fill=self.CLR["close_ring"]),
                              c.itemconfig("close_btn_x", fill="#999999")))

        # ── Drag ──
        for tag in ("title_bar", "logo"):
            c.tag_bind(tag, "<Button-1>", self._drag_start)
            c.tag_bind(tag, "<B1-Motion>", self._drag_move)

    # ── Text area ───────────────────────────────────────────────────

    def _draw_text_area(self):
        """Embedded Text widget with static border, generous padding."""
        c = self.canvas

        pad = 12
        x1, y1 = pad, 36
        x2, y2 = self.WIDTH - pad, self.HEIGHT - 26
        r = 8

        # Static rounded frame — no hover effects
        self._round_rect(x1, y1, x2, y2, r,
                         fill=self.CLR["edit_bg"], outline=self.CLR["border"], width=1,
                         tags="edit_frame")

        # Text widget (embedded in canvas)
        self.text = tk.Text(
            self.win, wrap="word",
            bg=self.CLR["edit_bg"], fg=self.CLR["text_fg"],
            insertbackground=self.CLR["accent"],
            font=("Microsoft YaHei UI", 11),
            bd=0, padx=10, pady=8,
            width=36, height=6, undo=True,
            relief="flat", highlightthickness=0,
        )
        self._text_win = c.create_window(
            x1 + 5, y1 + 5, window=self.text, anchor="nw",
            width=(x2 - x1) - 10, height=(y2 - y1) - 10,
        )

        self._show_placeholder()

        # Bindings
        self.text.bind("<FocusIn>", self._on_focus_in)
        self.text.bind("<Escape>", lambda e: self.hide())
        self.text.bind("<<Modified>>", self._on_modified)
        self.text.bind("<Control-v>", self._on_ctrl_v)
        self.text.bind("<Control-V>", self._on_ctrl_v)
        self.text.bind("<KeyRelease>", lambda e: self._redraw_status())

        c.tag_bind("edit_frame", "<Button-1>", lambda e: self.text.focus_set())

    # ── Bottom bar ──────────────────────────────────────────────────

    def _draw_bottom(self):
        """Thin separator line + floating status + toggle switch."""
        c = self.canvas
        pad = 12
        sep_y = self.HEIGHT - 26

        # Separator line
        c.create_line(pad, sep_y, self.WIDTH - pad, sep_y,
                      fill=self.CLR["border"], width=1, tags="bottom_bar")

        # Status text
        c.create_text(14, self.HEIGHT - 13, text="", anchor="w",
                      fill=self.CLR["status_fg"], font=("Segoe UI", 8),
                      tags="status_line")

        # ── Toggle switch ──
        tx = self.WIDTH - 56
        ty = self.HEIGHT - 13

        # Label
        c.create_text(tx - 8, ty, text="自动", anchor="e",
                      fill=self.CLR["text_fg"], font=("Microsoft YaHei UI", 8),
                      tags=("toggle_label", "bottom_bar"))

        self._draw_toggle()

        for t in ("toggle_track", "toggle_knob", "toggle_label"):
            c.tag_bind(t, "<Button-1>", lambda e: self._on_toggle())

    def _draw_toggle(self):
        """Draw the toggle switch in its current state."""
        c = self.canvas
        c.delete("toggle_track", "toggle_knob")

        tx, ty = self.WIDTH - 56, self.HEIGHT - 13
        sw_x1, sw_y1 = tx, ty - 8
        sw_x2, sw_y2 = tx + 34, ty + 8

        self._round_rect(sw_x1, sw_y1, sw_x2, sw_y2, 8,
                         fill=self.CLR["accent"] if self._auto_mode else self.CLR["toggle_off"],
                         outline="", tags="toggle_track")

        knob_r = 6
        knob_x = sw_x2 - 10 if self._auto_mode else sw_x1 + 10
        c.create_oval(knob_x - knob_r, ty - knob_r,
                      knob_x + knob_r, ty + knob_r,
                      fill=self.CLR["toggle_knob"], outline="", tags="toggle_knob")

    def _on_toggle(self):
        self._auto_mode = not self._auto_mode
        self._draw_toggle()
        if self._auto_mode and not self._placeholder_shown:
            self._copy_to_clipboard()

    # ── Round-rect helper ───────────────────────────────────────

    def _round_rect(self, x1, y1, x2, y2, r, fill="", outline="", width=1, tags=None):
        """Draw a rounded rectangle. Returns list of item IDs."""
        c = self.canvas
        opts = {}
        if tags:
            opts["tags"] = tags

        items = []

        if fill:
            fopts = {**opts, "fill": fill, "outline": ""}
            items.append(c.create_arc(x1, y1, x1 + 2*r, y1 + 2*r,
                         start=90, extent=90, style="pieslice", **fopts))
            items.append(c.create_arc(x2 - 2*r, y1, x2, y1 + 2*r,
                         start=0, extent=90, style="pieslice", **fopts))
            items.append(c.create_arc(x1, y2 - 2*r, x1 + 2*r, y2,
                         start=180, extent=90, style="pieslice", **fopts))
            items.append(c.create_arc(x2 - 2*r, y2 - 2*r, x2, y2,
                         start=270, extent=90, style="pieslice", **fopts))
            items.append(c.create_rectangle(x1 + r, y1, x2 - r, y2,
                                            fill=fill, outline="", **opts))
            items.append(c.create_rectangle(x1, y1 + r, x2, y2 - r,
                                            fill=fill, outline="", **opts))

        if outline:
            oopts = {**opts, "outline": outline, "width": width}
            items.append(c.create_arc(x1, y1, x1 + 2*r, y1 + 2*r,
                         start=90, extent=90, style="arc", **oopts))
            items.append(c.create_arc(x2 - 2*r, y1, x2, y1 + 2*r,
                         start=0, extent=90, style="arc", **oopts))
            items.append(c.create_arc(x1, y2 - 2*r, x1 + 2*r, y2,
                         start=180, extent=90, style="arc", **oopts))
            items.append(c.create_arc(x2 - 2*r, y2 - 2*r, x2, y2,
                         start=270, extent=90, style="arc", **oopts))
            items.append(c.create_line(x1 + r, y1, x2 - r, y1,
                                       fill=outline, width=width, **opts))
            items.append(c.create_line(x1 + r, y2, x2 - r, y2,
                                       fill=outline, width=width, **opts))
            items.append(c.create_line(x1, y1 + r, x1, y2 - r,
                                       fill=outline, width=width, **opts))
            items.append(c.create_line(x2, y1 + r, x2, y2 - r,
                                       fill=outline, width=width, **opts))

        return items

    # ── Animation ──────────────────────────────────────────────────

    def _animate_in(self):
        """Scale-up from 60% in ~120ms."""
        try:
            self._animate_in_impl()
        except Exception:
            _log(f"_animate_in crash:\n{traceback.format_exc()}")

    def _animate_in_impl(self):
        if not self.win or not self.win.winfo_exists():
            return
        x = self.win.winfo_x()
        y = self.win.winfo_y()
        tw, th = self.WIDTH, self.HEIGHT
        cx, cy = x + tw // 2, y + th // 2

        steps = 6
        for i in range(1, steps + 1):
            if not self.win or not self.win.winfo_exists() or not self.win.winfo_viewable():
                return  # window was hidden mid-animation
            s = 0.6 + 0.4 * (i / steps)
            w, h = int(tw * s), int(th * s)
            self.win.geometry(f"{w}x{h}+{cx - w // 2}+{cy - h // 2}")
            self.win.update()
            self.win.after(18)

    # ── Placeholder ──────────────────────────────────────────────────

    def _show_placeholder(self):
        if self.text and self.text.winfo_exists():
            self.text.delete("1.0", "end")
            self.text.insert("1.0", self.PLACEHOLDER)
            self.text.config(fg="#5c6370")
            self._placeholder_shown = True

    def _clear_placeholder(self):
        if self._placeholder_shown:
            self.text.delete("1.0", "end")
            self.text.config(fg=self.CLR["text_fg"])
            self._placeholder_shown = False

    # ── Event handlers ───────────────────────────────────────────────

    def _on_focus_in(self, event):
        self._clear_placeholder()

    def _on_ctrl_v(self, event):
        self._clear_placeholder()
        self.win.after(20, self._post_paste)

    def _post_paste(self):
        self._copy_to_clipboard()
        self._has_content = True
        self._redraw_status()

    def _on_modified(self, event=None):
        if self._placeholder_shown:
            return
        self.text.edit_modified(False)
        if self._auto_mode:
            self._copy_to_clipboard()
        self._redraw_status()

    def _on_focus_out(self, event):
        if self.win and self.win.winfo_exists():
            self.win.after(200, self._check_hide)

    def _check_hide(self):
        try:
            if self.win and self.win.winfo_exists():
                f = self.win.focus_get()
                if f is None:
                    self.hide()
        except Exception:
            pass

    # ── Drag ─────────────────────────────────────────────────────────

    def _drag_start(self, event):
        self._drag_data = (event.x_root, event.y_root)

    def _drag_move(self, event):
        dx = event.x_root - self._drag_data[0]
        dy = event.y_root - self._drag_data[1]
        self._drag_data = (event.x_root, event.y_root)
        x = self.win.winfo_x() + dx
        y = self.win.winfo_y() + dy
        self.win.geometry(f"+{x}+{y}")

    # ── Positioning ──────────────────────────────────────────────────

    def _position_near_cursor(self):
        pt = POINT()
        user32.GetCursorPos(byref(pt))
        self.win.geometry(f"+{pt.x - 60}+{pt.y + 10}")

    # ── Clipboard ────────────────────────────────────────────────────

    def _paste_clipboard_into_textarea(self):
        text = clipboard_read()
        if text:
            self._clear_placeholder()
            self.text.delete("1.0", "end")
            self.text.insert("1.0", text)
            self._has_content = True
            self._redraw_status()

    def _copy_to_clipboard(self):
        text = self.get_text()
        if text:
            if clipboard_write(text):
                self.set_status_line("已复制，可贴入 Cursor", self.CLR["success"])
            else:
                self.set_status_line("复制失败", self.CLR["error"])

    # ── About dialog ─────────────────────────────────────────────────

    def _show_about(self):
        import tkinter.messagebox as mb
        mb.showinfo(
            "关于 Cursor Bridge",
            "Cursor Bridge  v1.9\n\n"
            "中文剪贴板桥 — 解决 Cursor 编辑器\n"
            "中文粘贴乱码问题\n\n"
            "纯 stdlib 实现 · tkinter + ctypes\n"
            "GitHub: github.com/winter2815651645-collab/cursor-bridge",
            parent=self.win if self.win and self.win.winfo_exists() else self.root,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Main Application
# ═══════════════════════════════════════════════════════════════════════════

class App:
    """Orchestrates tray, popup, clipboard monitor, and hotkey."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("Cursor Bridge")

        # Global tkinter exception handler — write to debug log instead of
        # silently killing the process (pythonw has no console for stderr).
        def _tkerr(exc_type, exc_val, exc_tb):
            _log(f"tkinter unhandled: {''.join(traceback.format_exception(exc_type, exc_val, exc_tb))}")
        self.root.report_callback_exception = _tkerr

        self.popup = PopupWindow(self.root)

        # clipboard monitor state
        self._monitoring = True
        self._last_seen   = ""   # last raw clipboard text we saw
        self._last_written = ""  # last text we wrote to clipboard (dedup guard)

        # hotkey debounce
        self._hk_active = False

        # tray communication
        self._tq = queue.Queue()
        self._tray_hwnd = None
        thr = threading.Thread(target=_tray_thread_main, args=(self._tq,), daemon=True)
        thr.start()

        # wait for tray ready (max 3s)
        for _ in range(30):
            try:
                msg = self._tq.get(timeout=0.1)
                if msg[0] == "ready":
                    self._tray_hwnd = msg[1]
                    break
                elif msg[0] == "error":
                    print(f"[Cursor Bridge] 托盘初始化失败: {msg[1]}", file=sys.stderr)
                    break
            except queue.Empty:
                continue

        # start polling loops
        self._poll_clipboard()
        self._poll_hotkey()
        self._poll_tray()

    def run(self):
        self.root.mainloop()

    # ── Clipboard monitor (500ms poll) ───────────────────────────────

    def _poll_clipboard(self):
        if self._monitoring:
            try:
                cur = clipboard_read()
                if cur is not None and cur != self._last_seen:
                    self._last_seen = cur
                    if has_cjk(cur) and cur != self._last_written:
                        if clipboard_write(cur):
                            self._last_written = cur
                            _log(f"recovered+rewrote: {cur[:60]}")
                        else:
                            _log("rewrite failed")
            except Exception:
                _log(f"poll error: {traceback.format_exc()}")
        self.root.after(500, self._poll_clipboard)

    # ── Hotkey monitor (150ms poll, Win+Shift+V) ─────────────────────

    def _poll_hotkey(self):
        try:
            v = user32.GetAsyncKeyState(0x56) & 0x8000
            w = (user32.GetAsyncKeyState(0x5B) | user32.GetAsyncKeyState(0x5C)) & 0x8000
            s = user32.GetAsyncKeyState(0x10) & 0x8000
            active = bool(v and w and s)

            if active and not self._hk_active:
                self._do_hotkey()
            self._hk_active = active
        except Exception:
            pass
        self.root.after(150, self._poll_hotkey)

    def _do_hotkey(self):
        text = clipboard_read()
        if text and has_cjk(text):
            if clipboard_write(text):
                self._last_written = text
                if self.popup.is_visible():
                    self.popup.set_status_line("⚡ Win+Shift+V · 已处理", "#FF9800")

    # ── Tray events (200ms poll) ─────────────────────────────────────

    def _poll_tray(self):
        try:
            while True:
                evt = self._tq.get_nowait()
                if evt == "toggle_popup":
                    self.popup.toggle()
                elif evt == "show_popup":
                    self.popup.show()
                elif evt == "quit":
                    if self._tray_hwnd:
                        user32.PostMessageW(self._tray_hwnd, WM_DESTROY, 0, 0)
                        _log("发送 WM_DESTROY 到托盘线程")
                    self.root.after(300, self.root.destroy)
                    return
                elif evt == "about":
                    self.popup._show_about()
        except queue.Empty:
            pass
        self.root.after(200, self._poll_tray)


# ═══════════════════════════════════════════════════════════════════════════

def main():
    _log("=== Cursor Bridge v1.9 启动 ===")
    App().run()


if __name__ == "__main__":
    main()
