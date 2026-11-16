"""事实层：FactRecord + 三层事实保护（第 7.3 节）。

三层措施：
1. 字段级操作白名单 —— 见 `modules.py` 的 policy 与 `replace_field(actor="ai")` 的拒绝；
2. 对数字/日期/实体/事实引用的**确定性**检查 —— 本文件；
3. 对新增能力与语义偏移的辅助检查 + 用户确认 —— `semantic_shifts()`。

第 3 层不是形式化证明：数字相同也可能改变因果关系，因此提案始终保留原文对照与人工确认。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

from .modules import get_spec
from .resume import ResumeDocument

FactStatus = Literal["candidate", "confirmed", "rejected"]
Sensitivity = Literal["normal", "personal", "sensitive"]


class FactRecord(BaseModel):
    """用户提供或从文档提取的事实。提取 ≠ 确认，确认 ≠ 第三方核实。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    moduleId: str
    field: str
    value: str
    sourceRef: str = "user_input"
    status: FactStatus = "candidate"
    sensitivity: Sensitivity = "normal"
    confirmedAt: datetime | None = None

    def confirm(self) -> "FactRecord":
        return self.model_copy(update={"status": "confirmed", "confirmedAt": datetime.now(timezone.utc)})


# ---------------------------------------------------------------------------
# 令牌抽取
# ---------------------------------------------------------------------------
_YEAR_RE = re.compile(r"(?:(?:19|20)\d{2})")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s*[%％]")
_MONEY_RE = re.compile(r"[¥￥$]\s?\d+(?:\.\d+)?(?:\s?[万千kK])?")
_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,20}")
_ENTITY_RE = re.compile(r"(大学|学院|学校|公司|科技|集团|实验室|研究院|银行|医院|中学)")


@dataclass(frozen=True)
class TokenSet:
    years: frozenset[str]
    numbers: frozenset[str]
    percents: frozenset[str]
    money: frozenset[str]
    latin: frozenset[str]
    entities: frozenset[str]

    def union(self, other: "TokenSet") -> "TokenSet":
        return TokenSet(
            years=self.years | other.years,
            numbers=self.numbers | other.numbers,
            percents=self.percents | other.percents,
            money=self.money | other.money,
            latin=self.latin | other.latin,
            entities=self.entities | other.entities,
        )

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "years": sorted(self.years),
            "numbers": sorted(self.numbers),
            "percents": sorted(self.percents),
            "money": sorted(self.money),
            "latin": sorted(self.latin),
            "entities": sorted(self.entities),
        }


def extract_tokens(text: str) -> TokenSet:
    text = text or ""
    return TokenSet(
        years=frozenset(_YEAR_RE.findall(text)),
        numbers=frozenset(_NUM_RE.findall(_YEAR_RE.sub(" ", text))),
        percents=frozenset(m.strip() for m in _PERCENT_RE.findall(text)),
        money=frozenset(m.strip() for m in _MONEY_RE.findall(text)),
        latin=frozenset(m.lower() for m in _LATIN_RE.findall(text)),
        entities=frozenset(_ENTITY_RE.findall(text)),
    )


# ---------------------------------------------------------------------------
# 违规与检查结果
# ---------------------------------------------------------------------------
@dataclass
class Violation:
    kind: str
    detail: str
    severity: Literal["block", "warn"] = "block"

    def as_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail, "severity": self.severity}


@dataclass
class GuardResult:
    ok: bool
    violations: list[Violation] = field(default_factory=list)
    warnings: list[Violation] = field(default_factory=list)
    factIds: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "violations": [v.as_dict() for v in self.violations],
            "warnings": [v.as_dict() for v in self.warnings],
            "factIds": self.factIds,
        }


_ESCALATION_PAIRS: tuple[tuple[str, str], ...] = (
    ("参与", "主导"),
    ("协助", "负责"),
    ("配合", "独立完成"),
    ("了解", "精通"),
    ("熟悉", "精通"),
    ("使用", "设计"),
    ("参加", "组织"),
)


def semantic_shifts(before: str, after: str) -> list[str]:
    """语义偏移检测：只做提示，交给用户确认（第 7.3 节第 3 层）。"""
    hits: list[str] = []
    for weak, strong in _ESCALATION_PAIRS:
        if weak in before and strong in after and strong not in before:
            hits.append(f"表述由「{weak}」升级为「{strong}」，请确认有事实支撑")
    return hits


def check_guarded_rewrite(
    before: str,
    after: str,
    *,
    allowed_tokens: TokenSet | None = None,
    fact_ids: Iterable[str] = (),
) -> GuardResult:
    """guarded 字段的确定性检查。

    - 原文数字/日期/金额/百分比不得凭空新增；
    - 原文已有的数字不得被静默删除（可改写表达，不能改事实）；
    - 语义升级只产生 warning，不阻断。
    """
    allowed = allowed_tokens or TokenSet(
        frozenset(), frozenset(), frozenset(), frozenset(), frozenset(), frozenset()
    )
    b, a = extract_tokens(before), extract_tokens(after)
    violations: list[Violation] = []
    warnings: list[Violation] = []

    def _check(kind: str, before_set: frozenset[str], after_set: frozenset[str], label: str) -> None:
        allowed_set = getattr(allowed, kind)
        for token in sorted(after_set - before_set - allowed_set):
            violations.append(Violation("new_fact_token", f"新增{label}「{token}」缺少事实来源"))
        for token in sorted(before_set - after_set):
            violations.append(Violation("dropped_fact_token", f"原文{label}「{token}」被删除"))

    _check("years", b.years, a.years, "年份")
    _check("numbers", b.numbers, a.numbers, "数字")
    _check("percents", b.percents, a.percents, "百分比")
    _check("money", b.money, a.money, "金额")

    for shift in semantic_shifts(before, after):
        warnings.append(Violation("semantic_shift", shift, severity="warn"))

    if len(after) > max(120, len(before) * 2 + 40):
        warnings.append(Violation("length_inflation", "改写后长度显著膨胀，请确认信息密度", severity="warn"))

    return GuardResult(ok=not violations, violations=violations, warnings=warnings, factIds=list(fact_ids))


# ---------------------------------------------------------------------------
# 文档 → 事实库
# ---------------------------------------------------------------------------
def extract_facts(doc: ResumeDocument, *, status: FactStatus = "candidate") -> list[FactRecord]:
    """从文档的 locked 字段生成事实记录；guarded 字段只取短值。

    AI 生成的文本不会自动变成事实：调用方必须显式把 `status` 设为 candidate，
    再由用户在记忆面板确认（第 11.1 节）。
    """
    facts: list[FactRecord] = []
    for mod in doc.sorted_modules():
        spec = get_spec(mod.type)
        for fspec in spec.fields:
            if fspec.policy not in {"locked", "guarded"} or fspec.kind == "image":
                continue
            value = str(mod.data.get(fspec.name) or "").strip()
            if not value:
                continue
            if fspec.policy == "guarded" and len(value) > 60:
                continue  # 长文本不是"事实条目"，其事实性由守卫逐次检查
            facts.append(
                FactRecord(
                    id=f"fact-{mod.id}-{fspec.name}",
                    moduleId=mod.id,
                    field=fspec.name,
                    value=value,
                    sourceRef=f"document:{doc.id}@rev{doc.revision}",
                    status=status,
                    sensitivity="personal" if fspec.name in {"phone", "email", "name"} else "normal",
                )
            )
    return facts


def fact_tokens(facts: Iterable[FactRecord]) -> TokenSet:
    """把事实库里的值折成令牌集合，作为"允许出现的新令牌"白名单。"""
    acc = TokenSet(
        frozenset(), frozenset(), frozenset(), frozenset(), frozenset(), frozenset()
    )
    for f in facts:
        acc = acc.union(extract_tokens(f.value))
    return acc


def locked_value_map(doc: ResumeDocument) -> dict[str, list[str]]:
    """供实体一致性检查：每个 locked 字段的当前值。"""
    out: dict[str, list[str]] = {}
    for mod in doc.sorted_modules():
        spec = get_spec(mod.type)
        for fspec in spec.fields:
            if fspec.policy != "locked":
                continue
            value = str(mod.data.get(fspec.name) or "").strip()
            if value:
                out.setdefault(fspec.name, []).append(value)
    return out
