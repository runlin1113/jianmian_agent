"""模拟面试（M11，第 9.5 节）。

状态机：准备 → 提问 → 等待回答 → 基于回答追问 → 阶段小结 → 结束报告。
- 每轮绑定 `questionId`；提交回答必须带 `turnId`，同一 turnId 重放不会推进到下一问；
- rubric 版本化，评价维度：表达清晰度 / 具体证据 / 技术解释 / 岗位相关性；
- "项目真实性"改写为"表述可解释性 / 证据充分度"，不让模型断言造假或决定录用。
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import errors

InterviewState = Literal["preparing", "questioning", "awaiting_answer", "probing", "summarizing", "finished"]

RUBRIC_VERSION = "rubric-v1"
RUBRIC_DIMENSIONS: tuple[dict[str, str], ...] = (
    {"key": "clarity", "name": "表达清晰度", "hint": "结构清楚、信息密度合适"},
    {"key": "evidence", "name": "具体证据", "hint": "有可核对的动作、数据与结果"},
    {"key": "technical", "name": "技术解释", "hint": "能解释原理、取舍与边界"},
    {"key": "relevance", "name": "岗位相关性", "hint": "与目标岗位要求对齐"},
)

TOPIC_BANK: tuple[dict[str, str], ...] = (
    {"id": "t-intro", "name": "自我介绍", "seed": "用两分钟介绍你自己，并说明为什么适合{job}。"},
    {"id": "t-project", "name": "项目深挖", "seed": "挑一个你最想讲的项目，说明你具体负责的部分。"},
    {"id": "t-tradeoff", "name": "技术取舍", "seed": "这个项目里你做过哪些技术取舍？为什么这样选？"},
    {"id": "t-debug", "name": "问题排查", "seed": "讲一次你排查最久的问题，你的定位过程是什么？"},
    {"id": "t-collab", "name": "协作沟通", "seed": "讲一次你和他人意见不一致的经历，最后如何推进？"},
    {"id": "t-growth", "name": "学习能力", "seed": "最近半年你自学了什么？怎么验证学会了？"},
    {"id": "t-career", "name": "岗位理解", "seed": "你理解这个岗位的核心职责是什么？"},
    {"id": "t-risk", "name": "压力追问", "seed": "如果这个项目的关键指标没达成，你会先看什么？"},
)

MAX_FOLLOW_UPS_PER_TOPIC = 2


class InterviewTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turnId: str
    questionId: str
    topicId: str
    question: str
    answer: str = ""
    #: 追问轮次：0 = 主题首问，1..N = 追问
    depth: int = 0
    askedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    answeredAt: datetime | None = None
    #: 关联的简历表述（可定位到模块/字段）
    resumeRefs: list[dict] = Field(default_factory=list)


class ScoreItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str
    score: int = Field(ge=0, le=5)
    basis: str = ""
    advice: str = ""


class InterviewReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessionId: str
    rubricVersion: str = RUBRIC_VERSION
    scores: list[ScoreItem] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    #: 可回写为简历修改提案的素材（必须经用户确认）
    memoryCandidates: list[dict] = Field(default_factory=list)
    proposalHints: list[dict] = Field(default_factory=list)
    disclaimer: str = "评分仅基于本次问答文本，用于练习反馈，不构成录用判断。"


class InterviewSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: "iv-" + secrets.token_hex(5))
    resumeId: str
    resumeRevision: int
    targetJob: str = ""
    state: InterviewState = "preparing"
    rubricVersion: str = RUBRIC_VERSION
    topicIds: list[str] = Field(default_factory=list)
    currentTopicIndex: int = 0
    followUps: int = 0
    turns: list[InterviewTurn] = Field(default_factory=list)
    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finishedAt: datetime | None = None
    report: InterviewReport | None = None

    # ---- 状态迁移 ---------------------------------------------------------
    @property
    def current_turn(self) -> InterviewTurn | None:
        return self.turns[-1] if self.turns else None

    def start(self, topics: list[str] | None = None) -> "InterviewSession":
        if self.state != "preparing":
            raise errors.contract_error("会话已经开始")
        chosen = topics or [t["id"] for t in TOPIC_BANK][:6]
        if not chosen:
            raise errors.contract_error("至少需要一个面试主题")
        new = self.model_copy(deep=True)
        new.topicIds = chosen[: len(TOPIC_BANK)]
        new.state = "questioning"
        return new

    def ask(self, question: str, *, resume_refs: list[dict] | None = None) -> "InterviewSession":
        """开出一个新问题（首问或追问），并进入等待回答。"""
        if self.state not in {"questioning", "awaiting_answer", "probing", "summarizing"}:
            raise errors.contract_error(f"当前状态 {self.state} 不能提问")
        if self.state == "awaiting_answer" and self.current_turn and not self.current_turn.answer:
            raise errors.contract_error("上一问还没有回答")
        new = self.model_copy(deep=True)
        topic_id = new.topicIds[min(new.currentTopicIndex, len(new.topicIds) - 1)]
        depth = new.followUps
        new.turns.append(
            InterviewTurn(
                turnId="turn-" + secrets.token_hex(4),
                questionId=f"q-{secrets.token_hex(3)}",
                topicId=topic_id,
                question=question,
                depth=depth,
                resumeRefs=resume_refs or [],
            )
        )
        new.state = "awaiting_answer"
        return new

    def answer(self, turn_id: str, text: str) -> "InterviewSession":
        """提交回答。turnId 不匹配 → 409（防止重试重复推进）。"""
        if self.state != "awaiting_answer":
            raise errors.contract_error(f"当前状态 {self.state} 不接受回答")
        turn = self.current_turn
        if turn is None or turn.turnId != turn_id:
            raise errors.DomainError(
                "turn_conflict",
                "回答与当前轮次不匹配，可能已在其他标签页提交",
                status=409,
                details={"expected": turn.turnId if turn else None},
            )
        if turn.answer:
            return self  # 幂等重放
        if not text.strip():
            raise errors.contract_error("回答不能为空")
        if len(text) > 4000:
            raise errors.contract_error("回答过长（上限 4000 字）")
        new = self.model_copy(deep=True)
        new.turns[-1].answer = text.strip()
        new.turns[-1].answeredAt = datetime.now(timezone.utc)
        new.state = "probing"
        return new

    def next_question_or_advance(self) -> "InterviewSession":
        """决定继续追问还是进入下一主题。追问次数有上限。"""
        new = self.model_copy(deep=True)
        if new.followUps < MAX_FOLLOW_UPS_PER_TOPIC:
            new.followUps += 1
            new.state = "questioning"
            return new
        new.followUps = 0
        new.currentTopicIndex += 1
        if new.currentTopicIndex >= len(new.topicIds):
            new.state = "summarizing"
            return new
        new.state = "questioning"
        return new

    def finish(self, report: InterviewReport) -> "InterviewSession":
        new = self.model_copy(deep=True)
        new.state = "finished"
        new.finishedAt = datetime.now(timezone.utc)
        new.report = report
        return new

    def progress(self) -> dict:
        answered = sum(1 for t in self.turns if t.answer)
        return {
            "topicIndex": self.currentTopicIndex,
            "topicTotal": len(self.topicIds),
            "answered": answered,
            "state": self.state,
            "rubricVersion": self.rubricVersion,
        }


def build_report(session: InterviewSession) -> InterviewReport:
    """基于回答文本做**可解释**的规则评分，并把依据原句带出来。

    真实生成质量指标必须来自真实模型（第 16 章）；这里给出确定性的基线，
    模型只用来补充 advice 文案，不改变分数算法。
    """
    answered = [t for t in session.turns if t.answer]
    scores: list[ScoreItem] = []
    highlights: list[str] = []
    gaps: list[str] = []

    def _score(dim: str, value: int, basis: str, advice: str) -> ScoreItem:
        return ScoreItem(dimension=dim, score=max(0, min(5, value)), basis=basis, advice=advice)

    if not answered:
        return InterviewReport(
            sessionId=session.id,
            scores=[_score(d["key"], 0, "没有回答记录", "先完成至少两轮问答再生成报告") for d in RUBRIC_DIMENSIONS],
            gaps=["本次没有有效回答"],
        )

    avg_len = sum(len(t.answer) for t in answered) / len(answered)
    # 表达清晰度：看结构词与长度区间
    structure_hits = sum(
        1
        for t in answered
        if any(k in t.answer for k in ("首先", "其次", "最后", "1.", "2.", "背景", "结果"))
    )
    clarity = min(5, 2 + structure_hits // max(1, len(answered)) + (1 if 60 <= avg_len <= 400 else 0))
    scores.append(
        _score(
            "clarity",
            clarity,
            f"平均回答 {int(avg_len)} 字，{structure_hits}/{len(answered)} 轮出现结构性表述",
            "用「背景—行动—结果」三段作答，控制在 2 分钟内",
        )
    )

    # 具体证据：数字/结果词
    evidence_turns = [t for t in answered if any(ch.isdigit() for ch in t.answer)]
    evidence = min(5, 1 + len(evidence_turns))
    scores.append(
        _score(
            "evidence",
            evidence,
            f"{len(evidence_turns)}/{len(answered)} 轮回答含可核对数字",
            "补一条能给出具体数字或可验证结果的事例",
        )
    )
    if evidence_turns:
        highlights.append(f"有证据的回答：{evidence_turns[0].answer[:60]}…")
    else:
        gaps.append("回答里没有出现任何可核对的数字或结果")

    # 技术解释：原理/取舍词
    tech_turns = [
        t for t in answered if any(k in t.answer for k in ("原理", "因为", "取舍", "复杂度", "架构", "索引", "性能"))
    ]
    scores.append(
        _score(
            "technical",
            min(5, 1 + len(tech_turns)),
            f"{len(tech_turns)}/{len(answered)} 轮解释到原理或取舍",
            "对关键选型补一句「为什么不用另一个方案」",
        )
    )

    # 岗位相关性：是否提到目标岗位关键词
    job_keys = [k for k in (session.targetJob or "").replace("/", " ").split() if k]
    relevant = [
        t for t in answered if job_keys and any(k.lower() in t.answer.lower() for k in job_keys)
    ]
    scores.append(
        _score(
            "relevance",
            min(5, 2 + len(relevant)),
            f"{len(relevant)}/{len(answered)} 轮回答直接呼应「{session.targetJob or '目标岗位'}」",
            "把项目结果翻译成岗位关心的业务指标",
        )
    )

    memory_candidates = [
        {
            "kind": "fact",
            "text": t.answer[:120],
            "sourceRef": f"interview:{session.id}:{t.turnId}",
            "reason": "面试中补充的新事实，确认后可写入长期档案",
        }
        for t in answered[:3]
    ]
    proposal_hints = [
        {
            "moduleType": "project",
            "field": "desc",
            "reason": "把面试中讲清楚的细节补回简历",
            "sourceTurnId": t.turnId,
        }
        for t in answered[:2]
    ]
    return InterviewReport(
        sessionId=session.id,
        scores=scores,
        highlights=highlights,
        gaps=gaps or ["暂无明显缺口，可继续加大追问深度"],
        memoryCandidates=memory_candidates,
        proposalHints=proposal_hints,
    )
