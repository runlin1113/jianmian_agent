"""进程内事件总线（SSE 的推送侧）。

设计要点：
- **不计费、不持久**：事件只挂在 RunRecord 上，随 run 过期一起消失；
- **不会丢唤醒**：等待方先比较版本号再 `wait()`，发布方只做 `set()`，
  因此"发布发生在 wait 之前"这种情况会立刻返回而不是挂到超时；
- **有界**：单 run 事件条数由 RunStore 截断，这里不额外堆积。
"""

from __future__ import annotations

import asyncio


class EventBroker:
    def __init__(self) -> None:
        self._versions: dict[str, int] = {}
        self._events: dict[str, asyncio.Event] = {}

    def publish(self, run_id: str) -> None:
        """同步发布：编排层的事件回调本身是同步的。"""
        self._versions[run_id] = self._versions.get(run_id, 0) + 1
        ev = self._events.get(run_id)
        if ev is None:
            ev = asyncio.Event()
            self._events[run_id] = ev
        ev.set()

    async def wait(self, run_id: str, *, since_version: int, timeout: float) -> int:
        """等待版本号超过 `since_version`，或超时后返回当前版本号。"""
        current = self._versions.get(run_id, 0)
        if current > since_version:
            return current
        ev = self._events.get(run_id)
        if ev is None:
            ev = asyncio.Event()
            self._events[run_id] = ev
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            pass
        finally:
            # 只清自己的信号；清空后若又有发布，publish 会重新 set
            ev.clear()
        return self._versions.get(run_id, 0)

    def version(self, run_id: str) -> int:
        return self._versions.get(run_id, 0)

    def forget(self, run_id: str) -> None:
        self._versions.pop(run_id, None)
        self._events.pop(run_id, None)

    def stats(self) -> dict[str, int]:
        return {"runs": len(self._versions)}
