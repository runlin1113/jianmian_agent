# ADR 0005：自研有界图 + LangGraph 同构适配器

- 状态：已采纳
- 日期：2026-11-16
- 相关：架构书第 8.1、8.3、12.2 节

## 背景

架构书建议引入 LangGraph 做编排。但演示与测试需要**确定性**：同一句话必须得到同样的节点序列，
中断/恢复必须可复现，运行上限必须由我们自己的代码强制（而不是靠提示词或框架默认）。

## 决定

1. 图定义是**纯数据**：`GraphSpec{entry, nodes: dict[str, async handler]}`，节点返回下一节点名，
   `PAUSE` 表示中断，`END` 表示结束；
2. 默认执行器 `workflows/engine.py`：20 行核心循环，强制 `max_steps`、总时长预算；
3. `workflows/langgraph_runner.py` 把同一份 `GraphSpec` 翻译成 `StateGraph`，
   用于验证"图定义与框架无关"，未安装时 `available()` 返回 False 并自动回退。

## 为什么不用 LangGraph 做主执行器

- 首版需要"暂停后原样恢复"：我们的 `AgentState` 里已经有 `pending`、`steps`、`attempts`，
  恢复策略（从哪个节点继续）是**业务决定**，不该被框架的 checkpointer 语义绑架；
- 运行上限（工具 8 次、格式修复 2 次、压缩 2 次、120 秒）必须是可测试的硬约束；
- 少一层依赖，课程环境更容易跑起来。

## 恢复策略（业务决定，写在 `application/runs.py`）

| 中断 | 恢复起点 | 说明 |
|---|---|---|
| 澄清（业务入口不明） | `classify` | 把回答拼进指令，重新识别；若用户选了入口则 `forcedIntent` 直采信 |
| 澄清（多模块歧义，用户点了某一项） | `edit_dispatch` | 直接给定目标模块，不再重新分类 |
| 澄清（缺目标岗位） | `build_check_materials` | 回答作为 `targetJob` |
| 版面反馈 | `resume_after_layout` | 先按真实测量判断是否需要再压缩 |

## 代价

- 自己的引擎没有生态（可视化、时间旅行），排障靠事件流与测试；
- 适配器内部用 `asyncio.run`，不能在已运行的事件循环中直接调用（已注释说明）。

## 检验方式

`tests/test_workflows.py::test_same_graph_spec_runs_on_both_engines`：同一份图在两个执行器上
得到相同的节点顺序；未安装 LangGraph 时自动 skip。
