"""Tests for Cursor Bridge encoding recovery functions.

These tests only exercise the pure-Python encoding logic — no Win32 API calls.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cursor_bridge_pure import (
    has_cjk,
    _recover_utf8_mojibake,
    _recover_utf8_in_utf16le,
)


class TestHasCJK:
    """CJK detection tests."""

    def test_chinese(self):
        assert has_cjk("你好世界")

    def test_japanese(self):
        # Japanese kanji (CJK ideographs) detected; pure kana are not
        assert has_cjk("日本語")  # 日 and 本 are CJK, 語 is CJK

    def test_korean(self):
        # Korean hanja (CJK ideographs) detected; pure hangul is not
        assert has_cjk("大韓民國")  # all CJK

    def test_ascii_only(self):
        assert not has_cjk("Hello World")

    def test_ascii_with_numbers(self):
        assert not has_cjk("test 123 ABC")

    def test_mixed_cjk_ascii(self):
        assert has_cjk("Hello 世界")

    def test_empty(self):
        assert not has_cjk("")


class TestRecoverUtf8Mojibake:
    """Latin-1 → UTF-8 mojibake recovery."""

    def test_chinese_mojibake(self):
        # "运行中" encoded as UTF-8 then decoded as Latin-1
        text = "运行中".encode('utf-8').decode('latin-1')
        result = _recover_utf8_mojibake(text)
        assert result == "运行中"

    def test_already_valid_cjk(self):
        # Should return None when text is already valid CJK
        result = _recover_utf8_mojibake("你好世界")
        assert result is None

    def test_ascii_text(self):
        result = _recover_utf8_mojibake("Hello World")
        assert result is None

    def test_empty_text(self):
        result = _recover_utf8_mojibake("")
        assert result is None

    def test_garbled_text(self):
        # Chinese text → UTF-8 → mis-decoded as Latin-1 → should recover
        mojibake = "运行中".encode('utf-8').decode('latin-1')
        result = _recover_utf8_mojibake(mojibake)
        assert result == "运行中"


class TestRecoverUtf8InUtf16LE:
    """Pattern A + Pattern B recovery from raw CF_UNICODETEXT bytes."""

    # ── Pattern A: byte-expanded UTF-8 ──

    def test_pattern_a_chinese(self):
        # Simulate: "控制" → UTF-8 bytes → each byte as 16-bit LE char
        utf8 = "控制".encode('utf-8')  # e6 8e a7 e5 88 b6
        raw = bytes(b for byte in utf8 for b in (byte, 0))  # e6 00 8e 00 ...
        result = _recover_utf8_in_utf16le(raw)
        assert result == "控制"

    def test_pattern_a_ascii_alternating(self):
        # "abc" → UTF-8 bytes → expanded
        utf8 = "abc".encode('utf-8')
        raw = bytes(b for byte in utf8 for b in (byte, 0))
        result = _recover_utf8_in_utf16le(raw)
        assert result == "abc"

    # ── Pattern B: raw UTF-8 in CF_UNICODETEXT ──

    def test_pattern_b_english(self):
        # "Anthropic API" → UTF-8 bytes → dumped directly into CF_UNICODETEXT
        raw = "Anthropic API".encode('utf-8')
        result = _recover_utf8_in_utf16le(raw)
        assert result == "Anthropic API"

    def test_pattern_b_code_keywords(self):
        raw = "function import return class".encode('utf-8')
        result = _recover_utf8_in_utf16le(raw)
        assert result == "function import return class"

    # ── Edge cases ──

    def test_empty_bytes(self):
        result = _recover_utf8_in_utf16le(b'')
        assert result is None

    def test_single_byte(self):
        result = _recover_utf8_in_utf16le(b'A')
        assert result is None

    def test_short_utf16le_not_expanded(self):
        # "Hi" in proper UTF-16LE: H\x00i\x00
        raw = "Hi".encode('utf-16-le')
        # Pattern A check: odd bytes are 0x00 (true), even bytes H,i non-zero (true)
        # → would decode "Hi" as UTF-8 → "Hi"
        result = _recover_utf8_in_utf16le(raw)
        assert result == "Hi"

    def test_proper_utf16le_cjk_not_mistriggered(self):
        # "你好" in proper UTF-16LE — should NOT match Pattern B
        # because its bytes don't form valid ASCII UTF-8
        raw = "你好".encode('utf-16-le')
        result = _recover_utf8_in_utf16le(raw)
        assert result is None  # 4f60 597d → bytes 60 4F 7D 59 → non-ASCII in UTF-8 decode
