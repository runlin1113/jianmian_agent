"""旧数据迁移（第 7.2 节）。

约束：
- 只做纯函数迁移，不写存储；
- 旧 `apiKey` 绝不进入新文档（密钥隔离）；
- 未知模块 / 损坏数据进入 `recovery` 区，不静默清空；
- 迁移成功与否由调用方在**完整校验并成功写入后**再标记完成。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from .modules import DENSITY_BUDGETS, LEGACY_TYPE_MAP, MODULE_SPECS, get_spec
from .resume import Appearance, ResumeDocument, ResumeModule, new_document


@dataclass
class MigrationResult:
    document: ResumeDocument
    warnings: list[str] = field(default_factory=list)
    recovered: list[dict[str, Any]] = field(default_factory=list)
    migrated: bool = False
    dropped_keys: list[str] = field(default_factory=list)


def _coerce_appearance(raw: dict[str, Any]) -> Appearance:
    payload = {
        "template": raw.get("template", "executive"),
        "theme": raw.get("theme", "navy"),
        "density": raw.get("density", "balanced"),
        "zoom": raw.get("zoom", 0.75),
    }
    try:
        return Appearance.model_validate(payload)
    except (ValidationError, ValueError):
        payload.update(template="executive", theme="navy", density="balanced")
        try:
            return Appearance.model_validate(payload)
        except (ValidationError, ValueError):
            return Appearance()


def migrate_legacy(payload: dict[str, Any]) -> MigrationResult:
    """把 `jianmian_studio_v1` 结构迁移成 `ResumeDocument`。"""
    warnings: list[str] = []
    recovered: list[dict[str, Any]] = []
    dropped: list[str] = []

    if not isinstance(payload, dict):
        return MigrationResult(new_document(), ["旧数据不是对象，已忽略"], [], False, [])

    doc = new_document()
    doc.id = str(payload.get("resumeId") or doc.id)
    doc.targetJob = str(payload.get("targetJob") or "")[:120]
    doc.appearance = _coerce_appearance(payload)

    density = payload.get("density")
    if density and density not in DENSITY_BUDGETS:
        warnings.append(f"未知篇幅档位 {density}，已回退 balanced")

    # 密钥隔离：只记录"丢弃了这个键"，绝不复制值
    api = payload.get("api")
    if isinstance(api, dict) and (api.get("apiKey") or "").strip():
        dropped.append("api.apiKey")
        warnings.append("旧版曾把 API Key 写入本地状态；迁移时已丢弃，请在设置中重新填写（仅存内存）")

    modules: list[ResumeModule] = []
    seen_singleton: set[str] = set()
    for index, raw_mod in enumerate(payload.get("modules") or []):
        if not isinstance(raw_mod, dict):
            recovered.append({"reason": "模块不是对象", "raw": copy.deepcopy(raw_mod)})
            continue
        legacy_type = raw_mod.get("type")
        module_type = LEGACY_TYPE_MAP.get(str(legacy_type)) or (
            str(legacy_type) if str(legacy_type) in {s.type for s in MODULE_SPECS} else None
        )
        if module_type is None:
            recovered.append({"reason": f"未知模块类型 {legacy_type}", "raw": copy.deepcopy(raw_mod)})
            warnings.append(f"未知模块「{legacy_type}」已放入恢复区")
            continue

        spec = get_spec(module_type)
        if not spec.multiple and module_type in seen_singleton:
            recovered.append({"reason": f"重复的单例模块 {module_type}", "raw": copy.deepcopy(raw_mod)})
            continue
        seen_singleton.add(module_type)

        raw_data = raw_mod.get("data") or {}
        if not isinstance(raw_data, dict):
            recovered.append({"reason": "data 不是对象", "raw": copy.deepcopy(raw_mod)})
            continue
        # 旧版有两种写法：字段放在 data 里，或直接摊在模块层级上。两种都接受。
        flat = {
            key: value
            for key, value in raw_mod.items()
            if key not in {"id", "type", "data", "order", "collapsed"}
        }
        merged = {**flat, **raw_data}
        # 旧版可能用中文字段名；用字段标签做一次显式映射，不做模糊匹配
        label_to_name = {spec.field(name).label: name for name in spec.field_names if spec.field(name)}
        data: dict[str, str] = {}
        leftovers: dict[str, Any] = {}
        for key, value in merged.items():
            name = key if key in spec.field_names else label_to_name.get(str(key))
            if name is None:
                leftovers[key] = value
                continue
            text = "" if value is None else str(value)
            limit = spec.field(name).max_length  # type: ignore[union-attr]
            if len(text) > limit:
                warnings.append(f"{spec.zh}.{name} 超出长度上限，已截断")
                text = text[:limit]
            data[name] = text
        if leftovers:
            recovered.append(
                {"reason": f"{spec.zh} 含未知字段", "moduleId": raw_mod.get("id"), "raw": leftovers}
            )
        modules.append(
            ResumeModule(
                id=str(raw_mod.get("id") or f"m-{module_type}-{index}"),
                type=module_type,
                data=data,
                order=index,
                collapsed=bool(raw_mod.get("collapsed", False)),
            )
        )

    if not modules:
        warnings.append("旧数据中没有任何可迁移模块，已生成空白文档")
    else:
        doc.modules = modules
        doc.revision = 1

    doc.recovery = recovered
    # 最终校验：新文档必须能被完整校验，才算迁移可用
    validated = ResumeDocument.model_validate(doc.model_dump())
    return MigrationResult(validated, warnings, recovered, migrated=bool(modules), dropped_keys=dropped)
