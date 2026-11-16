"""请求守卫：会话、CSRF、限流。

放在依赖里而不是全局中间件，是为了让 SSE 这类长连接不被缓冲，
同时保持"每个不安全请求都必须过一遍"的可见性。
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request

from ..domain import errors
from ..security.session import SessionSigner
from .middleware import SESSION_STATE_KEY

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
#: 长连接的连接成本按半个请求计，避免"打开页面就把额度打光"
SSE_PATHS = ("/events",)


def session_id(request: Request) -> str:
    sid = request.scope.get("state", {}).get(SESSION_STATE_KEY)
    if not sid:
        raise errors.DomainError("session_missing", "会话未初始化，请刷新页面", status=401)
    return sid


def make_rate_guard(limiter):
    async def guard(request: Request) -> None:
        sid = session_id(request)
        cost = 0.4 if any(request.url.path.endswith(p) for p in SSE_PATHS) else 1.0
        allowed, retry_after = limiter.allow(sid, cost=cost)
        if not allowed:
            raise errors.rate_limited(retry_after)
        # 匿名会话 + IP 双维度：防止同一 NAT 下的单个脚本刷穿
        allowed_ip, retry_ip = limiter.allow(f"ip:{client_ip(request)}", cost=cost * 0.3)
        if not allowed_ip:
            raise errors.rate_limited(retry_ip)

    return guard


def make_csrf_guard(signer: SessionSigner, header_name: str):
    async def guard(request: Request) -> None:
        if request.method in SAFE_METHODS:
            return
        sid = session_id(request)
        presented = request.headers.get(header_name)
        if not signer.verify_csrf(sid, presented):
            raise errors.DomainError(
                "csrf_failed",
                "请求校验失败，请刷新页面后重试",
                status=403,
            )
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin and not _same_origin(origin, request):
            raise errors.DomainError("origin_rejected", "请求来源不被允许", status=403)

    return guard


def client_ip(request: Request) -> str:
    """只信任链路上最后一跳（由反向代理写入）。

    没有可信代理时直接用连接地址；不解析任意数量的 x-forwarded-for，
    否则客户端可以伪造 IP 绕过限流。
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()[:45] or "unknown"
    client = request.client
    return (client.host if client else "unknown")[:45]


def _same_origin(origin: str, request: Request) -> bool:
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    if not parts.netloc:
        return False
    host = request.headers.get("host", "")
    return parts.netloc.lower() == host.lower()
