"""岗位知识与匹配（M10，第 9.3 节）。

硬规则：
- 公共岗位知识与个人事实库**分开**存；
- 输出必须区分三档：`matched`（用户具备且有材料支持）/ `partial`（可能相关但需补充证据）
  / `missing`（尚缺能力）；
- 缺失能力只能转成学习建议，不能自动写成"已掌握"；
- 少量 JD 样本不能包装成全市场统计或薪资预测。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

JobCategory = Literal["matched", "partial", "missing"]
Confidence = Literal["high", "medium", "low"]


class JobEvidence(BaseModel):
    """公共岗位依据：区分"获取时间"和"原文发布时间"。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    role: str
    city: str = ""
    seniority: str = ""
    skills: list[str] = Field(default_factory=list)
    description: str = ""
    sourceUrl: str = ""
    sourceName: str = ""
    fetchedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    publishedAt: date | None = None
    expiresAt: date | None = None
    contentHash: str = ""
    isSample: bool = True

    def is_stale(self, today: date | None = None) -> bool:
        today = today or date.today()
        return bool(self.expiresAt and self.expiresAt < today)

    def citation(self) -> dict:
        return {
            "jobId": self.id,
            "role": self.role,
            "city": self.city,
            "sourceName": self.sourceName,
            "sourceUrl": self.sourceUrl,
            "fetchedAt": self.fetchedAt.isoformat(),
            "publishedAt": self.publishedAt.isoformat() if self.publishedAt else None,
            "expiresAt": self.expiresAt.isoformat() if self.expiresAt else None,
            "isSample": self.isSample,
        }


class SkillHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill: str
    category: JobCategory
    evidenceIds: list[str] = Field(default_factory=list)
    #: 命中的简历原文片段（来自 claim link），没有就是"无材料支持"
    resumeSpans: list[str] = Field(default_factory=list)
    suggestion: str = ""
    confidence: Confidence = "medium"


class MatchReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targetJob: str
    generatedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    hits: list[SkillHit] = Field(default_factory=list)
    citations: list[dict] = Field(default_factory=list)
    #: 样本不足时必须显式说明，不许包装成市场结论
    sampleSize: int = 0
    disclaimer: str = ""
    fallbackUsed: bool = False
    suggestions: list[str] = Field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {"matched": 0, "partial": 0, "missing": 0}
        for h in self.hits:
            out[h.category] += 1
        return out


DEFAULT_DISCLAIMER = (
    "以上结论仅基于本次检索到的 {n} 条岗位样本与你的简历原文，"
    "不代表全市场统计、真实招聘热度或薪资预测；"
    "缺失项是学习建议，不代表你已具备该能力。"
)


def build_disclaimer(sample_size: int) -> str:
    return DEFAULT_DISCLAIMER.format(n=sample_size)


def classify_skill(
    skill: str,
    *,
    resume_spans: list[str],
    jd_hits: list[str],
) -> SkillHit:
    """三档分类的确定性规则。LLM 只用于补建议文案，不改变分类语义。"""
    support = len(resume_spans)
    if support and jd_hits:
        category: JobCategory = "matched"
        suggestion = "已有材料支持，可在面试中重点展开"
        confidence: Confidence = "high"
    elif support or jd_hits:
        category = "partial"
        suggestion = "方向相关，建议补充一条能证明该能力的项目细节"
        confidence = "medium"
    else:
        category = "missing"
        suggestion = f"简历与样本中都没有「{skill}」的证据，建议先做一个可展示的小项目再写入"
        confidence = "high"
    return SkillHit(
        skill=skill,
        category=category,
        resumeSpans=resume_spans[:3],
        suggestion=suggestion,
        confidence=confidence,
    )
