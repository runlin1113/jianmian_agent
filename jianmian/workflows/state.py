"""编排层的运行时状态。

注意：`work_document` 是**工作副本**，不是第二份简历主数据；run 结束后即丢弃。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..domain.jobs import MatchReport
from ..domain.proposals import ChangeProposal
from ..domain.resume import ResumeDocument
from ..ports.model import ModelUsage
from ..ports.store import LayoutFeedback, PendingInterrupt


@dataclass
class AgentState:
    run_id: str
    session_id: str
    instruction: str
    intent: str = "edit"
    sub_intent: str = ""
    target_job: str = ""
    document: ResumeDocument | None = None
    #: 用户已确认的长期记忆（只传相关条目，不传整份档案）
    memory_facts: list[str] = field(default_factory=list)
    #: 本会话显式提供的 BYOK 是否存在（只标记存在性，不携带值）
    has_byok: bool = False

    # 运行控制
    started_at: float = field(default_factory=time.time)
    deadline: float = 0.0
    steps: list[str] = field(default_factory=list)
    tool_calls: int = 0
    format_repairs: int = 0
    compress_attempts: int = 0
    layout_rounds: int = 0

    # 产出
    proposal: ChangeProposal | None = None
    pending: PendingInterrupt | None = None
    clarifications: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    match_report: MatchReport | None = None
    layout: LayoutFeedback | None = None
    options: list[dict] = field(default_factory=list)
    message: str = ""
    usage: ModelUsage = field(default_factory=ModelUsage)
    error: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def elapsed(self) -> float:
        return time.time() - self.started_at

    def budget_exhausted(self) -> bool:
        return self.deadline > 0 and time.time() >= self.deadline
