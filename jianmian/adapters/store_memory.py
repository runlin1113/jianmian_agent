"""有界内存运行状态存储（默认单实例档）。

- 事件有上限（默认 400 条），超出丢弃最旧事件但保留递增 seq，重放时是"有界重放"；
- run 与事件分别带 TTL；`purge_expired` 由应用层定时/每请求调用，真实删除而非只写隐私声明；
- 幂等键以 (sessionId, key) 建立二级索引，并绑定请求哈希。

进程重启 → 活动 run 失效。这是**明确接受**的取舍：前端草稿仍在本地，用户重建任务即可。
换 Redis 实现同样的接口即可扩展为多人档，但必须同时补租约与确认 CAS。
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

from ..ports.store import RunRecord, RunStore


class InMemoryRunStore(RunStore):
    def __init__(self, *, max_runs: int = 500, max_events: int = 400) -> None:
        self._runs: OrderedDict[str, RunRecord] = OrderedDict()
        self._idem: dict[tuple[str, str], str] = {}
        self._lock = threading.RLock()
        self._max_runs = max_runs
        self._max_events = max_events

    # ---- 基础 CRUD --------------------------------------------------------
    def create(self, record: RunRecord) -> RunRecord:
        with self._lock:
            self._evict_if_needed()
            record.events = record.events[-self._max_events :]
            self._runs[record.id] = record
            if record.idempotencyKey:
                self._idem[(record.sessionId, record.idempotencyKey)] = record.id
            return record

    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return None
            if self._is_expired(record):
                record.status = "expired"
                record.error = record.error or {"code": "run_expired", "message": "任务已过期"}
                self._drop(record)
                return record
            return record

    def update(self, record: RunRecord) -> RunRecord:
        with self._lock:
            record.events = record.events[-self._max_events :]
            self._runs[record.id] = record
            self._runs.move_to_end(record.id)
            return record

    def delete(self, run_id: str) -> None:
        with self._lock:
            record = self._runs.get(run_id)
            if record:
                self._drop(record)

    # ---- 幂等 ------------------------------------------------------------
    def find_by_idempotency(self, session_id: str, key: str) -> RunRecord | None:
        with self._lock:
            run_id = self._idem.get((session_id, key))
            return self._runs.get(run_id) if run_id else None

    # ---- 清理 ------------------------------------------------------------
    def purge_expired(self, now: float | None = None) -> int:
        now = now or time.time()
        removed = 0
        with self._lock:
            for run_id in list(self._runs):
                record = self._runs[run_id]
                if self._is_expired(record, now):
                    record.status = "expired"
                    self._drop(record)
                    removed += 1
        return removed

    def stats(self) -> dict[str, int]:
        with self._lock:
            active = sum(1 for r in self._runs.values() if not r.is_terminal)
            by_status: dict[str, int] = {}
            for r in self._runs.values():
                by_status[r.status] = by_status.get(r.status, 0) + 1
            return {"runs": len(self._runs), "active": active, "idempotencyKeys": len(self._idem), **{
                f"status_{k}": v for k, v in by_status.items()
            }}

    # ---- 内部 ------------------------------------------------------------
    def _is_expired(self, record: RunRecord, now: float | None = None) -> bool:
        now = now or time.time()
        if record.is_terminal:
            return False
        return record.expiresAt > 0 and now >= record.expiresAt

    def _drop(self, record: RunRecord) -> None:
        self._runs.pop(record.id, None)
        if record.idempotencyKey:
            self._idem.pop((record.sessionId, record.idempotencyKey), None)

    def _evict_if_needed(self) -> None:
        if len(self._runs) < self._max_runs:
            return
        for run_id in list(self._runs):
            if self._runs[run_id].is_terminal:
                self._drop(self._runs[run_id])
                return
        oldest = next(iter(self._runs))
        self._drop(self._runs[oldest])
