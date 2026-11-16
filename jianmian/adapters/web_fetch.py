"""受控网页抓取（M10 联网档）。

先用例：用户粘贴 JD 链接时，抓取正文作为**证据材料**。
安全要求（第 13.1 节）：
- 只允许 http/https + 80/443，拒绝私网、回环、云 metadata 与解析到私网的域名；
- 每一跳重定向都重新校验（防 DNS rebinding / 跳转绕过）；
- 限制响应体积与超时，只接受文本类型；
- 网页内容是数据，不是系统指令（提示词层再做一次隔离标注）。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

from ..domain.jobs import JobEvidence
from ..security.net import UnsafeUrl, assert_public_http_url

MAX_BYTES = 512 * 1024
MAX_REDIRECTS = 3
ALLOWED_CONTENT_TYPES = ("text/html", "text/plain", "application/xhtml")

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")


def html_to_text(html: str) -> str:
    text = _SCRIPT_RE.sub(" ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)>", "\n", text)
    text = _TAG_RE.sub(" ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    lines = [_WS_RE.sub(" ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


class JdUrlFetcher:
    name = "safe-web-fetch"
    isRemote = True

    def __init__(self, *, timeout: float = 8.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._timeout = timeout
        self._transport = transport

    async def fetch(self, url: str, *, max_redirects: int = MAX_REDIRECTS) -> JobEvidence:
        current = url
        async with httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
            follow_redirects=False,
            headers={"User-Agent": "JianMianBot/0.1 (resume demo; contact: local)"},
        ) as client:
            for _ in range(max_redirects + 1):
                try:
                    assert_public_http_url(current)
                except UnsafeUrl as exc:
                    raise UnsafeUrl(f"地址不被允许：{exc}") from exc
                resp = await client.get(current)
                if resp.status_code in {301, 302, 303, 307, 308}:
                    location = resp.headers.get("location")
                    if not location:
                        raise UnsafeUrl("重定向缺少 Location")
                    current = str(httpx.URL(current).join(location))
                    continue
                if resp.status_code >= 400:
                    raise UnsafeUrl(f"抓取失败：HTTP {resp.status_code}")
                ctype = (resp.headers.get("content-type") or "").lower()
                if not any(ctype.startswith(t) for t in ALLOWED_CONTENT_TYPES):
                    raise UnsafeUrl("只接受文本类网页")
                raw = resp.content[:MAX_BYTES]
                html = raw.decode(resp.encoding or "utf-8", errors="replace")
                text = html_to_text(html)
                title = _extract_title(html) or current
                return JobEvidence(
                    id="web-" + str(abs(hash(current)) % 10**8),
                    role=title[:60],
                    city="",
                    seniority="",
                    skills=_guess_skills(text),
                    description=text[:4000],
                    sourceUrl=current,
                    sourceName=httpx.URL(current).host or "",
                    fetchedAt=datetime.now(timezone.utc),
                    publishedAt=None,
                    isSample=False,
                )
        raise UnsafeUrl("重定向次数超限")


def _extract_title(html: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    return _WS_RE.sub(" ", _TAG_RE.sub("", m.group(1))).strip() if m else ""


def _guess_skills(text: str) -> list[str]:
    from .model_mock import detect_skills

    return detect_skills(text)[:10]


class RemoteSearchProvider:
    """受控搜索 API 占位实现。

    未配置 `JIANMIAN_SEARCH_ENDPOINT` 时 `available=False`，岗位服务会退回本地样本
    并显式告知"本次未联网"，而不是假装查过市场。
    """

    name = "remote-search"
    isRemote = True

    def __init__(self, endpoint: str | None = None, api_key: str | None = None, transport=None) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._transport = transport
        self.available = bool(endpoint)

    async def search(self, *, role: str, city: str = "", seniority: str = "", limit: int = 5) -> list[JobEvidence]:
        if not self.available:
            return []
        try:
            assert_public_http_url(self._endpoint or "")
        except UnsafeUrl:
            return []
        async with httpx.AsyncClient(timeout=8.0, transport=self._transport) as client:
            resp = await client.get(
                self._endpoint,
                params={"q": role, "city": city, "seniority": seniority, "limit": limit},
                headers={"Authorization": f"Bearer {self._api_key}"} if self._api_key else {},
            )
        if resp.status_code >= 400:
            return []
        payload = resp.json()
        entries = payload.get("results", []) if isinstance(payload, dict) else []
        out: list[JobEvidence] = []
        for entry in entries[:limit]:
            if not isinstance(entry, dict):
                continue
            out.append(
                JobEvidence(
                    id=str(entry.get("id") or f"remote-{len(out)}"),
                    role=str(entry.get("role") or role),
                    city=str(entry.get("city") or city),
                    seniority=str(entry.get("seniority") or ""),
                    skills=[str(s) for s in entry.get("skills", [])][:15],
                    description=str(entry.get("description") or "")[:4000],
                    sourceUrl=str(entry.get("url") or ""),
                    sourceName=str(entry.get("source") or "受控搜索"),
                    isSample=False,
                )
            )
        return out
