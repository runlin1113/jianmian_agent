"""请求/响应契约（前端类型由此生成，见 packages/contracts）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..application.runs import Decision, RunStart


class SessionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csrfToken: str
    expiresIn: int = 0


class JobMatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targetJob: str = Field(min_length=1, max_length=80)
    document: dict[str, Any]
    city: str = Field(default="", max_length=40)
    limit: int = Field(default=5, ge=1, le=10)


class InterviewStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: dict[str, Any]
    targetJob: str = Field(default="", max_length=80)
    topics: list[str] | None = Field(default=None, max_length=8)


class InterviewAnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turnId: str = Field(min_length=1, max_length=40)
    answer: str = Field(min_length=1, max_length=4000)


class MemoryConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[dict[str, Any]] = Field(min_length=1, max_length=20)


class MemoryExtractIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=6, max_length=4000)


class ForgetPlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str = Field(pattern="^(document_only|memory_only|everywhere)$")
    factId: str | None = Field(default=None, max_length=60)


__all__ = [
    "RunStart",
    "Decision",
    "SessionOut",
    "JobMatchIn",
    "InterviewStartIn",
    "InterviewAnswerIn",
    "MemoryConfirmIn",
    "MemoryExtractIn",
    "ForgetPlanIn",
]
