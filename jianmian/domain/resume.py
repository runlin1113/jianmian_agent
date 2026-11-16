"""简历主文档与确定性命令（M1 编辑引擎的领域部分）。

设计要点：
- `ResumeDocument` 是**唯一**的简历主数据形状；编排层的 state 只是工作副本，
  不构成第二份可独立编辑的简历（第 5 章）。
- 所有写入都走命令函数，命令返回新文档（copy-on-write），并递增 `revision`。
- `content_hash` 只覆盖内容，不覆盖 `revision`，因此"原值未变但版本变了"可被区分出来。
"""

from __future__ import annotations

import copy
import hashlib
import json
import secrets
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .. import SCHEMA_VERSION
from .errors import (
    contract_error,
    fact_protected,
    forbidden_operation,
    unknown_field,
    unknown_module_type,
)
from .modules import (
    DEFAULT_APPEARANCE,
    MODULE_SPECS,
    THEMES,
    TEMPLATES,
    empty_data,
    get_spec,
    module_title,
)

DANGEROUS_KEYS = frozenset({"__proto__", "constructor", "prototype"})


class Appearance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str = "executive"
    theme: str = "navy"
    density: Literal["concise", "balanced", "detailed"] = "balanced"
    #: 前端只读回传的测量结果，服务端不据此决定计费/权限（第 9.4 节）
    zoom: float = Field(default=0.75, ge=0.4, le=1.5)

    @field_validator("template")
    @classmethod
    def _valid_template(cls, v: str) -> str:
        if v not in {t["id"] for t in TEMPLATES}:
            raise ValueError(f"未知模板：{v}")
        return v

    @field_validator("theme")
    @classmethod
    def _valid_theme(cls, v: str) -> str:
        if v not in {t["id"] for t in THEMES}:
            raise ValueError(f"未知主题：{v}")
        return v


class ResumeModule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    data: dict[str, str] = Field(default_factory=dict)
    order: int = 0
    collapsed: bool = False

    @field_validator("data")
    @classmethod
    def _no_dangerous_keys(cls, data: dict[str, str]) -> dict[str, str]:
        for key in data:
            if key in DANGEROUS_KEYS:
                raise ValueError(f"非法字段名：{key}")
        return data

    @model_validator(mode="after")
    def _check_fields(self) -> "ResumeModule":
        spec = get_spec(self.type)
        allowed = set(spec.field_names)
        unknown = [k for k in self.data if k not in allowed]
        if unknown:
            raise ValueError(f"模块 {self.type} 含未知字段：{unknown}")
        cleaned: dict[str, str] = {}
        for f in spec.fields:
            raw = self.data.get(f.name, "")
            value = "" if raw is None else str(raw)
            if len(value) > f.max_length:
                raise ValueError(f"字段 {f.name} 超出长度上限 {f.max_length}")
            cleaned[f.name] = value
        self.data = cleaned
        return self

    @property
    def title(self) -> str:
        return module_title(self.type, self.data)


class ResumeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: "r-" + secrets.token_hex(6))
    schemaVersion: str = SCHEMA_VERSION
    revision: int = 0
    targetJob: str = ""
    modules: list[ResumeModule] = Field(default_factory=list)
    appearance: Appearance = Field(default_factory=lambda: Appearance(**DEFAULT_APPEARANCE))
    #: 迁移时无法识别的旧数据放这里，绝不静默清空（第 7.2 节）
    recovery: list[dict[str, Any]] = Field(default_factory=list)

    # ---- 派生视图 ---------------------------------------------------------
    def module(self, module_id: str) -> ResumeModule | None:
        for m in self.modules:
            if m.id == module_id:
                return m
        return None

    def require_module(self, module_id: str) -> ResumeModule:
        mod = self.module(module_id)
        if mod is None:
            raise contract_error(f"模块 {module_id} 不存在", moduleId=module_id)
        return mod

    def by_type(self, module_type: str) -> list[ResumeModule]:
        return [m for m in sorted(self.modules, key=lambda x: x.order) if m.type == module_type]

    def sorted_modules(self) -> list[ResumeModule]:
        return sorted(self.modules, key=lambda x: (x.order, x.id))

    def content_hash(self) -> str:
        payload = {
            "schemaVersion": self.schemaVersion,
            "targetJob": self.targetJob,
            "appearance": self.appearance.model_dump(),
            "modules": [
                {"id": m.id, "type": m.type, "order": m.order, "data": m.data}
                for m in self.sorted_modules()
            ],
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]

    def text_blocks(self) -> list[tuple[str, str, str, str]]:
        """(moduleId, moduleType, field, text) —— 供事实提取、压缩、检索使用。"""
        out: list[tuple[str, str, str, str]] = []
        for m in self.sorted_modules():
            for f, v in m.data.items():
                if v and get_spec(m.type).field(f) and get_spec(m.type).field(f).kind != "image":
                    out.append((m.id, m.type, f, v))
        return out

    def char_count(self) -> int:
        return sum(len(t) for *_, t in self.text_blocks())

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "schemaVersion": self.schemaVersion,
            "revision": self.revision,
            "contentHash": self.content_hash(),
            "targetJob": self.targetJob,
            "moduleCount": len(self.modules),
            "charCount": self.char_count(),
            "modules": [
                {"id": m.id, "type": m.type, "title": m.title, "order": m.order} for m in self.sorted_modules()
            ],
        }


# ---------------------------------------------------------------------------
# 命令：唯一的写入入口
# ---------------------------------------------------------------------------
def new_document() -> ResumeDocument:
    doc = ResumeDocument()
    doc.modules = [
        ResumeModule(id="m-basic", type="basic", data=empty_data("basic"), order=0),
        ResumeModule(id="m-summary", type="summary", data=empty_data("summary"), order=1),
    ]
    return doc


def clone(doc: ResumeDocument) -> ResumeDocument:
    return ResumeDocument.model_validate(copy.deepcopy(doc.model_dump()))


def _bump(doc: ResumeDocument) -> None:
    doc.revision += 1
    for idx, m in enumerate(doc.sorted_modules()):
        m.order = idx


def replace_field(
    doc: ResumeDocument,
    module_id: str,
    field_name: str,
    value: str,
    *,
    actor: Literal["human", "ai"] = "ai",
) -> ResumeDocument:
    """单字段写入。`locked` 字段对 AI 完全关闭（人工仍可更正事实）。"""
    mod = doc.require_module(module_id)
    spec = get_spec(mod.type)
    fspec = spec.field(field_name)
    if fspec is None:
        raise unknown_field(mod.type, field_name)
    if fspec.kind == "image" and len(value) > fspec.max_length:
        raise contract_error("图片超出大小上限", field=field_name)
    if actor == "ai":
        if fspec.policy == "locked":
            raise fact_protected(module_id, field_name, "该字段属于硬事实")
        if fspec.policy == "asset":
            raise forbidden_operation("ai_write_asset")
    if len(value) > fspec.max_length:
        raise contract_error(f"字段 {field_name} 超出长度上限 {fspec.max_length}")
    new = clone(doc)
    target = new.require_module(module_id)
    if target.data.get(field_name, "") == value:
        return new  # 幂等：值未变不制造新版本
    target.data[field_name] = value
    _bump(new)
    return new


def add_module(
    doc: ResumeDocument,
    module_type: str,
    data: dict[str, str] | None = None,
    *,
    position: int | None = None,
    module_id: str | None = None,
) -> ResumeDocument:
    spec = get_spec(module_type)  # type: ignore[arg-type]
    if not spec.multiple and doc.by_type(module_type):
        raise contract_error(f"模块 {spec.zh} 只允许存在一个实例", moduleType=module_type)
    payload = dict(empty_data(module_type))
    for k, v in (data or {}).items():
        if k not in payload:
            raise unknown_field(module_type, k)
        payload[k] = "" if v is None else str(v)
    for f in spec.fields:
        if len(payload[f.name]) > f.max_length:
            raise contract_error(f"字段 {f.name} 超出长度上限 {f.max_length}", field=f.name)
    new = clone(doc)
    ordered = new.sorted_modules()
    insert_at = len(ordered) if position is None else max(0, min(position, len(ordered)))
    mod = ResumeModule(
        id=module_id or f"m-{module_type[:3]}-{secrets.token_hex(3)}",
        type=module_type,
        data=payload,
        order=insert_at,
    )
    ordered.insert(insert_at, mod)
    new.modules = ordered
    _bump(new)
    return new


def remove_module(doc: ResumeDocument, module_id: str) -> ResumeDocument:
    if doc.module(module_id) is None:
        raise contract_error(f"模块 {module_id} 不存在", moduleId=module_id)
    new = clone(doc)
    new.modules = [m for m in new.sorted_modules() if m.id != module_id]
    _bump(new)
    return new


def reorder_modules(doc: ResumeDocument, order: list[str]) -> ResumeDocument:
    ids = {m.id for m in doc.modules}
    if set(order) != ids:
        raise contract_error("排序必须给出全部模块 ID", missing=sorted(ids - set(order)))
    new = clone(doc)
    by_id = {m.id: m for m in new.modules}
    for idx, module_id in enumerate(order):
        by_id[module_id].order = idx
    new.modules = [by_id[i] for i in order]
    _bump(new)
    return new


def change_appearance(doc: ResumeDocument, changes: dict[str, Any]) -> ResumeDocument:
    allowed = set(Appearance.model_fields)
    unknown = set(changes) - allowed
    if unknown:
        raise contract_error(f"未知外观字段：{sorted(unknown)}")
    new = clone(doc)
    payload = new.appearance.model_dump()
    payload.update(changes)
    new.appearance = Appearance.model_validate(payload)
    _bump(new)
    return new


def set_target_job(doc: ResumeDocument, target_job: str) -> ResumeDocument:
    if len(target_job) > 120:
        raise contract_error("求职意向过长")
    new = clone(doc)
    if new.targetJob == target_job:
        return new
    new.targetJob = target_job
    basic = new.by_type("basic")
    if basic and not basic[0].data.get("job"):
        basic[0].data["job"] = target_job
    _bump(new)
    return new


def validate_document(payload: dict[str, Any]) -> ResumeDocument:
    """边界校验器：前端载荷进入领域层前先过这里（含危险键检查）。"""
    if not isinstance(payload, dict):
        raise contract_error("文档必须是对象")
    for key in payload:
        if key in DANGEROUS_KEYS:
            raise contract_error(f"非法字段名：{key}")
    modules = payload.get("modules")
    if modules is not None and not isinstance(modules, list):
        raise contract_error("modules 必须是数组")
    for mod in modules or []:
        if not isinstance(mod, dict):
            raise contract_error("模块必须是对象")
        if not isinstance(mod.get("type"), str):
            raise contract_error("模块缺少 type")
        if mod["type"] not in {s.type for s in MODULE_SPECS}:
            raise unknown_module_type(str(mod["type"]))
        data = mod.get("data") or {}
        if not isinstance(data, dict):
            raise contract_error("模块 data 必须是对象")
        spec = get_spec(mod["type"])
        for k, v in data.items():
            if k in DANGEROUS_KEYS:
                raise contract_error(f"非法字段名：{k}")
            if k not in spec.field_names:
                raise unknown_field(mod["type"], k)
            if not isinstance(v, str):
                raise contract_error(f"字段 {k} 必须是字符串")
    try:
        return ResumeDocument.model_validate(payload)
    except ValidationError as exc:
        # pydantic 的报错不能直接出网：转成统一契约错误，只保留首条原因
        first = exc.errors()[0] if exc.errors() else {}
        message = str(first.get("msg", "文档结构不合法")).replace("Value error, ", "")
        raise contract_error(message, path=".".join(str(p) for p in first.get("loc", []))) from exc
