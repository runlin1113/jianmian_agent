"""内存预算实现（默认单实例档）。

关键语义：**先原子预占、后结算**。若先调用模型再扣费，就无法阻止"请求开始前已超额"。
公开多实例档换 Redis 的 `INCRBY`/Lua 原子脚本，接口不变。
"""

from __future__ import annotations

import threading
import time
import uuid

from ..ports.budget import BudgetLease, BudgetStore


class InMemoryBudgetStore(BudgetStore):
    def __init__(self, *, daily_tokens: int = 60_000, window_seconds: int = 86_400) -> None:
        self._daily = daily_tokens
        self._window = window_seconds
        self._lock = threading.RLock()
        self._usage: dict[str, tuple[int, float]] = {}  # subject -> (used, windowStart)
        self._leases: dict[str, BudgetLease] = {}

    def _roll(self, subject: str, now: float) -> tuple[int, float]:
        used, start = self._usage.get(subject, (0, now))
        if now - start >= self._window:
            used, start = 0, now
        self._usage[subject] = (used, start)
        return used, start

    def reserve(self, subject: str, tokens: int) -> BudgetLease | None:
        if tokens <= 0:
            tokens = 1
        with self._lock:
            now = time.time()
            used, start = self._roll(subject, now)
            if used + tokens > self._daily:
                return None
            self._usage[subject] = (used + tokens, start)
            lease = BudgetLease(
                leaseId="b-" + uuid.uuid4().hex[:8],
                subject=subject,
                reservedTokens=tokens,
                createdAt=now,
            )
            self._leases[lease.leaseId] = lease
            return lease

    def settle(self, lease: BudgetLease, spent_tokens: int) -> BudgetLease:
        with self._lock:
            now = time.time()
            used, start = self._roll(lease.subject, now)
            refund = max(0, lease.reservedTokens - spent_tokens)
            spent = max(0, spent_tokens)
            self._usage[lease.subject] = (max(0, used - refund), start)
            lease.spentTokens = spent
            lease.state = "settled"
            self._leases[lease.leaseId] = lease
            return lease

    def release(self, lease: BudgetLease) -> None:
        with self._lock:
            now = time.time()
            used, start = self._roll(lease.subject, now)
            self._usage[lease.subject] = (max(0, used - lease.reservedTokens), start)
            lease.state = "released"
            self._leases.pop(lease.leaseId, None)

    def used(self, subject: str) -> int:
        with self._lock:
            used, _ = self._roll(subject, time.time())
            return used

    def remaining(self, subject: str) -> int:
        return max(0, self._daily - self.used(subject))


class UnlimitedBudgetStore(BudgetStore):
    """显式"无预算设施"实现：按架构要求，此时站长 Key 路径必须关闭。"""

    is_unlimited = True

    def reserve(self, subject: str, tokens: int) -> BudgetLease | None:
        return BudgetLease(leaseId="unlimited", subject=subject, reservedTokens=tokens, state="settled")

    def settle(self, lease: BudgetLease, spent_tokens: int) -> BudgetLease:
        lease.spentTokens = spent_tokens
        return lease

    def release(self, lease: BudgetLease) -> None:
        return None

    def used(self, subject: str) -> int:
        return 0
