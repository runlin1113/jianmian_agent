"""LangGraph 同构适配器（可选）。

同一份 `GraphSpec` 可以被两个执行器跑：
- 默认执行器：`engine.GraphRunner`，确定性、无额外依赖，测试用它固定事件序列；
- 本适配器：把节点与条件边翻译成 LangGraph 的 StateGraph，用于验证"图定义与框架无关"。

若未安装 langgraph（或版本不兼容），`available()` 返回 False，编排自动回退默认执行器，
不影响任何业务能力——这正是"换图框架不应改动简历字段规则"的落地方式。
"""

from __future__ import annotations

from typing import Any, TypedDict

from .engine import END, PAUSE, GraphSpec
from .state import AgentState


class _GraphState(TypedDict, total=False):
    agent: Any
    next: str


def available() -> bool:
    try:
        import langgraph  # noqa: F401
    except Exception:
        return False
    return True


def run_with_langgraph(spec: GraphSpec, state: AgentState) -> str:
    """执行一次图，返回最后到达的节点名（PAUSE 时返回 PAUSE）。"""
    from langgraph.graph import END as LG_END
    from langgraph.graph import StateGraph

    def _wrap(handler):
        async def _node(payload: _GraphState) -> _GraphState:
            agent: AgentState = payload["agent"]
            nxt = await handler(agent)
            return {"agent": agent, "next": nxt if nxt else END}

        return _node

    builder = StateGraph(_GraphState)
    for name, handler in spec.nodes.items():
        builder.add_node(name, _wrap(handler))
    builder.set_entry_point(spec.entry)

    def _route(payload: _GraphState) -> str:
        nxt = payload.get("next") or END
        if nxt in {END, PAUSE}:
            return LG_END
        return nxt

    builder.add_conditional_edges(
        spec.entry,
        _route,
        {name: name for name in spec.nodes} | {LG_END: LG_END},
    )
    for name in spec.nodes:
        if name == spec.entry:
            continue
        builder.add_conditional_edges(
            name,
            _route,
            {other: other for other in spec.nodes} | {LG_END: LG_END},
        )

    graph = builder.compile()
    # 节点是异步函数，必须走异步 API；本适配器是同步便捷入口，
    # 因此内部自建事件循环（不要在已运行的事件循环里直接调用它）。
    import asyncio

    result = asyncio.run(
        graph.ainvoke({"agent": state, "next": spec.entry}, config={"recursion_limit": 40})
    )
    last = (result or {}).get("next")
    return PAUSE if last in {None, END, LG_END} and state.pending else (last or END)
