"""有界状态图引擎。

为什么自己写一个而不是直接依赖框架：
- 演示与测试需要**确定性**的事件顺序与可复现的中断/恢复；
- 运行上限（步数、工具调用、时限、压缩轮次）必须由我们自己的代码强制，不能交给提示词；
- 图定义是纯数据（节点 + 条件边），因此也能被 LangGraph 适配器原样执行（见 langgraph_runner）。

语义：
- 节点是 `async def handler(state) -> str | None`，返回下一个节点名或 None 结束；
- 节点返回 `PAUSE` 表示中断：引擎停止，状态落为 awaiting_*，等待用户响应后从该节点继续；
- 引擎强制 `max_steps` 防止图内环；超时抛出 `BudgetExceeded`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

PAUSE = "__pause__"
END = "__end__"

NodeHandler = Callable[["AgentState"], Awaitable[str | None]]


class BudgetExceeded(Exception):
    def __init__(self, reason: str, *, code: str = "run_budget_exceeded"):
        super().__init__(reason)
        self.code = code
        self.reason = reason


@dataclass
class GraphSpec:
    name: str
    entry: str
    nodes: dict[str, NodeHandler] = field(default_factory=dict)
    #: 用于文档与校验的可读描述
    description: str = ""

    def node_names(self) -> list[str]:
        return list(self.nodes)

    def validate(self) -> None:
        if self.entry not in self.nodes:
            raise ValueError(f"入口节点 {self.entry} 不存在")
        if not self.nodes:
            raise ValueError("图至少需要一个节点")


class GraphRunner:
    def __init__(self, spec: GraphSpec, *, max_steps: int = 40) -> None:
        spec.validate()
        self.spec = spec
        self.max_steps = max_steps

    async def run(self, state: "AgentState", *, start_at: str | None = None) -> str:
        """执行到结束或中断，返回最终节点名（或 PAUSE 前的节点）。"""
        current = start_at or self.spec.entry
        steps = 0
        while current and current != END:
            if steps >= self.max_steps:
                raise BudgetExceeded("状态图步数超出上限")
            if state.budget_exhausted():
                raise BudgetExceeded("本次任务总时长超出预算")
            handler = self.spec.nodes.get(current)
            if handler is None:
                raise KeyError(f"未知节点 {current}")
            state.steps.append(current)
            nxt = await handler(state)
            steps += 1
            if nxt == PAUSE:
                return PAUSE
            current = nxt or END
        return current or END


from .state import AgentState  # noqa: E402  (避免循环导入的类型注解使用)
