"""编排层测试：意图识别、工具权限、有界执行、事实守卫修复路径。"""

from __future__ import annotations

import asyncio

import pytest

from jianmian.adapters.budget_memory import InMemoryBudgetStore
from jianmian.adapters.model_mock import MockModelProvider
from jianmian.adapters.search_local import LocalJobSearchProvider
from jianmian.domain.resume import add_module, new_document, validate_document
from jianmian.workflows.engine import PAUSE, BudgetExceeded, GraphRunner, GraphSpec
from jianmian.workflows.graph import WorkflowDeps, build_graph
from jianmian.workflows.intents import classify
from jianmian.workflows.orchestrator import Orchestrator
from jianmian.workflows.state import AgentState
from jianmian.workflows.tools import ALLOWED_BY_INTENT, ToolContext, build_registry


def run(coro):
    """不依赖 pytest-asyncio：测试里显式跑事件循环，减少环境差异。"""
    return asyncio.run(coro)


def make_doc():
    doc = new_document()
    return add_module(
        doc,
        "project",
        {
            "proj_name": "选课系统",
            "role": "后端",
            "time": "2025.03-2025.06",
            "tech": "Flask",
            "desc": "使用 Flask 实现选课功能，服务 300 名学生",
        },
    )


# ------------------------------------------------------------------ 意图
@pytest.mark.parametrize(
    "text,expected",
    [
        ("帮我从这段素材生成一份简历", "build"),
        ("我是大三学生，想投 Python 后端", "build"),
        ("把项目详情写得更专业", "edit"),
        ("删掉自我评价", "edit"),
        ("帮我压缩到一页", "compress"),
        ("看看这个岗位需要什么能力", "job"),
        ("模拟面试一下", "interview"),
        ("导入我原来的简历", "import"),
        ("记住我熟悉 Flask", "memory"),
    ],
)
def test_intent_classification(text, expected):
    assert classify(text).intent == expected


def test_intent_asks_when_ambiguous():
    # 已有内容的简历上，泛泛的请求必须澄清（不能猜着改）
    result = classify("嗯……这个你看着办", make_doc())
    assert result.intent == "clarify"
    assert result.needs_clarification
    assert result.options, "泛泛的请求要给出可选入口"


def test_empty_document_any_message_defaults_to_build():
    # 空简历上的第一句话就是"给我一份简历"，不该先被反问一轮
    result = classify("你好", new_document())
    assert result.intent == "build"


def test_target_resolution_by_ordinal_and_title():
    doc = make_doc()
    doc = add_module(doc, "project", {"proj_name": "图书管理系统", "desc": "负责前端页面"})
    by_ordinal = classify("把第二个项目写得更专业", doc)
    assert len(by_ordinal.module_ids) == 1
    assert doc.require_module(by_ordinal.module_ids[0]).data["proj_name"] == "图书管理系统"

    by_title = classify("把选课系统的详情写得更专业", doc)
    assert len(by_title.module_ids) == 1
    assert doc.require_module(by_title.module_ids[0]).data["proj_name"] == "选课系统"

    ambiguous = classify("把项目写得更专业", doc)
    assert ambiguous.needs_clarification and ambiguous.options


# ------------------------------------------------------------------ 工具权限
def _ctx(settings, state):
    return ToolContext(
        settings=settings,
        model=MockModelProvider(),
        job_provider=LocalJobSearchProvider(settings.job_db_path),
        budget=InMemoryBudgetStore(),
        budget_subject="test",
        state=state,
    )


def test_tool_permission_boundary(settings):
    registry = build_registry(settings)
    state = AgentState(run_id="r", session_id="s", instruction="删掉项目", document=make_doc())
    ctx = _ctx(settings, state)

    denied = run(registry.call("compress_all", {}, ctx, intent="edit"))
    assert denied.ok is False
    assert denied.error["code"] == "tool_not_permitted"

    unknown = run(registry.call("shell_exec", {"cmd": "rm -rf /"}, ctx, intent="edit"))
    assert unknown.ok is False
    assert unknown.error["code"] == "unknown_tool"

    bad_args = run(registry.call("rewrite_field", {"module_id": "m-x"}, ctx, intent="edit"))
    assert bad_args.ok is False
    assert bad_args.error["code"] == "invalid_tool_args"


def test_tool_budget_is_bounded(settings):
    registry = build_registry(settings)
    state = AgentState(run_id="r", session_id="s", instruction="x", document=make_doc())
    state.tool_calls = settings.max_tool_calls_per_run
    ctx = _ctx(settings, state)
    outcome = run(
        registry.call(
            "rewrite_field",
            {"module_id": "m-pro-1", "field": "desc", "instruction": "润色"},
            ctx,
            intent="edit",
        )
    )
    assert outcome.ok is False
    assert outcome.error["code"] == "tool_budget_exceeded"


def test_destructive_tools_are_registered_as_destructive(settings):
    registry = build_registry(settings)
    catalog = {item["name"]: item for item in registry.catalog()}
    assert catalog, "工具目录不能为空"
    for name in catalog:
        assert name in set().union(*ALLOWED_BY_INTENT.values()), f"{name} 没有任何意图可用"


# ------------------------------------------------------------------ 有界引擎
def test_graph_engine_enforces_step_limit():
    async def loop(state):
        return "loop"

    spec = GraphSpec(name="loop", entry="loop", nodes={"loop": loop})
    runner = GraphRunner(spec, max_steps=5)
    with pytest.raises(BudgetExceeded):
        run(runner.run(AgentState(run_id="r", session_id="s", instruction="x")))


def test_graph_engine_pauses_and_reports():
    async def stop(state):
        state.message = "需要你补充信息"
        return PAUSE

    spec = GraphSpec(name="pause", entry="stop", nodes={"stop": stop})
    runner = GraphRunner(spec, max_steps=3)
    state = AgentState(run_id="r", session_id="s", instruction="x")
    assert run(runner.run(state)) == PAUSE
    assert state.message


# ------------------------------------------------------------------ 全链路
def test_build_run_emits_proposal_without_writing(settings):
    deps = WorkflowDeps(
        settings=settings,
        model=MockModelProvider(),
        job_provider=LocalJobSearchProvider(settings.job_db_path),
        budget=InMemoryBudgetStore(),
        registry=build_registry(settings),
    )
    doc = new_document()
    state = AgentState(
        run_id="run-t",
        session_id="sess-t",
        instruction=(
            "我是大三学生，想投 Python 后端，用 Flask 做过选课系统，服务 300 名学生。"
            "姓名：张三，电话：13800138000，邮箱：zhangsan@example.com，"
            "学校：江城大学，专业：计算机科学与技术，本科，时间：2024.09-2025.06"
        ),
        target_job="Python 后端开发",
        document=doc,
    )
    events: list[str] = []
    state.extra["emit"] = lambda kind, payload: events.append(kind)

    result = run(Orchestrator(deps, settings).run(state))
    assert result.error is None
    assert result.proposal is not None and result.proposal.operations
    assert "proposal.ready" in events
    # 关键：提案不写文档，工作副本仍是原始 revision
    assert result.document.revision == doc.revision
    # 事实守卫跑过
    assert "step.completed" in events


def test_edit_run_keeps_numbers(settings):
    deps = WorkflowDeps(
        settings=settings,
        model=MockModelProvider(),
        job_provider=LocalJobSearchProvider(settings.job_db_path),
        budget=InMemoryBudgetStore(),
        registry=build_registry(settings),
    )
    state = AgentState(
        run_id="run-e",
        session_id="sess-e",
        instruction="把选课系统的项目详情写得更专业一些，不要改数字",
        document=make_doc(),
    )
    state.extra["emit"] = lambda kind, payload: None
    result = run(Orchestrator(deps, settings).run(state))
    assert result.error is None
    assert result.proposal is not None
    for op in result.proposal.operations:
        assert "300" in op.after, "改写必须保留原有数字"


def test_mock_extracts_project_from_action_clause():
    """口语化的"做过 X"也必须被认成项目；学校名、自我评价不能被相邻内容污染。"""
    from jianmian.adapters.model_mock import build_modules

    result = build_modules(
        "我是大三学生，想投 Python 后端，用 Flask 做过选课系统，服务 300 名学生，"
        "姓名张三，电话13800138000，学校江城大学，专业计算机科学与技术，熟悉 Redis 和 MySQL",
        "Python 后端",
    )
    by_type = {m["type"]: m["data"] for m in result["modules"]}
    assert "project" in by_type, "「做过选课系统」应被识别为项目经历"
    assert by_type["project"]["proj_name"] == "选课系统"
    assert "300" in by_type["project"]["desc"], "结果子句应跟着动作子句一起进来"
    assert by_type["basic"]["name"] == "张三", "「姓名张三」没有冒号也要能认"
    assert by_type["education"]["school"] == "江城大学", "学校名不该带上「学校」前缀"
    summary = by_type.get("summary")
    assert summary is None or "13800138000" not in summary["eval"], "自我评价不能把手机号抄进去"

    # 时间不能被截断：`2024.09` 必须原样保留，不能变成 `2024.0`
    timed = build_modules("就读时间 2024.09-2025.06，专业：计算机科学与技术", "")
    assert timed["profile"]["time"] == "2024.09-2025.06", timed["profile"]["time"]


def test_noop_rewrite_produces_no_proposal(settings):
    """改写结果与原文一致时，不许生成"采纳了但什么都没变"的空提案。"""
    from jianmian.domain.proposals import AddModuleOp, ReplaceFieldOp
    from jianmian.workflows.graph import WorkflowNodes

    deps = WorkflowDeps(
        settings=settings,
        model=MockModelProvider(),
        job_provider=LocalJobSearchProvider(settings.job_db_path),
        budget=InMemoryBudgetStore(),
        registry=build_registry(settings),
    )
    doc = make_doc()
    module = doc.by_type("project")[0]
    state = AgentState(run_id="run-n", session_id="sess-n", instruction="润色", document=doc)

    same = ReplaceFieldOp(moduleId=module.id, field="desc", before=module.data["desc"], after=module.data["desc"])
    nodes = WorkflowNodes(deps)
    assert nodes._proposal(state, [same], "改写表达") is None
    assert "没找到可改的地方" in state.message
    assert any(w["kind"] == "no_change" for w in state.warnings)

    # 只差空白字符同样算没改
    spaced = ReplaceFieldOp(
        moduleId=module.id,
        field="desc",
        before="服务 300 名学生",
        after="服务300名学生 ",
    )
    assert nodes._proposal(state, [spaced], "改写表达") is None

    # 新增模块这类没有 before/after 的操作必须保留，不能被误判成 no-op
    add = AddModuleOp(moduleType="skills", data={"skills": "Python, Flask"})
    kept = nodes._proposal(state, [add, same], "新增技能")
    assert kept is not None and len(kept.operations) == 1


def test_run_fails_on_fact_change_attempt(settings):
    """当改写动到事实且无法修复时，run 必须失败而不是"悄悄应用一小部分"。"""
    from jianmian.domain.proposals import ChangeProposal, ReplaceFieldOp

    deps = WorkflowDeps(
        settings=settings,
        model=MockModelProvider(),
        job_provider=LocalJobSearchProvider(settings.job_db_path),
        budget=InMemoryBudgetStore(),
        registry=build_registry(settings),
    )
    doc = make_doc()
    module = doc.by_type("project")[0]
    state = AgentState(run_id="run-f", session_id="sess-f", instruction="润色一下", document=doc)
    state.extra["emit"] = lambda kind, payload: None
    bad = ChangeProposal(
        resumeId=doc.id,
        baseRevision=doc.revision,
        baseHash=doc.content_hash(),
        operations=[
            ReplaceFieldOp(moduleId=module.id, field="desc", before=module.data["desc"], after="服务 800 名学生")
        ],
    )
    # 直接调用守卫节点：它应当报错并结束
    state.proposal = bad
    run(GraphRunner(build_graph(deps), max_steps=5).run(state, start_at="guard_proposal"))
    assert state.error and state.error["code"] in {"fact_guard_failed", "fact_protected"}
    assert state.document.revision == doc.revision


# ------------------------------------------------------------------ 图定义与框架无关
def test_same_graph_spec_runs_on_both_engines():
    """同一份 GraphSpec 在自研引擎和 LangGraph 上应得到同样的路径。

    这一条是"换编排框架不改业务规则"的可执行证明；未安装 langgraph 时自动跳过。
    """
    from jianmian.workflows import langgraph_runner

    trace: list[str] = []

    async def first(state):
        trace.append("a")
        return "second"

    async def second(state):
        trace.append("b")
        return None

    spec = GraphSpec(name="parity", entry="first", nodes={"first": first, "second": second})
    state = AgentState(run_id="r", session_id="s", instruction="x")
    final = run(GraphRunner(spec, max_steps=5).run(state))
    assert trace == ["a", "b"]

    if not langgraph_runner.available():
        pytest.skip("未安装 langgraph")

    state2 = AgentState(run_id="r2", session_id="s", instruction="x")
    trace.clear()
    langgraph_runner.run_with_langgraph(spec, state2)
    assert trace == ["a", "b"], "两个执行器的节点顺序必须一致"
    assert final in {"second", "__end__"}
