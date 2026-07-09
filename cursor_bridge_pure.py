"""Pure-Python encoding recovery functions (no Win32 API).

Extracted from cursor_bridge.pyw so tests can run without Windows.
"""

import re

# ── CJK detection regex ────────────────────────────────────────────────────
CJK_RE = re.compile(
    r'[一-鿿'          # CJK Unified Ideographs
    r'㐀-䶿'           # CJK Extension A
    r'豈-﫿'           # CJK Compatibility
    r'　-〿'           # CJK Symbols
    r'＀-￯'           # Fullwidth Forms
    r'⺀-⻿'           # CJK Radicals
    r']'
)


def has_cjk(text: str) -> bool:
    """True if text contains CJK characters."""
    return bool(CJK_RE.search(text))


def recover_utf8_mojibake(text: str) -> str | None:
    """Detect if `text` looks like UTF-8 bytes misinterpreted as Latin-1,
    and recover the original CJK text. Returns None if not mojibake.

    Example: 'è¿è¡Œä¸­' → '运行中'
    """
    if not text or has_cjk(text):
        return None

    non_ascii = [c for c in text if ord(c) >= 128]
    if not non_ascii:
        return None
    latin1_high = sum(1 for c in non_ascii if 0xC0 <= ord(c) <= 0xFF)
    if latin1_high / len(non_ascii) < 0.3:
        return None

    try:
        raw = text.encode('latin-1')
        recovered = raw.decode('utf-8')
        if has_cjk(recovered):
            return recovered
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return None


def recover_utf8_in_utf16le(raw: bytes) -> str | None:
    """Recover text from raw CF_UNICODETEXT bytes that may contain
    UTF-8 data mis-stored as UTF-16LE.

    Pattern A — byte-expanded: each UTF-8 byte stored as a 16-bit char
    (non-zero even bytes, 0x00 odd bytes).
      Raw:  E6 00 8E 00 A7 00 E5 00 88 00 B6 00 ...
      Even: E6 8E A7 E5 88 B6 → UTF-8 decode → 控制

    Pattern B — raw UTF-8: no padding, just the UTF-8 stream verbatim.
      Raw:  41 6E 74 68 72 6F 70 69 63 20 41 50 49
      wstring_at interprets as UTF-16LE pairs → CJK mojibake (湁桴潲楰⁣偁I)
      Fix: decode raw bytes directly as UTF-8 → Anthropic API
    """
    if len(raw) < 2:
        return None

    # ── Pattern A: byte-expanded (alternating 0x00) ──
    odd_zeros = sum(1 for i in range(1, min(len(raw), 100), 2) if raw[i] == 0)
    odd_total = min(len(raw), 100) // 2
    even_nonzero = sum(1 for i in range(0, min(len(raw), 100), 2) if raw[i] != 0)
    even_total = (min(len(raw), 100) + 1) // 2

    if odd_total > 0 and odd_zeros / odd_total >= 0.8:
        if even_nonzero / even_total >= 0.5:
            extracted = bytes(raw[i] for i in range(0, len(raw), 2))
            extracted = extracted.rstrip(b'\x00')
            try:
                return extracted.decode('utf-8')
            except UnicodeDecodeError:
                pass
        return None

    # ── Pattern B: raw UTF-8 (no 0x00 alternation) ──
    raw_stripped = raw.rstrip(b'\x00')
    if raw_stripped:
        try:
            recovered = raw_stripped.decode('utf-8')
            if recovered.isascii():
                alpha_ratio = sum(c.isalpha() for c in recovered) / max(len(recovered), 1)
                if alpha_ratio > 0.5:
                    return recovered
        except UnicodeDecodeError:
            pass

    return None


# Backward-compatible aliases (used by tests)
_recover_utf8_mojibake = recover_utf8_mojibake
_recover_utf8_in_utf16le = recover_utf8_in_utf16le
