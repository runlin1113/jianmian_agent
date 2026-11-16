"""记忆领域（M12，第 11 章）。

三种记忆必须分开：
- 工作上下文：一次 run 内有效，服务端只在 run 生命周期内使用；
- 长期个人记忆：`ProfileMemory`，只有用户**明确确认**后才写入；
- 面试表现：属于训练记录，不自动升级为"熟练某技术"的能力事实。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MemoryKind = Literal["fact", "project", "skill", "preference", "interest", "job_preference"]


class MemoryCandidate(BaseModel):
    """模型提出、等待用户确认的记忆候选。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: MemoryKind = "fact"
    text: str
    sourceRef: str = "conversation"
    reason: str = ""
    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    #: 置信度只作展示参考，不当作校准后的正确率（第 9.2 节同类表述）
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)

    def confirm(self, *, text: str | None = None) -> "ConfirmedFact":
        return ConfirmedFact(
            id=self.id,
            kind=self.kind,
            text=text or self.text,
            sourceRef=self.sourceRef,
            confirmedAt=datetime.now(timezone.utc),
        )


class ConfirmedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: MemoryKind = "fact"
    text: str
    sourceRef: str = "conversation"
    confirmedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    #: 用户可锁定/更正/遗忘
    locked: bool = False


class ProfileMemory(BaseModel):
    """本地长期档案。默认持久化位置是用户浏览器，服务端不落库。"""

    model_config = ConfigDict(extra="forbid")

    facts: list[ConfirmedFact] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    jobPreferences: list[str] = Field(default_factory=list)
    writingPreferences: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)

    def confirm_candidate(self, candidate: MemoryCandidate) -> "ProfileMemory":
        if any(f.id == candidate.id for f in self.facts):
            return self  # 幂等
        new = self.model_copy(deep=True)
        new.facts.append(candidate.confirm())
        if candidate.kind == "project":
            new.projects.append(candidate.text)
        elif candidate.kind == "job_preference":
            new.jobPreferences.append(candidate.text)
        elif candidate.kind == "preference":
            new.writingPreferences.append(candidate.text)
        elif candidate.kind == "interest":
            new.interests.append(candidate.text)
        return new

    def forget_fact(self, fact_id: str) -> "ProfileMemory":
        new = self.model_copy(deep=True)
        new.facts = [f for f in new.facts if f.id != fact_id]
        return new

    def relevant_for(self, *, job: str = "", limit: int = 8) -> list[ConfirmedFact]:
        """按岗位与关键词筛选，不把整份档案塞进每次 prompt（第 11.1 节）。"""
        facts = list(self.facts)
        if job:
            keys = [k for k in job.replace("/", " ").replace("·", " ").split() if k]
            facts.sort(key=lambda f: (-sum(1 for k in keys if k.lower() in f.text.lower()), -len(f.text)))
        return facts[:limit]


ForgetScope = Literal["document_only", "memory_only", "everywhere"]


def plan_forget(scope: ForgetScope, *, fact_id: str | None = None) -> dict:
    """三种"删除"是不同动作，必须解释清楚并允许一并清除（第 11.2 节）。"""
    actions: dict[ForgetScope, list[str]] = {
        "document_only": [
            "从当前简历移除该表述/模块",
            "保留记忆中的事实，后续可再次使用",
        ],
        "memory_only": [
            "停止记住这条事实（写入墓碑，避免自动复活）",
            "保留简历中已有的文字，但不再作为事实来源",
        ],
        "everywhere": [
            "从当前简历移除相关表述",
            "停止记住这条事实",
            "删除引用它的历史快照与面试记录",
            "清理本地检索索引与会话摘要",
            "说明：已导出的 PDF/JSON 无法远程删除；云模型供应商留存政策不受本系统单方面控制",
        ],
    }
    return {
        "scope": scope,
        "factId": fact_id,
        "steps": actions[scope],
        "irreversible": scope == "everywhere",
    }


def filter_by_authorization(
    memory: ProfileMemory,
    *,
    allowed_kinds: set[str] | None = None,
    include_sensitive: bool = False,
) -> ProfileMemory:
    """跨会话复用前再过一道授权过滤。"""
    allowed = allowed_kinds or {"fact", "project", "skill", "preference", "interest", "job_preference"}
    facts = [f for f in memory.facts if f.kind in allowed]
    if not include_sensitive:
        facts = [f for f in facts if "身份证" not in f.text and "银行卡" not in f.text]
    return memory.model_copy(update={"facts": facts})
