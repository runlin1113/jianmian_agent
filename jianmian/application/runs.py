"""Run 用例服务（第 12 章）。

职责边界（很重要）：
- **不保存简历主数据**：只保存本次 run 的工作副本，run 结束/过期即丢；
- **不做确定性判断**：意图、提案、事实守卫都在 workflows/domain 里；
- **不信任前端传来的版本**：提案采纳前重查 revision、哈希、到期时间与 run 所有权。

状态机：running → awaiting_user / awaiting_layout → ready / failed / cancelled / expired。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..domain import errors
from ..domain.facts import extract_facts, fact_tokens
from ..domain.proposals import ChangeProposal, apply_proposal
from ..domain.resume import ResumeDocument, validate_document
from ..ports.store import EventRecord, LayoutFeedback, PendingInterrupt, RunRecord
from ..security.ids import idempotency_digest, opaque_id
from ..workflows.graph import WorkflowDeps
from ..workflows.orchestrator import Orchestrator
from ..workflows.state import AgentState
from .container import AppContainer
from .events import EventBroker

#: 单个指令的字符上限，与节点校验保持一致
MAX_INSTRUCTION_CHARS = 4000


class RunStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=1, max_length=MAX_INSTRUCTION_CHARS)
    document: dict[str, Any]
    targetJob: str = Field(default="", max_length=80)
    memoryFacts: list[str] = Field(default_factory=list, max_length=20)
    intentHint: str | None = None
    idempotencyKey: str | None = Field(default=None, max_length=80)


class Decision(BaseModel):
    """用户决定：澄清回答 / 版面反馈 / 提案采纳。"""

    model_config = ConfigDict(extra="forbid")

    kind: str
    promptId: str | None = None
    answer: str | None = Field(default=None, max_length=4000)
    optionValue: str | None = Field(default=None, max_length=200)
    layout: dict[str, Any] | None = None
    action: str | None = None  # accept / reject
    document: dict[str, Any] | None = None
    #: 逐项采纳：只应用这些下标的操作；None 表示整批采纳
    opIndexes: list[int] | None = Field(default=None, max_length=60)


@dataclass
class _Execution:
    """一次执行的上下文，避免把可变状态塞回 RunRecord。

    `byok_key` 只在这里短暂存在，不写日志、不落存储、不进事件。
    """

    run_id: str
    state: AgentState
    byok: bool
    byok_key: str | None = None
    start_at: str | None = None


class RunService:
    def __init__(self, container: AppContainer, broker: EventBroker | None = None) -> None:
        self.container = container
        self.settings: Settings = container.settings
        self.store = container.store
        self.broker = broker or EventBroker()
        self._tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------
    async def create(
        self,
        session_id: str,
        req: RunStart,
        *,
        byok_key: str | None = None,
        request_id: str = "",
    ) -> RunRecord:
        document = validate_document(req.document)  # 422：结构不合法直接拒绝
        digest = self._request_digest(req, has_byok=bool(byok_key))
        key = (req.idempotencyKey or "").strip()

        if key:
            existing = self.store.find_by_idempotency(session_id, key)
            if existing is not None:
                if existing.requestHash != digest:
                    raise errors.DomainError(
                        "idempotency_conflict",
                        "同一幂等键提交了不同内容；请为新请求生成新的幂等键",
                        status=409,
                    )
                return existing  # 幂等重放：返回原 run，不重复执行

        now = time.time()
        record = RunRecord(
            id=opaque_id("run", 6),
            sessionId=session_id,
            status="running",
            createdAt=now,
            updatedAt=now,
            expiresAt=now + self.settings.run_ttl_seconds,
            requestId=request_id,
            idempotencyKey=key,
            requestHash=digest,
            resumeRevision=document.revision,
            documentHash=document.content_hash(),
            workDocument=document.model_dump(mode="json"),
        )
        record.snapshot = {
            "instruction": req.instruction,
            "targetJob": req.targetJob,
            "memoryFacts": req.memoryFacts[:16],
            "warnings": [],
            "message": "",
            "evidence": [],
            "options": [],
            "clarifications": [],
        }
        self.store.create(record)
        self._launch(
            _Execution(
                run_id=record.id,
                state=AgentState(
                    run_id=record.id,
                    session_id=session_id,
                    instruction=req.instruction,
                    target_job=req.targetJob,
                    document=document,
                    memory_facts=req.memoryFacts[:16],
                    has_byok=bool(byok_key),
                ),
                byok=bool(byok_key),
                byok_key=byok_key,
            )
        )
        return self.store.get(record.id) or record

    def _request_digest(self, req: RunStart, *, has_byok: bool) -> str:
        payload = json.dumps(
            {
                "instruction": req.instruction,
                "targetJob": req.targetJob,
                "documentHash": hashlib.sha256(
                    json.dumps(req.document, ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest(),
                "memoryFacts": req.memoryFacts,
                "hasByok": has_byok,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return idempotency_digest(payload, self.settings.session_secret)

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------
    def _launch(self, execution: _Execution) -> None:
        run_id = execution.run_id
        task = asyncio.get_event_loop().create_task(self._execute(execution))
        self._tasks[run_id] = task
        task.add_done_callback(lambda t: self._tasks.pop(run_id, None))

    async def _execute(self, execution: _Execution) -> None:
        state = execution.state
        run_id = execution.run_id
        state.deadline = state.started_at + self.settings.run_budget_seconds
        state.extra["emit"] = lambda event, data: self._emit(run_id, event, data)
        self._emit(run_id, "run.started", {"intent": state.intent, "resumed": bool(state.steps)})

        try:
            model = self.container.model_for(execution.byok_key)
        except errors.DomainError as exc:
            state.error = exc.to_payload()["error"]
            self._finish(run_id, state, status="failed")
            return

        deps = WorkflowDeps(
            settings=self.settings,
            model=model,
            job_provider=self.container.job_provider,
            budget=self.container.budget_for(byok=execution.byok),
            registry=self.container.registry,  # type: ignore[arg-type]
        )
        try:
            await Orchestrator(deps, self.settings).run(state, start_at=execution.start_at)
        except errors.DomainError as exc:
            state.error = exc.to_payload()["error"]
        except asyncio.CancelledError:
            self._finish(run_id, state, status="cancelled")
            raise
        except Exception as exc:  # 不外泄堆栈
            state.error = {
                "code": "internal_error",
                "message": "执行过程中出现内部错误，已停止本次任务",
                "retryable": True,
                "detail": type(exc).__name__,
            }
        self._finish(run_id, state)

    def _finish(self, run_id: str, state: AgentState, *, status: str | None = None) -> None:
        record = self.store.get(run_id)
        if record is None:
            return
        if status is None:
            if state.error:
                status = "failed"
            elif state.pending is not None:
                status = "awaiting_layout" if state.pending.kind == "layout" else "awaiting_user"
            elif state.proposal is not None and state.proposal.operations:
                # 提案已生成但未采纳：这是"等用户确认"，不是"任务已完成"
                status = "awaiting_user"
            else:
                status = "ready"
        record.status = status  # type: ignore[assignment]
        record.updatedAt = time.time()
        if state.document is not None:
            record.workDocument = state.document.model_dump(mode="json")
            record.resumeRevision = state.document.revision
            record.documentHash = state.document.content_hash()
        if state.proposal is not None:
            record.proposal = state.proposal.model_dump(mode="json")
        if state.pending is not None and state.pending.kind == "clarification":
            # 记录暂停节点：恢复时据此决定"重跑哪一步"，而不是猜
            state.pending.payload = {**state.pending.payload, "resumeNode": state.steps[-1] if state.steps else ""}
            record.pending = state.pending
        elif state.pending is not None:
            record.pending = state.pending
        else:
            record.pending = None
        if state.layout is not None:
            record.layout = state.layout
        record.usage = state.usage.model_dump(mode="json") if hasattr(state.usage, "model_dump") else {}
        record.error = state.error
        record.snapshot = {
            **(record.snapshot or {}),
            "intent": state.intent,
            "subIntent": state.sub_intent,
            "targetJob": state.target_job,
            "warnings": state.warnings[-30:],
            "message": state.message,
            "evidence": state.evidence[-10:],
            "options": state.options,
            "clarifications": state.clarifications,
            "steps": state.steps,
            "matchReport": state.match_report.model_dump(mode="json") if state.match_report else None,
            "compressAttempts": state.compress_attempts,
            "toolCalls": state.tool_calls,
            "elapsedMs": int(state.elapsed() * 1000),
        }
        record.snapshot.pop("__model__", None)
        self.store.update(record)
        if status in {"ready", "failed", "cancelled"}:
            event = {"ready": "run.completed", "failed": "run.failed", "cancelled": "run.cancelled"}[status]
            already = any(e.type == event for e in record.events)
            if not already:
                self._emit(run_id, event, {"status": status, "error": state.error})

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def _emit(self, run_id: str, event: str, data: dict) -> None:
        record = self.store.get(run_id)
        if record is None:
            return
        payload = _jsonable(data)
        record.events.append(
            EventRecord(seq=record.next_seq(), type=event, data=payload, at=time.time())
        )
        if len(record.events) > self.settings.max_events_per_run:
            record.events = record.events[-self.settings.max_events_per_run :]
        record.updatedAt = time.time()
        if event == "clarification.required":
            record.status = "awaiting_user"
        elif event == "layout.required":
            record.status = "awaiting_layout"
        self.store.update(record)
        self.broker.publish(run_id)

    async def events_since(self, run_id: str, session_id: str, after_seq: int):
        """SSE 生成器：按 seq 续传，终态后自动结束。"""
        record = self._require(run_id, session_id)
        last = max(0, after_seq)
        idle = 0.0
        while True:
            record = self.store.get(run_id)
            if record is None:
                yield {"type": "expired", "seq": last, "data": {"code": "run_expired"}}
                return
            pending = [e for e in record.events if e.seq > last]
            for e in pending:
                last = e.seq
                yield {"type": e.type, "seq": e.seq, "data": e.data, "at": e.at}
            if pending:
                idle = 0.0
            if record.is_terminal and not pending:
                return
            # 等用户操作时不占着连接：先把事件推完，然后正常结束，
            # 客户端做完决策后带 Last-Event-ID 重连续传即可。
            if record.status in {"awaiting_user", "awaiting_layout"} and not pending:
                return
            if record.expiresAt and time.time() > record.expiresAt:
                yield {"type": "expired", "seq": last, "data": {"code": "run_expired"}}
                return
            version = self.broker.version(run_id)
            await self.broker.wait(run_id, since_version=version, timeout=15.0)
            idle += 15.0
            if idle >= 60.0:
                idle = 0.0
                yield {"type": "heartbeat", "seq": last, "data": {}}

    # ------------------------------------------------------------------
    # 决策与恢复
    # ------------------------------------------------------------------
    async def decide(
        self,
        run_id: str,
        session_id: str,
        decision: Decision,
        *,
        byok_key: str | None = None,
    ) -> dict[str, Any]:
        record = self._require(run_id, session_id)
        if record.is_terminal:
            # 幂等：已采纳过的提案可以重复取回结果，其余终态拒绝
            if decision.kind == "proposal" and record.decisions:
                done = record.decisions.get(decision.action or "") or next(iter(record.decisions.values()))
                return {"runId": record.id, "status": record.status, "applied": bool(done.get("applied")),
                        "document": done.get("document"), "replayed": True}
            raise errors.DomainError("run_finished", "该任务已结束，请重新发起", status=409)
        if decision.kind == "proposal":
            return self._decide_proposal(record, decision)
        if decision.kind == "clarification":
            return await self._decide_clarification(record, decision, byok_key=byok_key)
        if decision.kind == "layout":
            return await self._decide_layout(record, decision, byok_key=byok_key)
        raise errors.contract_error(f"未知的决策类型：{decision.kind}")

    def _decide_proposal(self, record: RunRecord, decision: Decision) -> dict[str, Any]:
        if not record.proposal:
            raise errors.DomainError("no_proposal", "本次任务没有待确认的提案", status=409)
        proposal = ChangeProposal.model_validate(record.proposal)
        subset_note = ""
        if decision.action and decision.action.lower() == "accept" and decision.opIndexes is not None:
            chosen = [i for i in decision.opIndexes if 0 <= i < len(proposal.operations)]
            if not chosen:
                raise errors.contract_error("没有选中任何修改项")
            subset_note = "#" + ",".join(str(i) for i in sorted(set(chosen)))
            proposal = proposal.model_copy(
                update={"operations": [proposal.operations[i] for i in sorted(set(chosen))]}
            )
        cache_key = proposal.proposalId + subset_note
        cached = record.decisions.get(cache_key)
        if cached:
            return {"runId": record.id, "status": record.status, "applied": bool(cached.get("applied")),
                    "document": cached.get("document"), "warnings": cached.get("warnings", []), "replayed": True}

        action = (decision.action or "").lower()
        if action not in {"accept", "reject"}:
            raise errors.contract_error("action 必须是 accept 或 reject")

        if proposal.expiresAt and proposal.expiresAt < datetime.now(timezone.utc):
            raise errors.proposal_expired(proposal.proposalId)

        raw_doc = decision.document or record.workDocument
        if raw_doc is None:
            raise errors.DomainError("document_missing", "缺少文档，无法校验提案", status=422)
        document = validate_document(raw_doc)

        # 三重一致：版本、哈希、提案基准
        if document.revision != proposal.baseRevision:
            raise errors.version_conflict(proposal.baseRevision, document.revision)
        if document.content_hash() != proposal.baseHash:
            raise errors.DomainError(
                "candidate_mismatch",
                "当前文档与提案生成时的候选不一致（可能已在其他标签页编辑），请重新生成提案",
                status=409,
                retryable=True,
            )

        if action == "reject":
            record.decisions[cache_key] = {"applied": False, "at": time.time()}
            self.store.update(record)
            return {"runId": record.id, "status": record.status, "applied": False, "document": None}

        allowed = fact_tokens(extract_facts(document, status="confirmed"))
        outcome = apply_proposal(document, proposal, allowed_tokens=allowed)  # 失败则整批不写
        applied = outcome.document.model_dump(mode="json")
        record.decisions[cache_key] = {
            "applied": True,
            "at": time.time(),
            "revision": outcome.document.revision,
            "hash": outcome.document.content_hash(),
            "document": applied,
            "warnings": outcome.warnings,
        }
        record.status = "ready"
        record.workDocument = applied
        self.store.update(record)
        self._emit(record.id, "run.completed", {"status": "ready", "applied": True,
                                                "revision": outcome.document.revision})
        return {
            "runId": record.id,
            "status": "ready",
            "applied": True,
            "revision": outcome.document.revision,
            "hash": outcome.document.content_hash(),
            "document": applied,
            "warnings": outcome.warnings,
        }

    async def _decide_clarification(
        self, record: RunRecord, decision: Decision, *, byok_key: str | None = None
    ) -> dict[str, Any]:
        pending = record.pending
        if pending is None or pending.kind != "clarification":
            raise errors.DomainError("no_pending", "当前没有待回答的问题", status=409)
        if decision.promptId and decision.promptId != pending.promptId:
            raise errors.DomainError(
                "prompt_mismatch", "回答对应的问题已被替换，请刷新后再答", status=409
            )
        answer = (decision.optionValue or decision.answer or "").strip()
        if not answer:
            raise errors.contract_error("回答不能为空")

        state = self._rebuild_state(record)
        resume_node = pending.payload.get("resumeNode", "")
        chosen: dict[str, Any] | None = None
        for option in pending.options:
            if answer in {str(option.get("value")), str(option.get("moduleId")), str(option.get("label"))}:
                chosen = option
                break

        if chosen and chosen.get("moduleId"):
            # 歧义消解：直接把目标模块交给 edit_dispatch，不再重新分类
            intent = dict(state.extra.get("intent") or {})
            intent["needsClarification"] = False
            state.extra["intent"] = intent
            state.extra["targets"] = [chosen["moduleId"]]
            start_at = "edit_dispatch"
        elif chosen and chosen.get("intent"):
            # 用户选了业务入口：采信选择，不重新猜
            state.extra["forcedIntent"] = chosen["intent"]
            state.instruction = f"{state.instruction}\n补充说明：{chosen.get('label', '')}"[:MAX_INSTRUCTION_CHARS]
            start_at = "classify"
        elif resume_node == "build_check_materials" and not state.target_job:
            state.target_job = answer[:80]
            start_at = "build_check_materials"
        else:
            state.instruction = f"{state.instruction}\n补充说明：{answer}"[:MAX_INSTRUCTION_CHARS]
            start_at = "classify"

        record.pending = None
        record.status = "running"
        self.store.update(record)
        self._launch(_Execution(run_id=record.id, state=state, byok=bool(byok_key),
                                byok_key=byok_key, start_at=start_at))
        return {"runId": record.id, "status": "running", "resumeAt": start_at}

    async def _decide_layout(
        self, record: RunRecord, decision: Decision, *, byok_key: str | None = None
    ) -> dict[str, Any]:
        pending = record.pending
        if pending is None or pending.kind != "layout":
            raise errors.DomainError("no_pending", "当前没有待回传的版面数据", status=409)
        if not decision.layout:
            raise errors.contract_error("缺少版面数据")
        try:
            feedback = LayoutFeedback.model_validate(decision.layout)
        except Exception as exc:  # pydantic 校验失败
            raise errors.contract_error(f"版面数据不合法：{exc}") from exc
        if pending.candidateHash and feedback.candidateHash and feedback.candidateHash != pending.candidateHash:
            raise errors.DomainError(
                "candidate_mismatch",
                "版面数据测的不是本次候选，请重新测量后回传",
                status=409,
                retryable=True,
            )
        state = self._rebuild_state(record)
        state.layout = feedback
        state.has_byok = bool(byok_key)
        record.pending = None
        record.status = "running"
        self.store.update(record)
        self._launch(_Execution(run_id=record.id, state=state, byok=bool(byok_key),
                                byok_key=byok_key, start_at="resume_after_layout"))
        return {"runId": record.id, "status": "running", "resumeAt": "resume_after_layout"}

    def _rebuild_state(self, record: RunRecord) -> AgentState:
        snapshot = record.snapshot or {}
        doc = ResumeDocument.model_validate(record.workDocument) if record.workDocument else None
        state = AgentState(
            run_id=record.id,
            session_id=record.sessionId,
            instruction=snapshot.get("instruction", ""),
            intent=snapshot.get("intent", "edit") or "edit",
            sub_intent=snapshot.get("subIntent", ""),
            target_job=snapshot.get("targetJob", ""),
            document=doc,
            memory_facts=snapshot.get("memoryFacts", []) or [],
        )
        state.extra.update(
            {k: v for k, v in snapshot.items()
             if k in {"intent", "targets", "field", "appearance", "jobs", "jobRole",
                      "candidateHash", "candidateRevision", "moduleIndex", "facts"}}
        )
        if record.proposal:
            state.proposal = ChangeProposal.model_validate(record.proposal)
        state.compress_attempts = int(snapshot.get("compressAttempts", 0))
        return state

    # ------------------------------------------------------------------
    # 查询与维护
    # ------------------------------------------------------------------
    def _require(self, run_id: str, session_id: str) -> RunRecord:
        record = self.store.get(run_id)
        if record is None:
            raise errors.not_found("任务")
        if record.sessionId != session_id:
            raise errors.forbidden("该任务属于其他会话")
        return record

    def get(self, run_id: str, session_id: str) -> RunRecord:
        return self._require(run_id, session_id)

    def cancel(self, run_id: str, session_id: str) -> RunRecord:
        record = self._require(run_id, session_id)
        task = self._tasks.pop(run_id, None)
        if task and not task.done():
            task.cancel()
        if not record.is_terminal:
            record.status = "cancelled"
            record.pending = None
            record.updatedAt = time.time()
            self.store.update(record)
            self._emit(run_id, "run.cancelled", {"reason": "user_cancelled"})
        return record

    def purge_expired(self) -> dict[str, int]:
        """真实的后台清理，不只是隐私声明（第 13.2 节）。"""
        removed = self.store.purge_expired(time.time())
        for run_id in list(self._tasks):
            record = self.store.get(run_id)
            if record is None or record.is_terminal:
                self.broker.forget(run_id)
        return {"purged": removed, **self.store.stats(), **self.broker.stats()}

    def shutdown(self) -> None:
        for run_id, task in list(self._tasks.items()):
            if not task.done():
                task.cancel()
            self.broker.forget(run_id)
        self._tasks.clear()


def public_view(record: RunRecord) -> dict[str, Any]:
    """下发给前端的 run 快照：不含工作副本全文，避免把服务端当第二份主数据。"""
    snapshot = record.snapshot or {}
    return {
        "runId": record.id,
        "status": record.status,
        "intent": snapshot.get("intent", record.intent),
        "subIntent": snapshot.get("subIntent", ""),
        "revision": record.resumeRevision,
        "documentHash": record.documentHash,
        "createdAt": record.createdAt,
        "expiresAt": record.expiresAt,
        "requestId": record.requestId,
        "pending": record.pending.model_dump(mode="json") if record.pending else None,
        "proposal": record.proposal,
        "message": snapshot.get("message", ""),
        "warnings": snapshot.get("warnings", []),
        "clarifications": snapshot.get("clarifications", []),
        "options": snapshot.get("options", []),
        "steps": snapshot.get("steps", []),
        "matchReport": snapshot.get("matchReport"),
        "layout": record.layout.model_dump(mode="json") if record.layout else None,
        "usage": record.usage,
        "error": record.error,
        "lastSeq": record.events[-1].seq if record.events else 0,
    }


def _jsonable(value: Any) -> Any:
    """事件数据必须是可序列化的纯数据；把 pydantic 对象摊平。"""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value[:50]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
