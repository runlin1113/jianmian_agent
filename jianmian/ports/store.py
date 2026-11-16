"""运行状态与事件存储端口（第 12.2 节）。

首版是**有界内存**实现：进程重启则活动 run 失效，前端草稿仍在本地。
多人档换 TTL 共享实现（Redis）即可，接口不变；但那时必须同时补
run 所有权、执行租约、事件序列与确认 CAS，不能只换存储。
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

RunStatus = Literal[
    "running",
    "awaiting_user",
    "awaiting_layout",
    "ready",
    "failed",
    "cancelled",
    "expired",
]

TERMINAL_STATUSES: frozenset[str] = frozenset({"ready", "failed", "cancelled", "expired"})

EVENT_TYPES: tuple[str, ...] = (
    "run.started",
    "step.started",
    "step.completed",
    "text.delta",
    "evidence.ready",
    "clarification.required",
    "layout.required",
    "proposal.ready",
    "run.completed",
    "run.failed",
    "run.cancelled",
)


class EventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    at: float = 0.0


class PendingInterrupt(BaseModel):
    """等待用户解决的中断点：澄清 / 导入确认 / 版面反馈。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["clarification", "layout", "confirmation"]
    promptId: str
    question: str = ""
    options: list[dict] = Field(default_factory=list)
    #: 候选文档哈希：回传时必须一致，防止在旧候选上做决定
    candidateHash: str = ""
    resumeRevision: int = 0
    attempts: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)


class LayoutFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pageCount: int = 1
    overflowPx: float = 0.0
    blockHeights: dict[str, float] = Field(default_factory=dict)
    fontVersion: str = ""
    rendererVersion: str = ""
    candidateHash: str = ""
    minFontPt: float = 10.5
    viewportWidth: float = 794.0


class RunRecord(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    sessionId: str
    intent: str = "edit"
    status: RunStatus = "running"
    createdAt: float = 0.0
    updatedAt: float = 0.0
    expiresAt: float = 0.0
    requestId: str = ""
    idempotencyKey: str = ""
    requestHash: str = ""
    resumeRevision: int = 0
    documentHash: str = ""
    events: list[EventRecord] = Field(default_factory=list)
    #: 工作副本（只在该 run 生命周期内存在，不作为第二份简历主数据）
    workDocument: dict[str, Any] | None = None
    pending: PendingInterrupt | None = None
    proposal: dict[str, Any] | None = None
    layout: LayoutFeedback | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    #: 本次 run 的业务快照（消息、警告、证据、匹配报告、编排元数据）。
    #: 只在该 run 生命周期内存在，run 过期即随之丢弃，不作为简历主数据。
    snapshot: dict[str, Any] = Field(default_factory=dict)
    #: 已应用的决策：proposalId → 应用回执（幂等）
    decisions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    responseSeq: int = 0

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def next_seq(self) -> int:
        return (self.events[-1].seq if self.events else 0) + 1


class RunStore(Protocol):
    def create(self, record: RunRecord) -> RunRecord: ...

    def get(self, run_id: str) -> RunRecord | None: ...

    def update(self, record: RunRecord) -> RunRecord: ...

    def delete(self, run_id: str) -> None: ...

    def find_by_idempotency(self, session_id: str, key: str) -> RunRecord | None: ...

    def purge_expired(self, now: float) -> int: ...

    def stats(self) -> dict[str, int]: ...
