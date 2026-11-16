"""主图与业务子图（M6/M7/M8/M10/M11 的编排部分）。

流程（与架构书第 8.1 节一致）：
输入校验 → 上下文 → 意图与计划 → 权限/预算 → 工具 → 校验 → 提案 → 用户确认 → 本地应用

节点是职责划分，不代表每个节点都调用模型：
输入校验、字段检查、事实守卫、提案装配都在普通代码里完成；
只有表述生成、映射、追问等确实需要语义能力的地方才走 ModelProvider。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from ..config import Settings
from ..domain import errors
from ..domain.facts import extract_facts, fact_tokens
from ..domain.modules import DENSITY_BUDGETS, get_spec
from ..domain.proposals import (
    AddModuleOp,
    AppearanceOp,
    ChangeProposal,
    RemoveModuleOp,
    ReplaceFieldOp,
    ReorderOp,
    apply_proposal,
    assert_plain_text,
)
from ..domain.resume import ResumeDocument, new_document
from ..ports.budget import BudgetStore
from ..ports.model import ModelProvider
from ..ports.search import SearchProvider
from ..ports.store import PendingInterrupt
from ..security.ids import opaque_id
from .engine import END, PAUSE, GraphSpec
from .intents import IntentResult, classify, default_field_for
from .state import AgentState
from .tools import ALLOWED_BY_INTENT, ToolContext, ToolRegistry

Emit = Callable[[str, dict], None]


@dataclass
class WorkflowDeps:
    settings: Settings
    model: ModelProvider
    job_provider: SearchProvider
    budget: BudgetStore
    registry: ToolRegistry


class WorkflowNodes:
    def __init__(self, deps: WorkflowDeps) -> None:
        self.deps = deps
        self.settings = deps.settings

    # ---- 小工具 -----------------------------------------------------------
    def _ctx(self, state: AgentState) -> ToolContext:
        return ToolContext(
            settings=self.settings,
            model=self.deps.model,
            job_provider=self.deps.job_provider,
            budget=self.deps.budget,
            budget_subject=state.session_id,
            state=state,
        )

    def _emit(self, state: AgentState, event: str, payload: dict) -> None:
        emit: Emit | None = state.extra.get("emit")
        if emit is not None:
            emit(event, payload)

    async def _tool(self, state: AgentState, name: str, args: dict, *, allow_destructive: bool = False):
        outcome = await self.deps.registry.call(
            name,
            args,
            self._ctx(state),
            intent=state.intent,
            allow_destructive=allow_destructive,
        )
        self._emit(
            state,
            "step.completed",
            {"tool": name, "ok": outcome.ok, "elapsedMs": outcome.elapsedMs,
             "error": outcome.error["code"] if outcome.error else None},
        )
        return outcome

    def _doc(self, state: AgentState) -> ResumeDocument:
        if state.document is None:
            state.document = new_document()
        return state.document

    def _proposal(
        self, state: AgentState, ops: list[Any], summary: str, *, evidence: list[dict] | None = None
    ) -> ChangeProposal | None:
        """组装提案；若所有操作都等于原值，返回 None（不生成空提案）。

        "采纳了一处修改，但内容没变"是纯粹的坏体验：用户会以为系统坏了。
        宁可明确说"没找到可改的地方"，也不要交付一份空白 diff。
        """
        doc = self._doc(state)
        live = ops
        if ops:
            live = _drop_noop_ops(ops)
            if not live:
                state.message = (
                    "这段内容我没找到可改的地方——AI 不会为了凑改动而改写。"
                    "你可以直接手工润色，或补充希望强调的重点（比如「突出性能优化」）。"
                )
                state.warnings.append({"kind": "no_change", "detail": "改写结果与原文一致，已放弃生成提案"})
                return None
        return ChangeProposal(
            proposalId=opaque_id("p", 4),
            resumeId=doc.id,
            baseRevision=doc.revision,
            baseHash=doc.content_hash(),
            intent=state.intent,
            summary=summary,
            operations=live,
            evidence=evidence or [],
        )

    def _require_targets(self, state: AgentState, result: IntentResult) -> list[str]:
        if result.needs_clarification:
            raise errors.contract_error("存在歧义，必须先澄清")
        if not result.module_ids:
            raise errors.DomainError(
                "target_not_resolved",
                "没能确定要改哪个模块，请指明模块名称或序号",
                status=422,
            )
        return result.module_ids

    # ------------------------------------------------------------------
    # 公共节点
    # ------------------------------------------------------------------
    async def validate_input(self, state: AgentState) -> str | None:
        self._emit(state, "step.started", {"step": "validate_input", "label": "检查输入与文档版本"})
        if not state.instruction.strip():
            raise errors.contract_error("指令不能为空")
        if len(state.instruction) > 4000:
            raise errors.contract_error("指令过长（上限 4000 字）")
        doc = self._doc(state)
        if doc.revision != state.document.revision:  # pragma: no cover - 防御
            raise errors.version_conflict(state.document.revision, doc.revision)
        state.deadline = state.started_at + self.settings.run_budget_seconds
        state.extra["candidateRevision"] = doc.revision
        state.extra["candidateHash"] = doc.content_hash()
        self._emit(
            state,
            "step.completed",
            {"step": "validate_input", "revision": doc.revision, "charCount": doc.char_count()},
        )
        return "assemble_context"

    async def assemble_context(self, state: AgentState) -> str | None:
        self._emit(state, "step.started", {"step": "assemble_context", "label": "装配上下文与已确认记忆"})
        doc = self._doc(state)
        state.extra["moduleIndex"] = [
            {"id": m.id, "type": m.type, "title": m.title} for m in doc.sorted_modules()
        ]
        state.extra["facts"] = [f.value for f in extract_facts(doc, status="confirmed")][:12]
        if state.memory_facts:
            state.extra["facts"] = (state.extra["facts"] + state.memory_facts)[:16]
        self._emit(
            state,
            "step.completed",
            {"step": "assemble_context", "modules": len(doc.modules), "facts": len(state.extra["facts"])},
        )
        return "classify"

    async def classify(self, state: AgentState) -> str | None:
        self._emit(state, "step.started", {"step": "classify", "label": "识别意图与目标模块"})
        forced = state.extra.pop("forcedIntent", None)
        result = classify(state.instruction, self._doc(state), forced_intent=forced)
        state.intent = result.intent
        state.sub_intent = result.sub_intent
        state.extra["intent"] = result.as_dict()
        state.extra["targets"] = result.module_ids
        state.extra["field"] = result.field
        state.extra["appearance"] = result.appearance
        self._emit(
            state,
            "step.completed",
            {"step": "classify", "intent": result.intent, "subIntent": result.sub_intent,
             "confidence": result.confidence, "targets": result.module_ids},
        )
        if result.needs_clarification:
            return await self._pause_for_clarification(state, result.question, result.options)
        routes = {
            "build": "build_check_materials",
            "edit": "edit_dispatch",
            "compress": "compress_dispatch",
            "job": "job_search",
            "import": "import_pending",
            "interview": "interview_next",
            "memory": "memory_pending",
            "clarify": "clarify_more",
        }
        return routes.get(result.intent, "edit_dispatch")

    async def _pause_for_clarification(
        self, state: AgentState, question: str, options: list[dict] | None = None
    ) -> str:
        doc = self._doc(state)
        state.pending = PendingInterrupt(
            kind="clarification",
            promptId=opaque_id("q", 4),
            question=question,
            options=options or [],
            candidateHash=doc.content_hash(),
            resumeRevision=doc.revision,
        )
        self._emit(
            state,
            "clarification.required",
            {"promptId": state.pending.promptId, "question": question, "options": options or []},
        )
        return PAUSE

    # ------------------------------------------------------------------
    # build：从素材生成可编辑初稿
    # ------------------------------------------------------------------
    async def build_check_materials(self, state: AgentState) -> str | None:
        materials = state.instruction
        job_hint = state.target_job
        if len(materials.strip()) < 12:
            # 素材太少时不逼用户补充，先给一份结构模板让他直接改——
            # "从一句话到一份简历"要能走完，卡在反问上等于没有产出
            state.extra["template_fallback"] = True
            return "build_generate"
        # 素材里没有目标岗位时先问一句，避免生成一份"对谁都合适"的空话
        if not job_hint and not any(
            k in materials
            for k in ("工程师", "开发", "实习", "岗位", "方向", "后端", "前端", "算法", "数据", "测试", "运维", "产品", "设计")
        ):
            return await self._pause_for_clarification(
                state,
                "先确认目标岗位吧：这份简历主要投什么方向？（例如 Python 后端 / 前端 / 数据分析）",
                [
                    {"label": "Python 后端", "value": "Python 后端开发"},
                    {"label": "前端开发", "value": "前端开发"},
                    {"label": "数据分析", "value": "数据分析"},
                ],
            )
        return "build_generate"

    async def build_generate(self, state: AgentState) -> str | None:
        self._emit(state, "step.started", {"step": "build_generate", "label": "根据素材生成模块草稿"})
        self._emit(state, "text.delta", {"text": "正在把你的素材整理成简历模块…"})
        outcome = await self._tool(
            state, "build_draft", {"materials": state.instruction, "target_job": state.target_job}
        )
        if not outcome.ok:
            state.extra["toolError"] = outcome.error
            return "handle_tool_error"

        modules = outcome.data.get("modules") or []
        clarifications = outcome.data.get("clarifications") or []
        template_used = False
        if not modules and state.extra.get("template_fallback"):
            # 提取不到任何内容：退到结构模板（占位文字，不编造经历）
            from ..adapters.model_mock import starter_modules

            modules = starter_modules(state.target_job)
            template_used = True
            clarifications = []
            state.warnings.append(
                {
                    "kind": "template_used",
                    "detail": "素材里没有可写入的信息，已按模板生成骨架：占位文字需要你替换成真实经历",
                }
            )
        if not modules:
            return await self._pause_for_clarification(
                state,
                "我没有从这段素材里提取到任何可写入的模块，怕编造内容。能补充学校、项目、技能中的任意一项吗？",
                [],
            )
        doc = self._doc(state)
        existing = {m.type for m in doc.modules}
        ops: list[Any] = []
        for entry in modules:
            module_type = entry["type"]
            spec = get_spec(module_type)
            data = {k: v for k, v in entry["data"].items() if k in spec.field_names}
            if not data:
                continue
            if module_type in existing and not spec.multiple:
                # 单例模块已存在，分两种情况：
                module = doc.by_type(module_type)[0]
                is_blank = not any(str(v).strip() for v in module.data.values())
                if is_blank:
                    # ① 还没填过的空骨架（首次打开应用就是这种）→ 整块换成素材生成的模块。
                    #    走 AddModuleOp 而不是逐字段写，是因为姓名/电话/学校这些是硬事实：
                    #    硬事实一律不接受"AI 改写"，但"把用户自己打的字搬进去"不是改写。
                    #    删掉空骨架再新增，语义上等价于"填这张空表"，且保持一次提案、一次 +1 版本。
                    remove = RemoveModuleOp(moduleId=module.id, reason="空骨架，用素材内容替换")
                    ops.append(remove)
                    ops.append(
                        AddModuleOp(
                            moduleType=module_type,
                            data={
                                assert_plain_text(k, where="字段名"): assert_plain_text(v, where=k)
                                for k, v in data.items()
                            },
                            reason="来自用户素材（原话搬运，未编造）",
                        )
                    )
                    continue
                # ② 已有内容 → 只补可改写字段，硬事实不越权
                for field_name, value in data.items():
                    fspec = spec.field(field_name)
                    if fspec and fspec.ai_editable and not module.data.get(field_name):
                        ops.append(
                            ReplaceFieldOp(
                                moduleId=module.id,
                                field=field_name,
                                before="",
                                after=value,
                                reason="用用户素材补全",
                            )
                        )
                continue
            ops.append(
                AddModuleOp(
                    moduleType=module_type,
                    data={assert_plain_text(k, where="字段名"): assert_plain_text(v, where=k) for k, v in data.items()},
                    reason="来自用户素材，未包含未提供的数字",
                )
            )
        state.clarifications = clarifications
        if clarifications:
            state.warnings.extend(
                {"kind": "missing_info", "detail": c.get("question", "")} for c in clarifications if c.get("question")
            )
        state.proposal = self._proposal(
            state,
            ops,
            "先给你一份结构模板（占位内容请替换成真实经历）"
            if template_used
            else "根据你的素材生成初稿（缺失信息未编造）",
        )
        return "guard_proposal"

    # ------------------------------------------------------------------
    # edit：单字段改写 / 删除 / 排序 / 外观
    # ------------------------------------------------------------------
    async def edit_dispatch(self, state: AgentState) -> str | None:
        intent_info = state.extra.get("intent", {})
        sub = state.sub_intent
        if intent_info.get("needsClarification"):
            question = "这句话指向多个位置，请确认要改哪一个？"
            options = [{"moduleId": mid, "label": mid} for mid in intent_info.get("moduleIds") or []]
            return await self._pause_for_clarification(state, question, options)
        if sub == "appearance":
            return "edit_appearance"
        if sub == "remove":
            return "edit_remove"
        if sub == "reorder":
            return "edit_reorder"
        if sub == "add":
            return "edit_add"
        return "edit_rewrite"

    async def edit_rewrite(self, state: AgentState) -> str | None:
        doc = self._doc(state)
        targets: list[str] = state.extra.get("targets") or []
        if not targets:
            return await self._pause_for_clarification(
                state,
                "要改哪一段？可以说「改第二个项目的详情」或「润色自我评价」。",
                [{"moduleId": m.id, "label": m.title} for m in doc.sorted_modules()][:8],
            )
        ops: list[Any] = []
        for module_id in targets:
            module = doc.require_module(module_id)
            spec = get_spec(module.type)
            field_name = state.extra.get("field") or default_field_for(module.type)
            fspec = spec.field(field_name)
            if fspec is None or not fspec.ai_editable:
                return await self._pause_for_clarification(
                    state,
                    f"「{spec.zh}」的 {field_name} 属于硬事实，AI 不能改写。你可以直接手工编辑，或让我改它的描述部分。",
                    [],
                )
            self._emit(state, "step.started", {"step": "rewrite_field", "label": f"改写 {module.title}"})
            outcome = await self._tool(
                state,
                "rewrite_field",
                {"module_id": module.id, "field": field_name, "instruction": state.instruction},
            )
            if not outcome.ok:
                state.extra["toolError"] = outcome.error
                return "handle_tool_error"
            ops.append(
                ReplaceFieldOp(
                    moduleId=module.id,
                    field=field_name,
                    before=outcome.data["before"],
                    after=outcome.data["after"],
                    reason=f"按指令「{state.instruction[:40]}」改写表达，保留原有事实",
                )
            )
        state.proposal = self._proposal(state, ops, "按你的指令改写表达（事实字段未改动）")
        return "guard_proposal"

    async def edit_remove(self, state: AgentState) -> str | None:
        doc = self._doc(state)
        targets: list[str] = state.extra.get("targets") or []
        if not targets:
            return await self._pause_for_clarification(
                state, "要删哪个模块？告诉我名称或序号。", [{"moduleId": m.id, "label": m.title} for m in doc.modules]
            )
        ops = []
        for module_id in targets:
            module = doc.require_module(module_id)
            ops.append(RemoveModuleOp(moduleId=module.id, reason=f"用户要求删除「{module.title}」"))
        state.proposal = self._proposal(state, ops, "删除指定模块（采纳前不会真的删）")
        return "guard_proposal"

    async def edit_reorder(self, state: AgentState) -> str | None:
        doc = self._doc(state)
        types = state.extra.get("intent", {}).get("moduleTypes") or []
        order = [m.id for m in doc.sorted_modules()]
        if not types:
            return await self._pause_for_clarification(state, "要把哪一类模块移到前面？", [])
        moving = [m.id for m in doc.sorted_modules() if m.type in types]
        rest = [m for m in order if m not in moving]
        new_order = moving + rest
        ops = [ReorderOp(order=new_order, reason=f"把{'、'.join(types)}移到最前")]
        state.proposal = self._proposal(state, ops, "调整模块顺序")
        return "guard_proposal"

    async def edit_add(self, state: AgentState) -> str | None:
        intent_info = state.extra.get("intent", {})
        types = intent_info.get("moduleTypes") or []
        if not types:
            return await self._pause_for_clarification(
                state,
                "要新增哪一类模块？",
                [{"label": get_spec(t).zh, "value": t} for t in ("project", "internship", "honor", "education")],
            )
        module_type = types[0]
        spec = get_spec(module_type)
        ops = [AddModuleOp(moduleType=module_type, data={}, reason=f"新增空白「{spec.zh}」")]
        state.proposal = self._proposal(state, ops, f"新增「{spec.zh}」模块")
        return "guard_proposal"

    async def edit_appearance(self, state: AgentState) -> str | None:
        changes = state.extra.get("appearance") or {}
        if not changes:
            return await self._pause_for_clarification(state, "想换成哪套主题或模板？", [])
        state.proposal = self._proposal(
            state, [AppearanceOp(changes=changes, reason="用户要求切换外观")], "切换外观"
        )
        return "guard_proposal"

    # ------------------------------------------------------------------
    # compress：真实版面闭环
    # ------------------------------------------------------------------
    async def compress_dispatch(self, state: AgentState) -> str | None:
        state.compress_attempts = int(state.extra.get("compressAttempts", 0))
        if state.compress_attempts >= self.settings.max_compress_attempts:
            state.extra["compressGaveUp"] = True
            state.options = [
                {"id": "keep-two-pages", "label": "保留两页", "description": "内容完整，允许两页"},
                {"id": "pick-items", "label": "我自己选删条目", "description": "逐条确认后再删"},
                {"id": "compact-template", "label": "换更紧凑的模板", "description": "改 template=modern"},
            ]
            state.message = "已尝试压缩到上限轮次，仍无法在不删事实的前提下装进一页。请从下面三种方式里选一种。"
            self._emit(state, "run.completed", {"status": "needs_decision", "options": state.options})
            return END
        return "compress_generate"

    async def compress_generate(self, state: AgentState) -> str | None:
        state.compress_attempts += 1
        state.extra["compressAttempts"] = state.compress_attempts
        doc = self._doc(state)
        density = getattr(doc.appearance, "density", "balanced")
        budget = DENSITY_BUDGETS.get(density, 760)
        if state.compress_attempts > 1:
            budget = int(budget * 0.8)
        self._emit(
            state,
            "step.started",
            {"step": "compress_generate", "attempt": state.compress_attempts, "budget": budget},
        )
        outcome = await self._tool(state, "compress_all", {"budget": budget, "scope": "all"})
        if not outcome.ok:
            state.extra["toolError"] = outcome.error
            return "handle_tool_error"
        edits = outcome.data.get("edits") or []
        if not edits:
            state.proposal = self._proposal(state, [], "当前内容已在预算内，无需压缩")
            return "request_layout"
        ops = [
            ReplaceFieldOp(
                moduleId=e["moduleId"],
                field=e["field"],
                before=e["before"],
                after=e["after"],
                reason="压缩表达，保留数字与日期",
            )
            for e in edits
        ]
        state.proposal = self._proposal(state, ops, f"压缩提案（第 {state.compress_attempts} 轮）")
        return "request_layout"

    async def request_layout(self, state: AgentState) -> str | None:
        """先校验提案，再请求浏览器真实测量。"""
        guarded = await self.guard_proposal(state)
        if guarded in {"handle_tool_error", END}:
            return guarded
        doc = self._doc(state)
        candidate_hash = doc.content_hash()
        if state.proposal and state.proposal.operations:
            outcome = apply_proposal(doc, state.proposal, allowed_tokens=fact_tokens(extract_facts(doc)))
            candidate_hash = outcome.document.content_hash()
        state.pending = PendingInterrupt(
            kind="layout",
            promptId=opaque_id("lay", 4),
            question="请在预览中测量真实版面并把结果回传（不缩放坐标系）",
            candidateHash=candidate_hash,
            resumeRevision=doc.revision,
            attempts=state.compress_attempts,
        )
        self._emit(
            state,
            "layout.required",
            {
                "promptId": state.pending.promptId,
                "candidateHash": candidate_hash,
                "minFontPt": self.settings.min_font_pt,
                "attempt": state.compress_attempts,
                # 把候选改动一并下发：浏览器要按"候选"而不是"现状"测量版面
                "proposalId": state.proposal.proposalId if state.proposal else "",
                "operations": state.proposal.op_summary() if state.proposal else [],
            },
        )
        return PAUSE

    async def resume_after_layout(self, state: AgentState) -> str | None:
        feedback = state.layout
        doc = self._doc(state)
        if feedback is None:
            state.message = "没有收到版面数据，已保留当前内容。"
            return "finalize_proposal"
        if state.proposal and state.proposal.operations and feedback.candidateHash:
            if feedback.candidateHash != state.proposal.baseHash and feedback.candidateHash != doc.content_hash():
                # 客户端测量的不是这次候选：只提示，不据此改内容
                state.warnings.append(
                    {"kind": "layout_hash_mismatch", "detail": "版面数据与当前候选不一致，请重新测量"}
                )
        if feedback.pageCount <= 1 and feedback.overflowPx <= 1:
            state.message = "已在真实版面下装进一页，请确认采纳。"
            return "finalize_proposal"
        if feedback.minFontPt and feedback.minFontPt < self.settings.min_font_pt:
            state.warnings.append(
                {
                    "kind": "font_too_small",
                    "detail": f"当前字号 {feedback.minFontPt}pt 低于下限 {self.settings.min_font_pt}pt，不接受为'已压至一页'",
                }
            )
        if state.compress_attempts >= self.settings.max_compress_attempts:
            return await self.compress_dispatch(state)
        return "compress_generate"

    # ------------------------------------------------------------------
    # job：岗位证据与匹配
    # ------------------------------------------------------------------
    async def job_search(self, state: AgentState) -> str | None:
        role = state.target_job or self._doc(state).targetJob
        if not role:
            role = _guess_role(state.instruction)
        if not role:
            return await self._pause_for_clarification(
                state, "你想了解哪个岗位的要求？告诉我岗位名称即可。", []
            )
        self._emit(state, "step.started", {"step": "search_jd", "label": f"检索「{role}」岗位证据"})
        outcome = await self._tool(state, "search_jd", {"role": role, "limit": 5})
        if not outcome.ok:
            state.extra["toolError"] = outcome.error
            return "handle_tool_error"
        jobs = outcome.data.get("jobs") or []
        state.extra["jobs"] = jobs
        state.extra["jobRole"] = role
        if outcome.data.get("isSample"):
            state.warnings.append(
                {
                    "kind": "sample_only",
                    "detail": "本次使用课程种子样本，只描述这批样本，不代表全市场统计或薪资水平",
                }
            )
        self._emit(
            state,
            "evidence.ready",
            {"provider": outcome.data.get("provider"), "count": len(jobs),
             "jobs": [{k: j[k] for k in ("id", "role", "city", "sourceName", "sourceUrl")} for j in jobs]},
        )
        if not jobs:
            state.message = "没有检索到可用岗位样本，也没有联网。可以直接把 JD 文本粘给我。"
            return "finalize_proposal"
        return "job_match"

    async def job_match(self, state: AgentState) -> str | None:
        self._emit(state, "step.started", {"step": "analyze_match", "label": "对比事实与岗位要求"})
        outcome = await self._tool(state, "analyze_match", {"target_job": state.extra.get("jobRole", "")})
        if not outcome.ok:
            state.extra["toolError"] = outcome.error
            return "handle_tool_error"
        from ..domain.jobs import DEFAULT_DISCLAIMER, MatchReport, SkillHit

        hits = [SkillHit.model_validate(h) for h in outcome.data.get("hits", [])]
        jobs = state.extra.get("jobs", [])
        state.match_report = MatchReport(
            targetJob=state.extra.get("jobRole", ""),
            hits=hits,
            citations=[
                {
                    "jobId": j["id"],
                    "role": j["role"],
                    "city": j.get("city", ""),
                    "sourceName": j.get("sourceName", ""),
                    "sourceUrl": j.get("sourceUrl", ""),
                    "fetchedAt": j.get("fetchedAt", ""),
                    "isSample": j.get("isSample", True),
                }
                for j in jobs
            ],
            sampleSize=len(jobs),
            disclaimer=DEFAULT_DISCLAIMER.format(n=len(jobs)),
            fallbackUsed=True,
            suggestions=[h.suggestion for h in hits if h.suggestion][:6],
        )
        state.message = (
            f"对照了 {len(jobs)} 条岗位样本：命中 {sum(1 for h in hits if h.category == 'matched')} 项，"
            f"部分相关 {sum(1 for h in hits if h.category == 'partial')} 项，"
            f"暂无证据 {sum(1 for h in hits if h.category == 'missing')} 项。"
        )
        self._emit(state, "evidence.ready", {"match": state.match_report.model_dump(mode="json")})
        return END

    # ------------------------------------------------------------------
    # 其它意图
    # ------------------------------------------------------------------
    async def import_pending(self, state: AgentState) -> str | None:
        return await self._pause_for_clarification(
            state,
            "导入请走「导入简历」面板：上传 PDF/DOCX 后我会拆成模块候选，你在暂存区确认后再合并。",
            [],
        )

    async def memory_pending(self, state: AgentState) -> str | None:
        return await self._pause_for_clarification(
            state,
            "记忆在「我的档案」里管理：候选需要你确认才会长期保存，随时可以更正或忘记。",
            [],
        )

    async def clarify_more(self, state: AgentState) -> str | None:
        return await self._pause_for_clarification(state, "能再说具体一点吗？", [])

    async def interview_next(self, state: AgentState) -> str | None:
        outcome = await self._tool(
            state, "interview_turn", {"topic": "项目深挖", "question": "", "answer": ""}
        )
        if not outcome.ok:
            state.extra["toolError"] = outcome.error
            return "handle_tool_error"
        state.extra["question"] = outcome.data.get("question", "")
        state.message = state.extra["question"]
        return END

    # ------------------------------------------------------------------
    # 校验、提案、收尾
    # ------------------------------------------------------------------
    async def guard_proposal(self, state: AgentState) -> str | None:
        self._emit(state, "step.started", {"step": "guard_proposal", "label": "字段权限与事实守卫"})
        proposal = state.proposal
        if proposal is None:
            return "finalize_proposal"
        doc = self._doc(state)
        allowed = fact_tokens(extract_facts(doc, status="confirmed"))
        repairs = 0
        while True:
            try:
                outcome = apply_proposal(doc, proposal, allowed_tokens=allowed)
                state.warnings.extend(outcome.warnings)
                state.extra["guard"] = outcome.guard
                self._emit(
                    state,
                    "step.completed",
                    {"step": "guard_proposal", "operations": len(proposal.operations),
                     "repairs": repairs, "warnings": len(state.warnings)},
                )
                return "finalize_proposal"
            except errors.DomainError as exc:
                if exc.code != "fact_guard_failed" or repairs >= self.settings.max_format_repairs:
                    state.error = exc.to_payload()["error"]
                    state.message = exc.message
                    self._emit(state, "run.failed", {"error": state.error})
                    return END
                # 删掉触发守卫的那条操作，其余保留（有界格式修复）
                bad_field = (exc.details or {}).get("field")
                kept = [op for op in proposal.operations if getattr(op, "field", None) != bad_field]
                if len(kept) == len(proposal.operations):
                    kept = proposal.operations[:-1]
                if not kept:
                    state.error = {
                        "code": "fact_guard_failed",
                        "message": "全部改动都触碰事实保护，已放弃生成提案",
                    }
                    state.message = "这些改动会改动事实（数字/日期），我停在这里，等你确认原始信息。"
                    self._emit(state, "run.failed", {"error": state.error})
                    return END
                repairs += 1
                state.format_repairs = repairs
                state.warnings.append(
                    {"kind": "format_repair", "detail": f"第 {repairs} 次修复：移除了触碰事实保护的操作"}
                )
                proposal = proposal.model_copy(update={"operations": kept})
                state.proposal = proposal

    async def finalize_proposal(self, state: AgentState) -> str | None:
        proposal = state.proposal
        if proposal is not None and proposal.operations:
            self._emit(
                state,
                "proposal.ready",
                {
                    "proposalId": proposal.proposalId,
                    "baseRevision": proposal.baseRevision,
                    "baseHash": proposal.baseHash,
                    "summary": proposal.summary,
                    "operations": proposal.op_summary(),
                    "warnings": state.warnings,
                    "expiresAt": proposal.expiresAt.isoformat(),
                    "clarifications": state.clarifications,
                },
            )
            state.message = state.message or f"生成了 {len(proposal.operations)} 处修改建议，采纳前不会改动你的简历。"
        elif not state.message:
            state.message = "这次没有需要改动的地方。"
        return END

    # ------------------------------------------------------------------
    async def handle_tool_error(self, state: AgentState) -> str | None:
        error = state.extra.get("toolError") or {"code": "tool_failed", "message": "工具执行失败"}
        state.error = error
        state.message = error.get("message", "工具执行失败")
        self._emit(state, "run.failed", {"error": error})
        return END


def _squash(text: str) -> str:
    return "".join(str(text).split())


def _drop_noop_ops(ops: list[Any]) -> list[Any]:
    """丢掉"改了等于没改"的操作。

    只对成对携带 before/after 的文本类操作生效（replace_field / replace_text）；
    新增、删除、排序、外观这些操作的 before/after 语义不同，一律保留。
    """
    kept: list[Any] = []
    for op in ops:
        before = getattr(op, "before", None)
        after = getattr(op, "after", None)
        if isinstance(before, str) and isinstance(after, str) and _squash(before) == _squash(after):
            continue
        kept.append(op)
    return kept


def _guess_role(text: str) -> str:
    for role in ("Python 后端", "后端", "前端", "算法", "数据分析", "测试", "运维", "产品", "机器学习"):
        if role in text:
            return role
    return ""


def build_graph(deps: WorkflowDeps) -> GraphSpec:
    nodes = WorkflowNodes(deps)
    return GraphSpec(
        name="jianmian-main",
        entry="validate_input",
        description="输入校验 → 上下文 → 意图 → 工具 → 校验 → 提案 → 用户确认",
        nodes={
            "validate_input": nodes.validate_input,
            "assemble_context": nodes.assemble_context,
            "classify": nodes.classify,
            # build
            "build_check_materials": nodes.build_check_materials,
            "build_generate": nodes.build_generate,
            # edit
            "edit_dispatch": nodes.edit_dispatch,
            "edit_rewrite": nodes.edit_rewrite,
            "edit_remove": nodes.edit_remove,
            "edit_reorder": nodes.edit_reorder,
            "edit_add": nodes.edit_add,
            "edit_appearance": nodes.edit_appearance,
            # compress
            "compress_dispatch": nodes.compress_dispatch,
            "compress_generate": nodes.compress_generate,
            "request_layout": nodes.request_layout,
            "resume_after_layout": nodes.resume_after_layout,
            # job
            "job_search": nodes.job_search,
            "job_match": nodes.job_match,
            # 其它
            "import_pending": nodes.import_pending,
            "memory_pending": nodes.memory_pending,
            "clarify_more": nodes.clarify_more,
            "interview_next": nodes.interview_next,
            # 收尾
            "guard_proposal": nodes.guard_proposal,
            "finalize_proposal": nodes.finalize_proposal,
            "handle_tool_error": nodes.handle_tool_error,
        },
    )


RESUME_NODES: dict[str, str] = {
    "clarification": "classify",
    "layout": "resume_after_layout",
}
