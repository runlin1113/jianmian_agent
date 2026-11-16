"""受控工具注册表（第 8.1/8.2 节）。

三条硬边界：
1. **不反射调用**：模型给出的工具名必须先落在注册表里，再看该意图是否被允许；
2. **默认最小权限**：注册表里没有 Shell、任意文件系统、任意 SQL、任意 HTTP、自动装插件；
3. **有界执行**：单次 run 工具调用次数、单工具耗时、模型预算都从配置强制。

工具返回值必须逐字段清洗：不允许夹带可执行 JS、模板 HTML、CSS 或任意 JSON Pointer。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import Settings
from ..domain import errors
from ..domain.jobs import classify_skill
from ..domain.modules import MODULE_BY_TYPE, get_spec
from ..domain.proposals import assert_plain_text
from ..ports.budget import BudgetStore
from ..ports.model import ModelProvider, ModelRequest, estimate_tokens
from ..ports.search import SearchProvider
from .state import AgentState

ToolCategory = Literal["read", "propose", "clarify", "layout"]
MAX_TOOL_SECONDS = 60.0


# ---------------------------------------------------------------------------
# 参数 Schema
# ---------------------------------------------------------------------------
class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AskUserParams(_Params):
    questions: list[str] = Field(min_length=1, max_length=5)
    fields: list[str] = Field(default_factory=list, max_length=8)


class BuildDraftParams(_Params):
    materials: str = Field(min_length=1, max_length=20_000)
    target_job: str = Field(default="", max_length=120)


class FillModuleParams(_Params):
    module_type: str
    materials: str = Field(min_length=1, max_length=20_000)


class RewriteFieldParams(_Params):
    module_id: str
    field: str
    instruction: str = Field(default="", max_length=500)


class CompressParams(_Params):
    budget: int = Field(default=760, ge=200, le=3000)
    scope: str = Field(default="all", max_length=40)


class ParseParams(_Params):
    blocks: str = Field(min_length=1, max_length=60_000)


class SearchJdParams(_Params):
    role: str = Field(min_length=1, max_length=120)
    city: str = Field(default="", max_length=40)
    limit: int = Field(default=5, ge=1, le=10)


class AnalyzeMatchParams(_Params):
    target_job: str = Field(min_length=1, max_length=120)


class LayoutParams(_Params):
    reason: str = Field(default="compress", max_length=40)


class InterviewTurnParams(_Params):
    question: str = Field(default="", max_length=500)
    answer: str = Field(default="", max_length=4000)
    topic: str = Field(default="项目深挖", max_length=60)


# ---------------------------------------------------------------------------
# 工具定义
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    category: ToolCategory
    params: type[BaseModel]
    #: 是否会产出结构化修改提案
    writes: bool = False
    #: 是否访问网络
    network: bool = False
    #: 是否处理个人数据（决定是否需要额外授权与日志脱敏）
    personal_data: bool = False
    destructive: bool = False
    max_seconds: float = MAX_TOOL_SECONDS


@dataclass
class ToolContext:
    settings: Settings
    model: ModelProvider
    job_provider: SearchProvider
    budget: BudgetStore
    budget_subject: str
    #: 本次模型调用的租约（由编排层预占）
    state: AgentState

    def charge(self, usage_tokens: int) -> None:
        self.state.usage.promptTokens += usage_tokens


@dataclass
class ToolOutcome:
    ok: bool
    tool: str
    data: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    elapsedMs: int = 0


ALLOWED_BY_INTENT: dict[str, frozenset[str]] = {
    "build": frozenset({"ask_user", "build_draft", "search_jd"}),
    "edit": frozenset({"ask_user", "rewrite_field", "fill_module", "request_layout_check"}),
    "compress": frozenset({"ask_user", "compress_all", "request_layout_check"}),
    "job": frozenset({"search_jd", "analyze_match", "ask_user"}),
    "import": frozenset({"parse_resume", "ask_user"}),
    "interview": frozenset({"interview_turn", "ask_user"}),
    "memory": frozenset({"ask_user"}),
    "clarify": frozenset({"ask_user"}),
}


def _sanitize(value: Any, depth: int = 0) -> Any:
    """递归清洗工具输出。字符串必须是纯文本，否则直接拒绝整条结果。"""
    if depth > 6:
        raise errors.contract_error("工具输出嵌套过深")
    if isinstance(value, str):
        return assert_plain_text(value, where="工具输出")
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in {"__proto__", "constructor", "prototype", "$ref", "$dynamicRef"}:
                raise errors.contract_error(f"工具输出含危险键：{k}")
            out[k] = _sanitize(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_sanitize(v, depth + 1) for v in value[:50]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


Handler = Callable[[BaseModel, ToolContext], Awaitable[dict[str, Any]]]


class ToolRegistry:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, Handler] = {}

    # ---- 注册 ------------------------------------------------------------
    def register(self, spec: ToolSpec, handler: Handler) -> None:
        if spec.name in self._specs:
            raise ValueError(f"工具 {spec.name} 重复注册")
        if spec.category not in {"read", "propose", "clarify", "layout"}:
            raise ValueError(f"非法工具类别 {spec.category}")
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def catalog(self) -> list[dict]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "category": s.category,
                "writes": s.writes,
                "network": s.network,
                "personalData": s.personal_data,
                "destructive": s.destructive,
            }
            for s in self._specs.values()
        ]

    def names(self) -> list[str]:
        return list(self._specs)

    # ---- 调用 ------------------------------------------------------------
    async def call(
        self,
        name: str,
        raw_args: dict[str, Any],
        ctx: ToolContext,
        *,
        intent: str,
        allow_destructive: bool = False,
    ) -> ToolOutcome:
        started = time.time()
        spec = self._specs.get(name)
        if spec is None:
            # 模型给了不存在的工具：拒绝，绝不反射执行
            return ToolOutcome(
                ok=False,
                tool=name,
                error={"code": "unknown_tool", "message": f"未注册的工具 {name}"},
                elapsedMs=0,
            )
        allowed = ALLOWED_BY_INTENT.get(intent, frozenset())
        if name not in allowed:
            return ToolOutcome(
                ok=False,
                tool=name,
                error={"code": "tool_not_permitted", "message": f"意图 {intent} 无权调用 {name}"},
                elapsedMs=0,
            )
        if spec.destructive and not allow_destructive:
            return ToolOutcome(
                ok=False,
                tool=name,
                error={"code": "destructive_not_permitted", "message": "该操作需要用户显式指令"},
                elapsedMs=0,
            )
        if ctx.state.tool_calls >= self._settings.max_tool_calls_per_run:
            return ToolOutcome(
                ok=False,
                tool=name,
                error={"code": "tool_budget_exceeded", "message": "本次任务工具调用次数已达上限"},
                elapsedMs=0,
            )
        try:
            args = spec.params.model_validate(raw_args)
        except ValidationError as exc:
            return ToolOutcome(
                ok=False,
                tool=name,
                error={"code": "invalid_tool_args", "message": "工具参数不符合 Schema", "detail": exc.errors()[:3]},
                elapsedMs=0,
            )

        ctx.state.tool_calls += 1
        try:
            data = await self._handlers[name](args, ctx)
            cleaned = _sanitize(data)
        except errors.DomainError as exc:
            return ToolOutcome(ok=False, tool=name, error=exc.to_payload()["error"], elapsedMs=0)
        except Exception as exc:  # 工具内部异常不能拖垮整个 run
            return ToolOutcome(
                ok=False,
                tool=name,
                error={"code": "tool_failed", "message": f"工具执行失败（{type(exc).__name__}）"},
                elapsedMs=int((time.time() - started) * 1000),
            )
        return ToolOutcome(
            ok=True, tool=name, data=cleaned, elapsedMs=int((time.time() - started) * 1000)
        )


# ---------------------------------------------------------------------------
# 十个首批工具的具体实现
# ---------------------------------------------------------------------------
async def _model_generate(ctx: ToolContext, task: str, inputs: dict, *, max_tokens: int = 1200) -> dict:
    """统一走预算：先预占，再调用，最后按实际用量结算。"""
    estimated = estimate_tokens(str(inputs)) + max_tokens
    lease = ctx.budget.reserve(ctx.budget_subject, estimated)
    if lease is None:
        raise errors.budget_exhausted("演示额度已用完，请稍后再试或使用自己的 Key")
    try:
        result = await ctx.model.generate(ModelRequest(task=task, inputs=inputs, maxTokens=max_tokens))
    except Exception:
        ctx.budget.release(lease)
        raise
    if not result.ok or result.structured is None:
        ctx.budget.settle(lease, 0)
        raise errors.upstream_unavailable("模型未返回可用的结构化结果")
    ctx.budget.settle(lease, result.usage.totalTokens or estimated)
    ctx.state.usage.promptTokens += result.usage.promptTokens
    ctx.state.usage.completionTokens += result.usage.completionTokens
    ctx.state.usage.totalTokens += result.usage.totalTokens
    ctx.state.usage.costCny += result.usage.costCny
    return result.structured


def build_registry(settings: Settings) -> ToolRegistry:
    registry = ToolRegistry(settings)

    async def ask_user(args: AskUserParams, ctx: ToolContext) -> dict:
        return {"clarifications": args.questions, "fields": args.fields}

    async def build_draft(args: BuildDraftParams, ctx: ToolContext) -> dict:
        payload = await _model_generate(
            ctx,
            "build_modules",
            {
                "materials": args.materials,
                "target_job": args.target_job,
                "facts": "；".join(ctx.state.memory_facts[:8]),
            },
            max_tokens=1600,
        )
        modules = []
        for entry in payload.get("modules") or []:
            if not isinstance(entry, dict):
                continue
            module_type = entry.get("type")
            if module_type not in MODULE_BY_TYPE:
                continue
            spec = get_spec(module_type)
            data = {
                str(k): str(v)
                for k, v in (entry.get("data") or {}).items()
                if k in spec.field_names and v not in (None, "")
            }
            if data:
                modules.append({"type": module_type, "data": data})
        return {
            "modules": modules,
            "clarifications": [
                c for c in (payload.get("clarifications") or []) if isinstance(c, dict)
            ][:6],
            "missing": [str(m) for m in (payload.get("missing") or [])][:6],
        }

    async def fill_module(args: FillModuleParams, ctx: ToolContext) -> dict:
        if args.module_type not in MODULE_BY_TYPE:
            raise errors.unknown_module_type(args.module_type)
        payload = await _model_generate(
            ctx,
            "build_modules",
            {"materials": args.materials, "target_job": ctx.state.target_job, "facts": ""},
            max_tokens=1200,
        )
        spec = get_spec(args.module_type)
        for entry in payload.get("modules") or []:
            if isinstance(entry, dict) and entry.get("type") == args.module_type:
                data = {
                    str(k): str(v)
                    for k, v in (entry.get("data") or {}).items()
                    if k in spec.field_names and v not in (None, "")
                }
                if data:
                    return {"moduleType": args.module_type, "data": data}
        raise errors.contract_error("模型没有为该模块产出可用内容", moduleType=args.module_type)

    async def rewrite_field(args: RewriteFieldParams, ctx: ToolContext) -> dict:
        document = ctx.state.document
        if document is None:
            raise errors.contract_error("缺少文档工作副本")
        module = document.require_module(args.module_id)
        spec = get_spec(module.type)
        fspec = spec.field(args.field)
        if fspec is None:
            raise errors.unknown_field(module.type, args.field)
        if not fspec.ai_editable:
            raise errors.fact_protected(module.id, args.field, "该字段属于硬事实")
        before = module.data.get(args.field, "")
        payload = await _model_generate(
            ctx,
            "rewrite_field",
            {
                "text": before,
                "module_type": module.type,
                "module_label": spec.zh,
                "field": args.field,
                "field_label": fspec.label,
                "target_job": ctx.state.target_job,
                "instruction": args.instruction,
            },
            max_tokens=900,
        )
        after = str(payload.get("after") or "").strip()
        if not after:
            raise errors.upstream_unavailable("模型返回了空文本")
        return {
            "moduleId": module.id,
            "field": args.field,
            "before": before,
            "after": after,
            "notes": [str(n) for n in (payload.get("notes") or [])][:5],
        }

    async def compress_all(args: CompressParams, ctx: ToolContext) -> dict:
        document = ctx.state.document
        if document is None:
            raise errors.contract_error("缺少文档工作副本")
        edits: list[dict] = []
        notes: list[str] = []
        for module in document.sorted_modules():
            spec = get_spec(module.type)
            for fspec in spec.fields:
                if not fspec.ai_editable or fspec.kind == "image":
                    continue
                text = module.data.get(fspec.name, "")
                if len(text) <= args.budget // 3:
                    continue
                payload = await _model_generate(
                    ctx,
                    "compress_all",
                    {
                        "text": text,
                        "budget": args.budget // 3,
                        "density": "balanced",
                        "current": len(text),
                        "tokens": text,
                    },
                    max_tokens=900,
                )
                after = str(payload.get("after") or "").strip()
                if after and after != text:
                    edits.append(
                        {
                            "moduleId": module.id,
                            "field": fspec.name,
                            "before": text,
                            "after": after,
                        }
                    )
                notes.extend(str(n) for n in (payload.get("notes") or [])[:2])
        return {"edits": edits, "notes": notes[:6], "budget": args.budget}

    async def parse_resume(args: ParseParams, ctx: ToolContext) -> dict:
        payload = await _model_generate(ctx, "parse_map", {"blocks": args.blocks}, max_tokens=1600)
        modules = []
        for entry in payload.get("modules") or []:
            if not isinstance(entry, dict):
                continue
            module_type = entry.get("type")
            if module_type not in MODULE_BY_TYPE:
                continue
            spec = get_spec(module_type)
            data = {
                str(k): str(v)
                for k, v in (entry.get("data") or {}).items()
                if k in spec.field_names and v not in (None, "")
            }
            modules.append(
                {
                    "type": module_type,
                    "data": data,
                    "confidence": float(entry.get("confidence") or 0.6),
                    "sourcePages": [int(p) for p in (entry.get("sourcePages") or [])][:10],
                }
            )
        return {"modules": modules, "unmapped": [str(u) for u in (payload.get("unmapped") or [])][:10]}

    async def search_jd(args: SearchJdParams, ctx: ToolContext) -> dict:
        jobs = await ctx.job_provider.search(role=args.role, city=args.city, limit=args.limit)
        return {
            "jobs": [j.model_dump(mode="json") for j in jobs],
            "provider": getattr(ctx.job_provider, "name", "unknown"),
            "isSample": all(j.isSample for j in jobs) if jobs else True,
            "count": len(jobs),
        }

    async def analyze_match(args: AnalyzeMatchParams, ctx: ToolContext) -> dict:
        document = ctx.state.document
        if document is None:
            raise errors.contract_error("缺少文档工作副本")
        jobs = [j for j in ctx.state.extra.get("jobs", [])]
        skills: list[str] = []
        for job in jobs:
            for skill in job.get("skills", []):
                if skill not in skills:
                    skills.append(skill)
        if not skills:
            raise errors.contract_error("还没有岗位证据，请先检索岗位")
        spans_by_skill: dict[str, list[str]] = {}
        blocks = document.text_blocks()
        for skill in skills:
            low = skill.lower()
            spans = [f"{ty}:{txt[:40]}" for _, ty, _, txt in blocks if low in txt.lower()]
            spans_by_skill[skill] = spans
        jd_hits = {skill: [j["id"] for j in jobs if skill in j.get("skills", [])] for skill in skills}
        hits = [
            classify_skill(skill, resume_spans=spans_by_skill[skill], jd_hits=jd_hits[skill]).model_dump()
            for skill in skills
        ]
        return {"hits": hits, "sampleSize": len(jobs)}

    async def request_layout_check(args: LayoutParams, ctx: ToolContext) -> dict:
        document = ctx.state.document
        if document is None:
            raise errors.contract_error("缺少文档工作副本")
        return {
            "requiresLayout": True,
            "candidateHash": document.content_hash(),
            "reason": args.reason,
            "minFontPt": settings.min_font_pt,
        }

    async def interview_turn(args: InterviewTurnParams, ctx: ToolContext) -> dict:
        if args.answer:
            payload = await _model_generate(
                ctx,
                "interview_followup",
                {"question": args.question, "answer": args.answer},
                max_tokens=300,
            )
        else:
            spans = ""
            if ctx.state.document is not None:
                spans = "\n".join(t for _, _, _, t in ctx.state.document.text_blocks())[:2000]
            payload = await _model_generate(
                ctx,
                "interview_question",
                {"target_job": ctx.state.target_job, "topic": args.topic, "resume_spans": spans},
                max_tokens=400,
            )
        return {"question": str(payload.get("question") or "").strip()}

    registry.register(
        ToolSpec("ask_user", "提出澄清问题，绝不生成虚构经历", "clarify", AskUserParams),
        ask_user,
    )
    registry.register(
        ToolSpec(
            "build_draft",
            "根据用户素材生成模块草稿提案",
            "propose",
            BuildDraftParams,
            writes=True,
            personal_data=True,
        ),
        build_draft,
    )
    registry.register(
        ToolSpec(
            "fill_module",
            "用素材补全指定类型的模块",
            "propose",
            FillModuleParams,
            writes=True,
            personal_data=True,
        ),
        fill_module,
    )
    registry.register(
        ToolSpec(
            "rewrite_field",
            "改写单个字段的表达（不改事实）",
            "propose",
            RewriteFieldParams,
            writes=True,
            personal_data=True,
        ),
        rewrite_field,
    )
    registry.register(
        ToolSpec(
            "compress_all",
            "按档位压缩全文，保留硬事实",
            "propose",
            CompressParams,
            writes=True,
            personal_data=True,
        ),
        compress_all,
    )
    registry.register(
        ToolSpec(
            "parse_resume",
            "把文档块映射成模块候选与证据",
            "propose",
            ParseParams,
            writes=True,
            personal_data=True,
        ),
        parse_resume,
    )
    registry.register(
        ToolSpec("search_jd", "检索岗位证据（带来源与获取时间）", "read", SearchJdParams, network=True),
        search_jd,
    )
    registry.register(
        ToolSpec("analyze_match", "对比事实与岗位证据，输出三档结论", "read", AnalyzeMatchParams),
        analyze_match,
    )
    registry.register(
        ToolSpec("request_layout_check", "请求浏览器真实版面测量", "layout", LayoutParams),
        request_layout_check,
    )
    registry.register(
        ToolSpec(
            "interview_turn",
            "生成下一问或基于回答的追问",
            "read",
            InterviewTurnParams,
            personal_data=True,
        ),
        interview_turn,
    )
    return registry
