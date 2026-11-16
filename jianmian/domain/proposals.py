"""修改提案：闭集操作 + 原子应用（第 10 章）。

契约要点：
- 操作集合是**闭集**，不存在 "run_js" / "patch_json_pointer" 这类通用通道；
- 工具返回值不允许夹带可执行 JS、模板 HTML、CSS 或任意 JSON Pointer；
- 一批操作要么全部写入，要么一个字段都不写（先在副本上演练）；
- `baseRevision` / `baseHash` / `expiresAt` 三重校验防止旧提案覆盖新内容。
"""

from __future__ import annotations

import copy
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import errors
from .facts import GuardResult, TokenSet, check_guarded_rewrite
from .modules import get_spec
from .resume import ResumeDocument, add_module, change_appearance, remove_module, replace_field, reorder_modules

OP_ADD_MODULE = "add_module"
OP_REPLACE_FIELD = "replace_field"
OP_REMOVE_MODULE = "remove_module"
OP_REORDER = "reorder_modules"
OP_APPEARANCE = "change_appearance"

ALLOWED_OPS = frozenset({OP_ADD_MODULE, OP_REPLACE_FIELD, OP_REMOVE_MODULE, OP_REORDER, OP_APPEARANCE})

#: 默认所有工具都没有删除/排序权限；只有显式声明后才可下发（第 10.1 节）
DESTRUCTIVE_OPS = frozenset({OP_REMOVE_MODULE, OP_REORDER})

_HTML_TAG = re.compile(r"<\s*/?\s*[a-zA-Z!]", re.IGNORECASE)
_JS_URL = re.compile(r"(javascript|data:text/html|vbscript)\s*:", re.IGNORECASE)
_EVENT_ATTR = re.compile(r"\bon[a-z]+\s*=", re.IGNORECASE)
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def assert_plain_text(value: str, *, where: str = "text") -> str:
    """拒绝可执行内容。允许普通数学符号，但拒绝标签、事件属性与伪协议。"""
    if not isinstance(value, str):
        raise errors.contract_error(f"{where} 必须是字符串")
    if _CTRL.search(value):
        raise errors.contract_error(f"{where} 含控制字符")
    if _HTML_TAG.search(value):
        raise errors.contract_error(f"{where} 不允许包含 HTML 标签")
    if _JS_URL.search(value):
        raise errors.contract_error(f"{where} 不允许包含可执行 URL")
    if _EVENT_ATTR.search(value):
        raise errors.contract_error(f"{where} 不允许包含事件属性")
    return value


class _OpBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = ""


class AddModuleOp(_OpBase):
    op: Literal["add_module"] = OP_ADD_MODULE
    moduleType: str
    data: dict[str, str] = Field(default_factory=dict)
    position: int | None = None
    moduleId: str | None = None

    @field_validator("data")
    @classmethod
    def _clean(cls, data: dict[str, str]) -> dict[str, str]:
        for k, v in data.items():
            assert_plain_text(k, where="字段名")
            assert_plain_text(str(v), where=f"字段 {k}")
        return data


class ReplaceFieldOp(_OpBase):
    op: Literal["replace_field"] = OP_REPLACE_FIELD
    moduleId: str
    field: str
    before: str = ""
    after: str
    factIds: list[str] = Field(default_factory=list)

    @field_validator("after", "before")
    @classmethod
    def _clean(cls, v: str) -> str:
        return assert_plain_text(v, where="字段内容")


class RemoveModuleOp(_OpBase):
    op: Literal["remove_module"] = OP_REMOVE_MODULE
    moduleId: str


class ReorderOp(_OpBase):
    op: Literal["reorder_modules"] = OP_REORDER
    order: list[str]

    @field_validator("order")
    @classmethod
    def _unique(cls, order: list[str]) -> list[str]:
        if len(set(order)) != len(order):
            raise ValueError("排序列表含重复 ID")
        return order


class AppearanceOp(_OpBase):
    op: Literal["change_appearance"] = OP_APPEARANCE
    changes: dict[str, Any]


Operation = Annotated[
    Union[AddModuleOp, ReplaceFieldOp, RemoveModuleOp, ReorderOp, AppearanceOp],
    Field(discriminator="op"),
]


class ChangeProposal(BaseModel):
    """AI 建议的修改集合。它不等于已应用的修改。"""

    model_config = ConfigDict(extra="forbid")

    proposalId: str = Field(default_factory=lambda: "p-" + secrets.token_hex(4))
    resumeId: str
    baseRevision: int
    baseHash: str
    intent: str = "edit"
    summary: str = ""
    operations: list[Operation] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expiresAt: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(minutes=30)
    )

    def is_expired(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        expires = self.expiresAt
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now >= expires

    def op_summary(self) -> list[dict]:
        out = []
        for op in self.operations:
            entry: dict[str, Any] = {"op": op.op}
            if isinstance(op, ReplaceFieldOp):
                entry.update(
                    moduleId=op.moduleId,
                    field=op.field,
                    before=op.before,
                    after=op.after,
                )
            elif isinstance(op, AddModuleOp):
                # 带上字段内容：用户要能在采纳前看到"到底会加进去什么"，
                # 只写"新增模块：项目经历"等于让人盲签
                entry.update(
                    moduleType=op.moduleType,
                    title=(op.data or {}).get("proj_name") or op.moduleType,
                    data={k: v for k, v in (op.data or {}).items() if str(v).strip()},
                )
            elif isinstance(op, RemoveModuleOp):
                entry.update(moduleId=op.moduleId)
            elif isinstance(op, ReorderOp):
                entry.update(order=op.order)
            elif isinstance(op, AppearanceOp):
                entry.update(changes=op.changes)
            entry["reason"] = op.reason
            out.append(entry)
        return out


class ApplyOutcome(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    document: ResumeDocument
    applied: list[dict]
    warnings: list[dict]
    guard: list[dict]


def _differs(a: str, b: str) -> bool:
    return (a or "").strip() != (b or "").strip()


def apply_proposal(
    doc: ResumeDocument,
    proposal: ChangeProposal,
    *,
    actor: Literal["human", "ai"] = "ai",
    allowed_tokens: TokenSet | None = None,
    permit_destructive: bool = True,
    now: datetime | None = None,
) -> ApplyOutcome:
    """原子应用提案。

    任何一步失败 → 抛出 DomainError，调用方手里的文档保持原样（不做部分写入）。
    """
    if proposal.is_expired(now):
        raise errors.proposal_expired(proposal.proposalId)
    if proposal.baseRevision != doc.revision:
        raise errors.version_conflict(proposal.baseRevision, doc.revision)
    if proposal.baseHash and proposal.baseHash != doc.content_hash():
        raise errors.version_conflict(proposal.baseRevision, doc.revision)

    work = ResumeDocument.model_validate(copy.deepcopy(doc.model_dump()))
    applied: list[dict] = []
    warnings: list[dict] = list(proposal.warnings)
    guards: list[dict] = []

    for index, op in enumerate(proposal.operations):
        if op.op not in ALLOWED_OPS:  # 理论上被 discriminator 拦住，保留兜底
            raise errors.forbidden_operation(str(op.op))
        if op.op in DESTRUCTIVE_OPS and not permit_destructive:
            raise errors.forbidden_operation(op.op)

        if isinstance(op, ReplaceFieldOp):
            mod = work.require_module(op.moduleId)
            spec = get_spec(mod.type)
            fspec = spec.field(op.field)
            if fspec is None:
                raise errors.unknown_field(mod.type, op.field)
            current = mod.data.get(op.field, "")
            if _differs(current, op.before):
                # 生成期间用户改了这一格：不允许覆盖
                raise errors.version_conflict(proposal.baseRevision, doc.revision)
            if fspec.policy == "guarded":
                guard = check_guarded_rewrite(
                    current, op.after, allowed_tokens=allowed_tokens, fact_ids=op.factIds
                )
                guards.append({"op": index, "moduleId": op.moduleId, "field": op.field, **guard.as_dict()})
                if not guard.ok:
                    raise errors.DomainError(
                        "fact_guard_failed",
                        f"字段「{op.field}」的改写触碰事实保护",
                        status=422,
                        details=guard.as_dict(),
                    )
                warnings.extend(v.as_dict() for v in guard.warnings)
            work = replace_field(work, op.moduleId, op.field, op.after, actor=actor)
            applied.append(
                {
                    "op": op.op,
                    "moduleId": op.moduleId,
                    "field": op.field,
                    "before": current,
                    "after": op.after,
                }
            )
        elif isinstance(op, AddModuleOp):
            work = add_module(
                work,
                op.moduleType,
                op.data,
                position=op.position,
                module_id=op.moduleId,
            )
            applied.append({"op": op.op, "moduleType": op.moduleType, "moduleId": op.moduleId})
        elif isinstance(op, RemoveModuleOp):
            work = remove_module(work, op.moduleId)
            applied.append({"op": op.op, "moduleId": op.moduleId})
        elif isinstance(op, ReorderOp):
            work = reorder_modules(work, op.order)
            applied.append({"op": op.op, "order": op.order})
        elif isinstance(op, AppearanceOp):
            work = change_appearance(work, op.changes)
            applied.append({"op": op.op, "changes": op.changes})

    # 整批只推进一个版本：逐条 +1 会让"一次确认"看起来像改了很多次
    work.revision = doc.revision + 1
    for idx, mod in enumerate(work.sorted_modules()):
        mod.order = idx

    return ApplyOutcome(document=work, applied=applied, warnings=warnings, guard=guards)


def validate_proposal_payload(payload: dict[str, Any]) -> ChangeProposal:
    """客户端/模型返回值统一从这里进领域层。"""
    if not isinstance(payload, dict):
        raise errors.contract_error("提案必须是对象")
    raw_ops = payload.get("operations")
    if raw_ops is not None and not isinstance(raw_ops, list):
        raise errors.contract_error("operations 必须是数组")
    for op in raw_ops or []:
        if not isinstance(op, dict):
            raise errors.contract_error("operation 必须是对象")
        if op.get("op") not in ALLOWED_OPS:
            raise errors.forbidden_operation(str(op.get("op")))
        for key in op:
            if key in {"__proto__", "constructor", "prototype"}:
                raise errors.contract_error(f"非法字段名：{key}")
    return ChangeProposal.model_validate(payload)


def guard_result_to_warnings(result: GuardResult) -> list[dict]:
    return [v.as_dict() for v in result.warnings]
