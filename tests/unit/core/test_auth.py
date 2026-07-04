"""Tests for core/auth.py — TenantContext + pure functions."""

import pytest
from ragnexus.core.auth import TenantContext, hash_key, extract_token


class TestHashKey:
    def test_produces_64_hex_chars(self):
        """SHA-256 输出固定 64 字符十六进制。"""
        result = hash_key("test_key")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self):
        """相同输入产生相同哈希。"""
        assert hash_key("abc") == hash_key("abc")

    def test_different_inputs_produce_different_hashes(self):
        """不同输入产生不同哈希。"""
        assert hash_key("abc") != hash_key("abd")


class TestExtractToken:
    def test_valid_bearer_token(self):
        assert extract_token("Bearer abc123") == "abc123"

    def test_none_header(self):
        assert extract_token(None) is None

    def test_empty_header(self):
        assert extract_token("") is None

    def test_wrong_scheme(self):
        assert extract_token("Basic dXNlcjpwYXNz") is None

    def test_extra_parts(self):
        assert extract_token("Bearer a b") is None

    def test_lowercase_bearer(self):
        """大小写不敏感。"""
        assert extract_token("bearer abc") == "abc"


class TestTenantContext:
    def test_fields(self):
        ctx = TenantContext(
            tenant_id="t1",
            tenant_name="测试",
            key_id="uuid-1",
            key_prefix="rk_a1b2",
        )
        assert ctx.tenant_id == "t1"
        assert ctx.tenant_name == "测试"
        assert ctx.key_id == "uuid-1"
        assert ctx.key_prefix == "rk_a1b2"
