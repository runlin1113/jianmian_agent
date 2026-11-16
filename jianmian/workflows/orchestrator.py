"""编排入口：把图、工具、预算、模型装配起来执行一次 run。

对上层只暴露 `run(state, start_at)`；对下层把一切不确定性收敛在依赖对象里，
因此在测试中替换 deps 就能整条链路跑在 mock 模型上。
"""

from __future__ import annotations

from ..config import Settings
from .engine import PAUSE, BudgetExceeded, GraphRunner
from .graph import WorkflowDeps, build_graph
from .state import AgentState


class Orchestrator:
    def __init__(self, deps: WorkflowDeps, settings: Settings | None = None) -> None:
        self.deps = deps
        self.settings = settings or deps.settings
        self.spec = build_graph(deps)

    async def run(self, state: AgentState, *, start_at: str | None = None) -> AgentState:
        runner = GraphRunner(self.spec, max_steps=40)
        try:
            await runner.run(state, start_at=start_at)
        except BudgetExceeded as exc:
            state.error = {"code": exc.code, "message": exc.reason, "retryable": True}
            emit = state.extra.get("emit")
            if emit:
                emit("run.failed", {"error": state.error})
        return state
