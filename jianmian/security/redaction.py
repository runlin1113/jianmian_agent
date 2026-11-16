"""日志与诊断包脱敏。

原则：Key 不出现在文档、历史、URL、遥测与模型 prompt 里；日志只记元数据。
"""

from __future__ import annotations

import re
from typing import Any

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(sk-[A-Za-z0-9_\-]{8,})"), "[REDACTED_KEY]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(api[_-]?key\"?\s*[:=]\s*\"?)([^\"\s,}]{6,})"), r"\1[REDACTED]"),
    (re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)"), "[REDACTED_PHONE]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[REDACTED_EMAIL]"),
)


def redact(text: str) -> str:
    out = text or ""
    for pattern, repl in _SECRET_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def redact_mapping(data: dict[str, Any], *, depth: int = 0) -> dict[str, Any]:
    if depth > 4:
        return {"_truncated": True}
    out: dict[str, Any] = {}
    for key, value in data.items():
        lower = str(key).lower()
        if lower in {"apikey", "api_key", "authorization", "password", "secret", "token"}:
            out[key] = "[REDACTED]"
        elif isinstance(value, str):
            out[key] = redact(value)
        elif isinstance(value, dict):
            out[key] = redact_mapping(value, depth=depth + 1)
        elif isinstance(value, list):
            out[key] = [redact(v) if isinstance(v, str) else v for v in value[:25]]
        else:
            out[key] = value
    return out


def safe_error_detail(exc: BaseException) -> str:
    """只暴露异常类型，避免把上游响应、堆栈或密钥带出去。"""
    return f"{type(exc).__name__}"
