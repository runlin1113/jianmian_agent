"""多轮面试用例（M12）。

边界：
- 面试表现**不会**自动升级成"熟练某技术"的能力事实（第 11.1 节）；
- 评分是规则基线 + 可引用的原句，模型只补建议文案，不改分数算法；
- 轮次用 turnId 对齐，重复提交返回 409 而不是重复推进。
"""

from __future__ import annotations

import time
from typing import Any

from ..domain import errors
from ..domain.interview import (
    MAX_FOLLOW_UPS_PER_TOPIC,
    TOPIC_BANK,
    InterviewReport,
    InterviewSession,
    build_report,
)
from ..domain.resume import ResumeDocument
from ..ports.model import ModelRequest, estimate_tokens
from .container import AppContainer


class InterviewService:
    def __init__(self, container: AppContainer) -> None:
        self.container = container
        self._sessions: dict[str, tuple[str, InterviewSession, float]] = {}
        self._ttl = 3600.0
        self._max = 300

    async def create(
        self,
        session_id: str,
        *,
        document: ResumeDocument,
        target_job: str,
        topics: list[str] | None = None,
        byok_key: str | None = None,
    ) -> tuple[InterviewSession, str]:
        session = InterviewSession(
            resumeId=document.id,
            resumeRevision=document.revision,
            targetJob=target_job,
        ).start(topics)
        session, question = await self._ask_next(session, document, byok_key=byok_key)
        self._save(session_id, session)
        return session, question

    async def answer(
        self,
        session_id: str,
        interview_id: str,
        *,
        turn_id: str,
        text: str,
        byok_key: str | None = None,
    ) -> dict[str, Any]:
        session = self._require(session_id, interview_id)
        session = session.answer(turn_id, text)  # turnId 不匹配 → 409
        if session.state == "probing":
            session = session.next_question_or_advance()
        if session.state == "summarizing":
            report = build_report(session)
            session = session.finish(report)
            self._save(session_id, session)
            return {"finished": True, "session": self.public(session), "report": report.model_dump(mode="json")}

        document = self._document_stub(session)
        session, question = await self._ask_next(session, document, byok_key=byok_key)
        self._save(session_id, session)
        return {"finished": False, "session": self.public(session), "question": question}

    def get(self, session_id: str, interview_id: str) -> InterviewSession:
        return self._require(session_id, interview_id)

    def report(self, session_id: str, interview_id: str) -> InterviewReport:
        session = self._require(session_id, interview_id)
        if session.report is None:
            raise errors.DomainError("report_not_ready", "还没有完成所有主题，无法生成复盘", status=409)
        return session.report

    # ------------------------------------------------------------------
    async def _ask_next(
        self, session: InterviewSession, document: ResumeDocument, *, byok_key: str | None
    ) -> tuple[InterviewSession, str]:
        topic = TOPIC_BANK[min(session.currentTopicIndex, len(TOPIC_BANK) - 1)]
        seed = topic["seed"].replace("{job}", session.targetJob or "这个岗位")
        refs = self._resume_refs(document, topic["id"])
        spans = "\n".join(r["text"] for r in refs)[:1200]

        question = ""
        previous = session.turns[-1] if session.turns else None
        if session.followUps and previous is not None and previous.answer:
            # 追问要基于上一轮回答，而不是换一个主题重开
            question = await self._model_call(
                "interview_followup",
                {"question": previous.question, "answer": previous.answer[:1500]},
                byok_key=byok_key,
                max_tokens=300,
            )
            if not question:
                question = f"你刚才提到「{previous.answer[:24]}」，能展开讲讲你具体做了什么、结果如何吗？"
        else:
            question = await self._model_call(
                "interview_question",
                {"target_job": session.targetJob, "topic": topic["name"], "resume_spans": spans},
                byok_key=byok_key,
                max_tokens=400,
            ) or seed
        return session.ask(question[:400], resume_refs=refs), question

    async def _model_call(
        self, task: str, inputs: dict, *, byok_key: str | None, max_tokens: int
    ) -> str:
        """走预算的结构化调用；任何失败都降级为规则问题，不向用户报错。"""
        try:
            model = self.container.model_for(byok_key)
        except Exception:
            return ""
        subject = "interview"
        budget = self.container.budget_for(byok=bool(byok_key))
        estimated = estimate_tokens(str(inputs)) + max_tokens
        lease = budget.reserve(subject, estimated)
        if lease is None:
            return ""
        try:
            result = await model.generate(
                ModelRequest(task=task, inputs=inputs, maxTokens=max_tokens)
            )
        except Exception:
            budget.release(lease)
            return ""
        if not result.ok or not result.structured:
            budget.settle(lease, 0)
            return ""
        budget.settle(lease, result.usage.totalTokens or estimated)
        return str(result.structured.get("question") or "").strip()

    def _resume_refs(self, document: ResumeDocument, topic_id: str) -> list[dict]:
        """只挑与该主题相关的 1—2 句原文，作为追问锚点。"""
        keywords = {
            "t-project": ("项目", "开发", "实现"),
            "t-tradeoff": ("选型", "技术", "架构"),
            "t-debug": ("问题", "排查", "修复"),
            "t-collab": ("团队", "协作", "沟通"),
            "t-growth": ("学习", "自学", "课程"),
            "t-career": ("岗位", "职责", "实习"),
        }.get(topic_id, ())
        refs: list[dict] = []
        for _, module_type, _, text in document.text_blocks():
            if not text.strip():
                continue
            if not keywords or any(key.lower() in text.lower() for key in keywords):
                refs.append({"moduleType": module_type, "text": text.strip()[:120]})
            if len(refs) >= 2:
                break
        return refs

    def _document_stub(self, session: InterviewSession) -> ResumeDocument:
        """面试只需要引用原文；过期后不再回读整份文档，用空壳保证不会误用旧内容。"""
        return ResumeDocument(id=session.resumeId, revision=session.resumeRevision, modules=[])

    def _save(self, session_id: str, session: InterviewSession) -> None:
        if len(self._sessions) >= self._max:
            oldest = min(self._sessions.items(), key=lambda kv: kv[1][2])
            self._sessions.pop(oldest[0], None)
        self._sessions[session.id] = (session_id, session, time.time() + self._ttl)

    def _require(self, session_id: str, interview_id: str) -> InterviewSession:
        entry = self._sessions.get(interview_id)
        if entry is None or entry[2] < time.time():
            raise errors.not_found("面试会话")
        if entry[0] != session_id:
            raise errors.forbidden("该面试会话属于其他会话")
        return entry[1]

    def public(self, session: InterviewSession) -> dict[str, Any]:
        return {
            "interviewId": session.id,
            "state": session.state,
            "targetJob": session.targetJob,
            "progress": session.progress(),
            "turns": [
                {
                    "turnId": t.turnId,
                    "topicId": t.topicId,
                    "question": t.question,
                    "answer": t.answer,
                    "depth": t.depth,
                    "resumeRefs": t.resumeRefs,
                }
                for t in session.turns
            ],
            "maxFollowUps": MAX_FOLLOW_UPS_PER_TOPIC,
            "topics": [{"id": t["id"], "name": t["name"]} for t in TOPIC_BANK],
            "report": session.report.model_dump(mode="json") if session.report else None,
        }

    def purge(self) -> int:
        now = time.time()
        dead = [key for key, value in self._sessions.items() if value[2] < now]
        for key in dead:
            self._sessions.pop(key, None)
        return len(dead)
