"""岗位匹配用例（M11 的非编排部分）。

结论必须可追溯：每个技能都带"简历里的原句"与"哪条岗位样本提到它"，
样本不足时显式说明，不包装成市场结论。
"""

from __future__ import annotations

from ..domain.jobs import (
    DEFAULT_DISCLAIMER,
    MatchReport,
    SkillHit,
    classify_skill,
)
from ..domain.resume import ResumeDocument
from .container import AppContainer


class JobService:
    def __init__(self, container: AppContainer) -> None:
        self.container = container

    async def match(
        self, *, target_job: str, document: ResumeDocument, city: str = "", limit: int = 5
    ) -> MatchReport:
        jobs = await self.container.job_provider.search(
            role=target_job, city=city, limit=max(1, min(limit, 10))
        )
        skills: list[str] = []
        for job in jobs:
            for skill in job.skills:
                if skill not in skills:
                    skills.append(skill)

        blocks = document.text_blocks()
        hits: list[SkillHit] = []
        for skill in skills:
            low = skill.lower()
            spans = [f"{module_type}:{text[:40]}" for _, module_type, _, text in blocks if low in text.lower()]
            jd_hits = [job.id for job in jobs if skill in job.skills]
            hit = classify_skill(skill, resume_spans=spans, jd_hits=jd_hits)
            hit.evidenceIds = jd_hits
            hits.append(hit)

        return MatchReport(
            targetJob=target_job,
            hits=hits,
            citations=[
                {
                    "jobId": job.id,
                    "role": job.role,
                    "city": job.city,
                    "sourceName": job.sourceName,
                    "sourceUrl": job.sourceUrl,
                    "fetchedAt": job.fetchedAt.isoformat() if job.fetchedAt else "",
                    "isSample": job.isSample,
                }
                for job in jobs
            ],
            sampleSize=len(jobs),
            disclaimer=DEFAULT_DISCLAIMER.format(n=len(jobs)),
            fallbackUsed=True,
            suggestions=[hit.suggestion for hit in hits if hit.suggestion][:6],
        )
