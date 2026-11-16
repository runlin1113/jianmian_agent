"""检索端口（M10）。实现可以是本地种子库、受控搜索 API，或未来的混合检索。"""

from __future__ import annotations

from typing import Protocol

from ..domain.jobs import JobEvidence


class SearchProvider(Protocol):
    name: str
    isRemote: bool

    async def search(self, *, role: str, city: str = "", seniority: str = "", limit: int = 5) -> list[JobEvidence]:
        ...
