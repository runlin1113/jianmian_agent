"""上传与网络出口的边界校验（第 13.1 节风险表）。

上传：
- 用**魔数**校验真实类型，不听扩展名；
- 拒绝可执行/宏格式；限制大小、页数、解包后总大小（zip bomb）；
- 文件名只用于展示，落盘名随机化。

网络：
- 只允许 http/https + 80/443；
- 拒绝 localhost、私网 IPv4/IPv6、link-local、云 metadata 地址；
- 每一跳重定向都重新校验（防 DNS rebinding / 跳转绕过）。
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
    "instance-data",
}

BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost", ".home.arpa")

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443}

_UNSAFE_FILENAME = re.compile(r"[^\w.\-\u4e00-\u9fa5]")


class UploadRejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class UnsafeUrl(Exception):
    def __init__(self, message: str):
        super().__init__(message)


@dataclass
class UploadInfo:
    kind: str  # pdf | docx
    filename: str
    size: int
    stored_name: str


def detect_kind(data: bytes, filename: str) -> str:
    if data.startswith(PDF_MAGIC):
        return "pdf"
    if data.startswith(ZIP_MAGIC):
        lower = (filename or "").lower()
        if lower.endswith((".docx", ".zip", "")) or lower.endswith(".doc"):
            return "docx"
        raise UploadRejected("unsupported_type", "压缩包只接受 .docx 简历")
    if data.startswith(OLE_MAGIC):
        raise UploadRejected("legacy_binary", "旧版 .doc 请另存为 .docx 后再上传")
    raise UploadRejected("unsupported_type", "只接受 PDF 或 DOCX 文件")


def validate_upload(
    data: bytes,
    *,
    filename: str,
    max_bytes: int,
    max_uncompressed_bytes: int = 40 * 1024 * 1024,
) -> UploadInfo:
    if not data:
        raise UploadRejected("empty_file", "文件为空")
    if len(data) > max_bytes:
        raise UploadRejected("payload_too_large", f"文件超过 {max_bytes // (1024 * 1024)} MB 上限")
    lower = (filename or "").lower()
    if lower.endswith((".docm", ".dotm", ".exe", ".js", ".bat", ".cmd", ".ps1", ".sh", ".vbs")):
        raise UploadRejected("unsupported_type", "拒绝可执行文件与含宏格式")
    kind = detect_kind(data, filename)

    if kind == "docx":
        import io
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
                if "[Content_Types].xml" not in names:
                    raise UploadRejected("invalid_docx", "不是有效的 DOCX 包")
                total = sum(info.file_size for info in zf.infolist())
                if total > max_uncompressed_bytes:
                    raise UploadRejected("zip_bomb", "解包后体积异常，已拒绝")
                if any(n.lower().startswith("word/vbaproject") for n in names):
                    raise UploadRejected("macro_detected", "文档含宏，已拒绝")
                if any(n.startswith("/") or ".." in n for n in names):
                    raise UploadRejected("zip_slip", "压缩包路径异常，已拒绝")
        except zipfile.BadZipFile as exc:
            raise UploadRejected("invalid_docx", "DOCX 解包失败") from exc

    safe_name = _UNSAFE_FILENAME.sub("_", filename or "upload").replace("..", "_")[-80:]
    import secrets

    stored = f"{secrets.token_hex(8)}-{safe_name}"
    return UploadInfo(kind=kind, filename=safe_name, size=len(data), stored_name=stored)


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def assert_public_http_url(url: str, *, resolve: bool = True) -> str:
    """在真正发起请求前校验目标地址。"""
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrl("只允许 http/https")
    if parts.port not in ALLOWED_PORTS:
        raise UnsafeUrl("只允许 80/443 端口")
    host = (parts.hostname or "").strip().lower()
    if not host:
        raise UnsafeUrl("缺少主机名")
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_HOST_SUFFIXES):
        raise UnsafeUrl("拒绝本机/内网主机名")
    if host.startswith("[") or ":" in host:
        raise UnsafeUrl("拒绝 IPv6 直连")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and _is_blocked_ip(literal):
        raise UnsafeUrl("拒绝私网或保留地址")
    if resolve and literal is None:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise UnsafeUrl("域名无法解析") from exc
        for info in infos:
            addr = info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if _is_blocked_ip(ip):
                raise UnsafeUrl("域名解析到私网地址，已拒绝")
    return url
