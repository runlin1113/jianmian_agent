"""匿名签名会话（第 13.1 节）。

CORS 只约束浏览器，不是身份认证。因此：
- 会话 ID 由服务端签名，浏览器无法伪造他人 sid；
- Cookie 使用 HttpOnly + SameSite=Lax（HTTPS 下加 Secure）；
- 匿名会话**不是**简历云账号：简历正文默认不出浏览器。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


class SessionSigner:
    def __init__(self, secret: str) -> None:
        self._secret = secret.encode("utf-8")

    def _sig(self, session_id: str) -> str:
        return hmac.new(self._secret, session_id.encode("utf-8"), hashlib.sha256).hexdigest()[:32]

    def new_session(self) -> tuple[str, str]:
        session_id = "s-" + secrets.token_urlsafe(18)
        return session_id, self.token(session_id)

    def token(self, session_id: str) -> str:
        return f"{session_id}.{self._sig(session_id)}"

    def verify(self, token: str | None) -> str | None:
        if not token or "." not in token:
            return None
        session_id, _, sig = token.rpartition(".")
        if not session_id.startswith("s-") or len(session_id) > 64:
            return None
        if hmac.compare_digest(self._sig(session_id), sig):
            return session_id
        return None

    # ---- CSRF：双提交令牌，与 sid 绑定 -----------------------------------
    def csrf_token(self, session_id: str) -> str:
        return hmac.new(self._secret, f"csrf:{session_id}".encode("utf-8"), hashlib.sha256).hexdigest()[:40]

    def verify_csrf(self, session_id: str, presented: str | None) -> bool:
        if not presented:
            return False
        return hmac.compare_digest(self.csrf_token(session_id), presented)


def cookie_flags(secure: bool) -> dict:
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
        "path": "/",
    }
