"""本地岗位库适配器（M10 默认档，SQLite）。

- 与"个人事实库"物理分离：这里只存公共岗位材料；
- 中文检索不假设默认分词足够：先用**归一化标签 + 关键词/二元字组**匹配，
  样本足够多且召回评测显示不足时再加嵌入向量（第 9.3 节）；
- 种子样本标记 `isSample=True`，输出时必须带引用与免责声明。
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from ..config import KNOWLEDGE_DIR
from ..domain.jobs import JobEvidence
from ..ports.search import SearchProvider

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    city TEXT,
    seniority TEXT,
    skills TEXT,
    description TEXT,
    source_name TEXT,
    source_url TEXT,
    fetched_at TEXT,
    published_at TEXT,
    expires_at TEXT,
    is_sample INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_jobs_role ON jobs(role);
"""

_STOP = {"开发", "工程师", "岗位", "实习", "应届", "招聘"}


def _bigrams(text: str) -> set[str]:
    cleaned = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9+#.]", "", text or "")
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def _normalize_skills(raw: str | list[str]) -> list[str]:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except json.JSONDecodeError:
            return [s for s in re.split(r"[、,，/\s]+", raw) if s]
    return [str(x) for x in raw]


class LocalJobSearchProvider(SearchProvider):
    name = "local-seed"
    isRemote = False

    def __init__(self, db_path: str | Path, *, seed_dir: Path | None = None) -> None:
        self._db_path = Path(db_path)
        self._seed_dir = seed_dir or KNOWLEDGE_DIR
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()
        self._seed_if_empty()

    # ---- 初始化 ----------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _seed_if_empty(self) -> None:
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            if count:
                return
            seeds = self._load_seed_files()
            for job in seeds:
                conn.execute(
                    "INSERT OR REPLACE INTO jobs (id, role, city, seniority, skills, description,"
                    " source_name, source_url, fetched_at, published_at, expires_at, is_sample)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        job["id"],
                        job["role"],
                        job.get("city", ""),
                        job.get("seniority", ""),
                        json.dumps(job.get("skills", []), ensure_ascii=False),
                        job.get("description", ""),
                        job.get("sourceName", "课程种子样本"),
                        job.get("sourceUrl", ""),
                        job.get("fetchedAt", datetime.now(timezone.utc).isoformat()),
                        job.get("publishedAt"),
                        job.get("expiresAt"),
                        1,
                    ),
                )

    def _load_seed_files(self) -> list[dict]:
        jobs: list[dict] = []
        if not self._seed_dir.exists():
            return jobs
        for path in sorted(self._seed_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            entries = payload if isinstance(payload, list) else payload.get("jobs", [])
            for entry in entries:
                if isinstance(entry, dict) and entry.get("id") and entry.get("role"):
                    jobs.append(entry)
        return jobs

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    # ---- 检索 ------------------------------------------------------------
    async def search(
        self, *, role: str, city: str = "", seniority: str = "", limit: int = 5
    ) -> list[JobEvidence]:
        limit = max(1, min(limit, 20))
        rows = self._fetch_candidates(role, city)
        query_tokens = _bigrams(role) | {t for t in re.split(r"[\s/、,，]+", role or "") if t and t not in _STOP}
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            skills = _normalize_skills(row["skills"])
            overlap = len(query_tokens & _bigrams(" ".join(skills)))
            role_bonus = 2.0 if role and role in row["role"] else 0.0
            city_bonus = 1.0 if city and city in (row["city"] or "") else 0.0
            senior_bonus = 0.5 if seniority and seniority == row["seniority"] else 0.0
            score = overlap + role_bonus + city_bonus + senior_bonus
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda x: (-x[0], x[1]["id"]))
        out: list[JobEvidence] = []
        for _, row in scored[:limit]:
            out.append(
                JobEvidence(
                    id=row["id"],
                    role=row["role"],
                    city=row["city"] or "",
                    seniority=row["seniority"] or "",
                    skills=_normalize_skills(row["skills"]),
                    description=row["description"] or "",
                    sourceUrl=row["source_url"] or "",
                    sourceName=row["source_name"] or "课程种子样本",
                    fetchedAt=_parse_dt(row["fetched_at"]),
                    publishedAt=_parse_date(row["published_at"]),
                    expiresAt=_parse_date(row["expires_at"]),
                    isSample=bool(row["is_sample"]),
                )
            )
        return out

    def _fetch_candidates(self, role: str, city: str) -> list[sqlite3.Row]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs").fetchall()
        if not rows:
            return []
        keys = [k for k in re.split(r"[\s/、,，]+", role or "") if k]
        matched = [r for r in rows if any(k in (r["role"] or "") for k in keys)]
        if not matched:
            matched = [r for r in rows if any(b in (r["role"] or "") for b in _bigrams(role))]
        if not matched:
            matched = list(rows)
        if city:
            city_matched = [r for r in matched if city in (r["city"] or "")]
            matched = city_matched or matched
        return matched


def _parse_dt(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(str(raw))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None
