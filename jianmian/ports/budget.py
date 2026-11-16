"""预算端口（M13）。

只允许**一个权威存储**原子更新共享预算；每个进程各计一份会算错。
本地档用内存实现，公开档换 Redis 实现即可，接口不变。
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class BudgetLease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leaseId: str
    subject: str
    reservedTokens: int = 0
    spentTokens: int = 0
    createdAt: float = 0.0
    state: str = "reserved"  # reserved | settled | released

    def remaining(self) -> int:
        return max(0, self.reservedTokens - self.spentTokens)


class BudgetStore(Protocol):
    """预占 → 结算 的两阶段接口。

    `reserve` 必须在**调用模型之前**原子扣减，否则无法阻止请求开始前已经超额。
    """

    def reserve(self, subject: str, tokens: int) -> BudgetLease | None: ...

    def settle(self, lease: BudgetLease, spent_tokens: int) -> BudgetLease: ...

    def release(self, lease: BudgetLease) -> None: ...

    def used(self, subject: str) -> int: ...
