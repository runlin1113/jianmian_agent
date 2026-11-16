"""记忆管理用例（M13）。

首版的真实长期档案在浏览器（IndexedDB）；服务端这里只是**会话级临时镜像**，
用于"这一轮对话里我确认过的事实"能被上下文装配读到，并随会话过期清空。

规则：
- 模型提出的候选必须由用户确认才进入档案；
- 用户可更正、可遗忘；遗忘时区分"只从简历删""只停止记忆""全部清除"。
"""

from __future__ import annotations

import time
from typing import Any

from ..domain import errors
from ..domain.memory import (
    ConfirmedFact,
    ForgetScope,
    MemoryCandidate,
    ProfileMemory,
    plan_forget,
)
from ..ports.model import ModelRequest, estimate_tokens
from ..security.ids import opaque_id
from .container import AppContainer


class ProfileService:
    def __init__(self, container: AppContainer) -> None:
        self.container = container
        self._profiles: dict[str, tuple[ProfileMemory, float]] = {}
        self._ttl = 1800.0
        self._max = 500

    def get(self, session_id: str) -> ProfileMemory:
        self._roll()
        entry = self._profiles.get(session_id)
        if entry is None:
            return ProfileMemory()
        return entry[0]

    def confirm(self, session_id: str, candidates: list[dict[str, Any]]) -> ProfileMemory:
        profile = self.get(session_id)
        for raw in candidates[:20]:
            try:
                candidate = MemoryCandidate.model_validate({**raw, "id": raw.get("id") or opaque_id("fact", 4)})
            except Exception as exc:
                raise errors.contract_error(f"记忆候选不合法：{exc}") from exc
            if len(candidate.text.strip()) < 4:
                raise errors.contract_error("记忆文本过短")
            profile = profile.confirm_candidate(candidate)
        self._save(session_id, profile)
        return profile

    def forget(self, session_id: str, fact_id: str) -> tuple[ProfileMemory, dict]:
        profile = self.get(session_id)
        if not any(f.id == fact_id for f in profile.facts):
            raise errors.not_found("该条记忆")
        self._save(session_id, profile.forget_fact(fact_id))
        return self.get(session_id), plan_forget("memory_only", fact_id=fact_id)

    def forget_plan(self, scope: str, *, fact_id: str | None = None) -> dict:
        if scope not in {"document_only", "memory_only", "everywhere"}:
            raise errors.contract_error("scope 必须是 document_only / memory_only / everywhere")
        return plan_forget(scope, fact_id=fact_id)  # type: ignore[arg-type]

    async def extract(self, session_id: str, text: str, *, byok_key: str | None = None) -> list[MemoryCandidate]:
        """从对话里提候选，不直接写入。"""
        if len(text.strip()) < 6:
            raise errors.contract_error("文本过短，无法抽取记忆")
        model = self.container.model_for(byok_key)
        budget = self.container.budget_for(byok=bool(byok_key))
        lease = budget.reserve(session_id, estimate_tokens(text) + 500)
        if lease is None:
            raise errors.budget_exhausted("演示额度已用完，暂时无法抽取记忆")
        try:
            result = await model.generate(
                ModelRequest(task="memory_extract", inputs={"text": text[:4000]}, maxTokens=500)
            )
        except Exception:
            budget.release(lease)
            raise
        if not result.ok or not result.structured:
            budget.settle(lease, 0)
            raise errors.upstream_unavailable("模型没有返回可用的记忆候选")
        budget.settle(lease, result.usage.totalTokens or 0)
        out: list[MemoryCandidate] = []
        for raw in (result.structured.get("candidates") or [])[:8]:
            if not isinstance(raw, dict) or not str(raw.get("text", "")).strip():
                continue
            out.append(
                MemoryCandidate(
                    id=opaque_id("mem", 4),
                    kind=raw.get("kind", "fact"),
                    text=str(raw["text"])[:200],
                    reason=str(raw.get("reason", ""))[:120],
                )
            )
        return out

    def context_facts(self, session_id: str, *, job: str = "", limit: int = 8) -> list[str]:
        return [fact.text for fact in self.get(session_id).relevant_for(job=job, limit=limit)]

    # ------------------------------------------------------------------
    def _save(self, session_id: str, profile: ProfileMemory) -> None:
        if len(self._profiles) >= self._max:
            oldest = min(self._profiles.items(), key=lambda kv: kv[1][1])
            self._profiles.pop(oldest[0], None)
        self._profiles[session_id] = (profile, time.time() + self._ttl)

    def _roll(self) -> None:
        now = time.time()
        dead = [key for key, value in self._profiles.items() if value[1] < now]
        for key in dead:
            self._profiles.pop(key, None)

    def public(self, session_id: str) -> dict[str, Any]:
        profile = self.get(session_id)
        return {
            "facts": [f.model_dump(mode="json") for f in profile.facts],
            "projects": profile.projects,
            "jobPreferences": profile.jobPreferences,
            "writingPreferences": profile.writingPreferences,
            "interests": profile.interests,
            "scope": "session",
            "note": "服务端只保留会话级临时档案；长期档案在你的浏览器里，可导出 JSON 备份。",
        }


__all__ = ["ProfileService", "ConfirmedFact", "ForgetScope"]
