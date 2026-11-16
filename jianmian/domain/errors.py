"""领域错误与对外错误契约（第 12.1 节）。

错误统一包含 code / message / requestId / retryable；不把上游响应、堆栈或密钥回传用户。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DomainError(Exception):
    code: str
    message: str
    status: int = 422
    retryable: bool = False
    details: dict = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover - 仅调试用
        return f"{self.code}: {self.message}"

    def to_payload(self, request_id: str | None = None) -> dict:
        payload = {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "requestId": request_id,
            }
        }
        if self.details:
            payload["error"]["details"] = self.details
        return payload


# ---- 契约错误 (422) -------------------------------------------------------
def contract_error(message: str, **details) -> DomainError:
    return DomainError("contract_violation", message, status=422, details=details)


def unknown_module_type(module_type: str) -> DomainError:
    return DomainError(
        "unknown_module_type",
        f"未知模块类型：{module_type}",
        status=422,
        details={"moduleType": module_type},
    )


def unknown_field(module_type: str, field_name: str) -> DomainError:
    return DomainError(
        "unknown_field",
        f"模块 {module_type} 不存在字段 {field_name}",
        status=422,
        details={"moduleType": module_type, "field": field_name},
    )


def forbidden_operation(op: str) -> DomainError:
    return DomainError("operation_not_allowed", f"操作 {op} 不在允许闭集内", status=422)


def fact_protected(module_id: str, field_name: str, reason: str) -> DomainError:
    return DomainError(
        "fact_protected",
        f"字段 {field_name} 受事实保护，AI 不得改写：{reason}",
        status=422,
        details={"moduleId": module_id, "field": field_name, "reason": reason},
    )


# ---- 冲突 (409) -----------------------------------------------------------
def version_conflict(expected: int, actual: int) -> DomainError:
    return DomainError(
        "revision_conflict",
        "文档版本已变化，请在最新版本上重新生成提案",
        status=409,
        retryable=True,
        details={"expectedRevision": expected, "currentRevision": actual},
    )


def proposal_expired(proposal_id: str) -> DomainError:
    return DomainError(
        "proposal_expired",
        "提案已过期，请重新生成",
        status=409,
        details={"proposalId": proposal_id},
    )


# ---- 权限 (403/404) -------------------------------------------------------
def not_found(what: str) -> DomainError:
    return DomainError("not_found", f"{what} 不存在或已过期", status=404)


def forbidden(message: str = "无权访问该资源") -> DomainError:
    return DomainError("forbidden", message, status=403)


# ---- 上传 (413) -----------------------------------------------------------
def payload_too_large(message: str, **details) -> DomainError:
    return DomainError("payload_too_large", message, status=413, details=details)


# ---- 限流/预算 (429/402) --------------------------------------------------
def rate_limited(retry_after: int = 60) -> DomainError:
    return DomainError(
        "rate_limited",
        "请求过于频繁，请稍后再试",
        status=429,
        retryable=True,
        details={"retryAfter": retry_after},
    )


def budget_exhausted(message: str = "演示额度已用完") -> DomainError:
    return DomainError("budget_exhausted", message, status=429, retryable=False)


def upstream_unavailable(message: str = "模型服务暂时不可用") -> DomainError:
    return DomainError("upstream_unavailable", message, status=503, retryable=True)
