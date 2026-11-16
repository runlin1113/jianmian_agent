"""HTTP 中间件（纯 ASGI，避免 BaseHTTPMiddleware 缓冲 SSE）。

- `SessionMiddleware`：匿名签名会话。新会话在响应上补 Set-Cookie；
- `SecurityHeadersMiddleware`：CSP / nosniff / frame-ancestors。
  CSP 允许同源脚本与内联样式（首版为了保持单页可读性），
  但把 connect-src 限制到 'self'，不允许任意外联。
"""

from __future__ import annotations

from http.cookies import SimpleCookie

from ..security.session import SessionSigner

SESSION_STATE_KEY = "jm_sid"


class SessionMiddleware:
    def __init__(self, app, *, signer: SessionSigner, cookie_name: str, secure: bool) -> None:
        self.app = app
        self.signer = signer
        self.cookie_name = cookie_name
        self.secure = secure

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        sid = self._read_session(scope)
        issued = None
        if sid is None:
            sid, issued = self.signer.new_session()

        state = scope.setdefault("state", {})
        state[SESSION_STATE_KEY] = sid

        if issued is None:
            return await self.app(scope, receive, send)

        async def send_with_cookie(message):
            if message["type"] == "http.response.start":
                raw = f"{self.cookie_name}={issued}; Path=/; HttpOnly; SameSite=Lax"
                if self.secure:
                    raw += "; Secure"
                headers = list(message.get("headers") or [])
                headers.append((b"set-cookie", raw.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cookie)

    def _read_session(self, scope) -> str | None:
        for key, value in scope.get("headers") or []:
            if key == b"cookie":
                cookie = SimpleCookie()
                try:
                    cookie.load(value.decode("latin-1"))
                except Exception:
                    return None
                morsel = cookie.get(self.cookie_name)
                if morsel is not None:
                    return self.signer.verify(morsel.value)
        return None


class SecurityHeadersMiddleware:
    def __init__(self, app, *, csp: str) -> None:
        self.app = app
        self.csp = csp

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapped(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.extend(
                    [
                        (b"content-security-policy", self.csp.encode("latin-1")),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (b"permissions-policy", b"geolocation=(), microphone=(), camera=()"),
                        (b"cross-origin-opener-policy", b"same-origin"),
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapped)


class RequestIdMiddleware:
    """给每个请求一个可追踪的 id，并回写到响应头。

    用纯 ASGI 实现而不是 BaseHTTPMiddleware，避免缓冲流式响应（SSE）。
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from ..security.ids import request_id as new_id

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        rid = (headers.get("x-request-id") or new_id())[:64]
        scope.setdefault("state", {})["request_id"] = rid

        async def send_wrapped(message):
            if message["type"] == "http.response.start":
                out = list(message.get("headers") or [])
                out.append((b"x-request-id", rid.encode("latin-1")))
                message = {**message, "headers": out}
            await send(message)

        await self.app(scope, receive, send_wrapped)


def build_csp(*, allow_inline_style: bool = True) -> str:
    style = "'self' 'unsafe-inline'" if allow_inline_style else "'self'"
    return (
        "default-src 'self'; "
        f"style-src {style}; "
        "script-src 'self'; "
        "img-src 'self' data: blob:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
