"""不透明 ID 生成。随机 ID 不等于授权：所有权校验在应用层做。"""

from __future__ import annotations

import secrets


def opaque_id(prefix: str, nbytes: int = 8) -> str:
    return f"{prefix}-{secrets.token_hex(nbytes)}"


def request_id() -> str:
    return "req-" + secrets.token_hex(8)


def idempotency_digest(payload: str, secret: str) -> str:
    """服务端不落请求正文时，用带密钥的 HMAC 摘要比较同键不同内容。"""
    import hashlib
    import hmac

    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
