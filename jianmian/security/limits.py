"""令牌桶限流（按会话为主、IP 风险为辅）。

按 IP 硬限流会误伤校园 NAT 后的整栋宿舍；所以默认主体是**匿名签名会话**，
IP 只作为"风险辅助"（阈值更宽）。CORS 不参与这里的任何判断。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class Bucket:
    tokens: float
    updated_at: float


class TokenBucketLimiter:
    def __init__(self, *, per_minute: int = 40, burst: int = 12) -> None:
        self._per_minute = max(1, per_minute)
        self._burst = max(1, burst)
        self._rate = self._per_minute / 60.0
        self._buckets: dict[str, Bucket] = {}
        self._lock = threading.RLock()
        self._max_buckets = 20_000

    def allow(self, key: str, *, cost: float = 1.0, now: float | None = None) -> tuple[bool, int]:
        """返回 (是否放行, 建议 retryAfter 秒)。"""
        now = now or time.time()
        with self._lock:
            if len(self._buckets) > self._max_buckets:
                self._buckets.clear()
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = Bucket(tokens=float(self._burst), updated_at=now)
                self._buckets[key] = bucket
            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(self._burst, bucket.tokens + elapsed * self._rate)
            bucket.updated_at = now
            if bucket.tokens >= cost:
                bucket.tokens -= cost
                return True, 0
            deficit = cost - bucket.tokens
            retry_after = max(1, int(deficit / self._rate) + 1)
            return False, retry_after

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
