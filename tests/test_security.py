"""安全层测试：会话、CSRF、限流、上传边界、SSRF、脱敏。

这些是"公网部署前必须为真"的命题，不依赖任何模型行为。
"""

from __future__ import annotations

import io
import time
import zipfile

import pytest

from jianmian.security.limits import TokenBucketLimiter
from jianmian.security.net import (
    UnsafeUrl,
    UploadRejected,
    assert_public_http_url,
    detect_kind,
    validate_upload,
)
from jianmian.security.redaction import redact, redact_mapping
from jianmian.security.session import SessionSigner

PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def make_docx(*, with_macro: bool = False, extra: dict[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        if with_macro:
            archive.writestr("word/vbaProject.bin", b"\x00" * 32)
        for name, payload in (extra or {}).items():
            archive.writestr(name, payload)
    return buffer.getvalue()


# ------------------------------------------------------------------ 会话
def test_session_roundtrip_and_tamper():
    signer = SessionSigner("secret-a")
    sid, token = signer.new_session()
    assert signer.verify(token) == sid
    # 篡改 sid 或签名都要失败，不能"解出个新会话"
    assert signer.verify(token.replace(sid, "s-attacker")) is None
    assert signer.verify(sid + ".deadbeef") is None
    assert signer.verify(None) is None
    assert signer.verify("not-a-token") is None


def test_csrf_token_is_bound_to_session():
    signer = SessionSigner("secret-b")
    sid_a, _ = signer.new_session()
    sid_b, _ = signer.new_session()
    token = signer.csrf_token(sid_a)
    assert signer.verify_csrf(sid_a, token)
    assert not signer.verify_csrf(sid_b, token)
    assert not signer.verify_csrf(sid_a, None)
    assert not signer.verify_csrf(sid_a, token[:-1] + "x")


# ------------------------------------------------------------------ 限流
def test_token_bucket_blocks_after_burst_then_refills():
    limiter = TokenBucketLimiter(per_minute=60, burst=3)
    now = 1000.0
    allowed = [limiter.allow("s-1", now=now + i * 0.001)[0] for i in range(3)]
    assert all(allowed)
    blocked, retry_after = limiter.allow("s-1", now=now + 0.01)
    assert not blocked and retry_after >= 1
    # 60 秒后恢复
    assert limiter.allow("s-1", now=now + 61)[0]
    # 不同主体互不影响（校园 NAT 共用 IP 时靠会话区分）
    assert limiter.allow("s-2", now=now + 0.01)[0]


# ------------------------------------------------------------------ 上传
def test_detect_kind_by_magic_bytes_not_extension():
    assert detect_kind(PDF_BYTES, "resume.pdf") == "pdf"
    assert detect_kind(make_docx(), "resume.docx") == "docx"
    with pytest.raises(UploadRejected):
        detect_kind(b"#!/bin/sh\nrm -rf /", "resume.pdf")
    with pytest.raises(UploadRejected):
        detect_kind(b"MZ\x90\x00", "resume.docx")


def test_upload_rejects_legacy_doc_and_office_macros():
    with pytest.raises(UploadRejected) as legacy:
        validate_upload(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64, filename="old.doc", max_bytes=1024 * 1024)
    assert legacy.value.code == "legacy_binary"

    with pytest.raises(UploadRejected) as macro:
        validate_upload(make_docx(with_macro=True), filename="evil.docx", max_bytes=1024 * 1024)
    assert macro.value.code == "macro_detected"


def test_upload_rejects_zip_slip_and_zip_bomb():
    with pytest.raises(UploadRejected) as slip:
        validate_upload(make_docx(extra={"../evil.xml": b"x"}), filename="x.docx", max_bytes=1024 * 1024)
    assert slip.value.code == "zip_slip"

    bomb = make_docx(extra={"word/big.xml": b"a" * (1024 * 1024)})
    with pytest.raises(UploadRejected) as too_big:
        validate_upload(bomb, filename="bomb.docx", max_bytes=8 * 1024 * 1024, max_uncompressed_bytes=1024)
    assert too_big.value.code == "zip_bomb"


def test_upload_rejects_oversize_and_empty():
    with pytest.raises(UploadRejected) as big:
        validate_upload(PDF_BYTES * 100, filename="a.pdf", max_bytes=100)
    assert big.value.code == "payload_too_large"
    with pytest.raises(UploadRejected):
        validate_upload(b"", filename="a.pdf", max_bytes=1000)


def test_upload_sanitizes_filename():
    info = validate_upload(PDF_BYTES, filename="../../etc/passwd.pdf", max_bytes=1024 * 1024)
    assert "/" not in info.stored_name and "\\" not in info.stored_name
    assert ".." not in info.stored_name


# ------------------------------------------------------------------ SSRF
def test_ssrf_blocks_private_and_non_http_targets():
    for url in (
        "http://127.0.0.1/admin",
        "http://localhost:8000/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://[::1]/",
    ):
        with pytest.raises(UnsafeUrl):
            assert_public_http_url(url, resolve=False)


def test_ssrf_allows_normal_public_url():
    assert assert_public_http_url("https://example.com/jobs/1", resolve=False).startswith("https://")


# ------------------------------------------------------------------ 脱敏
def test_redaction_hides_keys_phones_emails():
    text = "key=sk-abcdefgh12345678 手机 13800138000 邮箱 a@b.com"
    masked = redact(text)
    assert "sk-abcdefgh" not in masked
    assert "13800138000" not in masked
    assert "a@b.com" not in masked
    assert "[REDACTED_KEY]" in masked


def test_redact_mapping_hides_secret_fields():
    payload = {"apiKey": "sk-1234567890", "nested": {"authorization": "Bearer abcdefgh"}, "note": "ok"}
    masked = redact_mapping(payload)
    assert masked["apiKey"] == "[REDACTED]"
    assert masked["nested"]["authorization"] == "[REDACTED]"
    assert masked["note"] == "ok"
