"""测试用例 TC-001：一句话 → 一份简历 → 多轮修改（端到端主链路）

这是整个系统最关键的一条用例：它把"用户只输入一句话，最后拿到一份可用的简历"
这条主干从头走到尾，并且沿途检查四个不可退让的约束：

1. 提案不落地 —— 采纳之前，服务端不得改动文档（版本号不能自己往前跑）；
2. 整批原子应用 —— 采纳后版本只 +1，模块一次性补齐，不存在"改了一半"；
3. 采纳幂等 —— 同一个提案重复提交返回 replayed，版本不重复推进；
4. 硬事实守恒 —— 第二轮改写措辞可以变，手机号、邮箱、300 这些事实不能变。

运行方式（两种都行）：
    python -m pytest tests/test_case_tc001.py -v -s
    python tests/test_case_tc001.py

用例自带环境（临时目录 + mock 模型），不打网络、不需要 Key、不写用户目录。
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------- 用例数据
#: 用户第一次说的话：口语化，夹带岗位、项目、联系方式、教育背景（真实场景就是这样）
FIRST_INSTRUCTION = (
    "我是大三学生，想投 Python 后端，用 Flask 做过选课系统，服务 300 名学生。"
    "姓名：张三，电话 13800138000，邮箱 zhangsan@example.com，"
    "学校：江城大学，专业：计算机科学与技术，本科，时间 2024.09-2025.06"
)
#: 第二轮：只改措辞，明确不许动数字
SECOND_INSTRUCTION = "把选课系统的项目详情写得更专业一些，不要改数字"

#: 无论怎么改写都必须原样保留的硬事实
MUST_KEEP = ["13800138000", "zhangsan@example.com", "300"]

_STEP_NO = 0


def _step(title: str, expectation: str) -> None:
    global _STEP_NO
    _STEP_NO += 1
    print(f"\n[步骤 {_STEP_NO}] {title}")
    print(f"  期望：{expectation}")


def _ok(detail: str) -> None:
    print(f"  实际：{detail}  ✔")


def _build_client():
    """按测试约定现场装配一个应用：mock 模型 + 临时岗位库。"""
    from fastapi.testclient import TestClient

    from jianmian.api.app import create_app
    from jianmian.application.container import build_container
    from jianmian.application.services import Services
    from jianmian.config import Settings

    tmp = tempfile.mkdtemp(prefix="tc001-")
    settings = Settings(
        env="test",
        debug=True,
        model_provider="mock",
        session_secret="tc001-secret-key-for-hmac-only",
        job_db_path=str(Path(tmp) / "jobs.sqlite3"),
        rate_limit_per_minute=10_000,
        rate_limit_burst=5_000,
        daily_token_budget=1_000_000,
    )
    services = Services.build(build_container(settings))
    app = create_app(services=services, settings=services.container.settings)
    return TestClient(app), services


def _wait(client, run_id: str, timeout: float = 10.0) -> dict:
    """轮询到 run 停下（不再 running）。"""
    deadline = time.time() + timeout
    snapshot: dict = {}
    while time.time() < deadline:
        snapshot = client.get(f"/api/runs/{run_id}").json()
        if snapshot["status"] != "running":
            return snapshot
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} 超时未结束：{json.dumps(snapshot, ensure_ascii=False)}")


def _all_text(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False)


def _module_count(document: dict) -> int:
    return len(document.get("modules") or [])


# ---------------------------------------------------------------- 主用例
def test_tc001_one_sentence_to_resume() -> None:
    """TC-001：一句指令到一份简历，再改一轮，全程版本与事实可控。"""
    from jianmian.domain.resume import new_document

    client, services = _build_client()
    try:
        # ---------------------------------------------------------- 步骤 1
        _step(
            "准备空白简历",
            "revision=0，只有 basic/summary 两个空骨架，字段全为空串（第一次打开应用）",
        )
        document = new_document().model_dump(mode="json")
        assert document["revision"] == 0
        skeleton = [m["type"] for m in document["modules"]]
        assert skeleton == ["basic", "summary"], skeleton
        for module in document["modules"]:
            assert all(str(v).strip() == "" for v in module["data"].values()), module
        _ok(f"revision=0，骨架 {skeleton}，字段全空")

        csrf = {"x-jm-csrf": client.get("/api/config").json()["csrfToken"]}

        # ---------------------------------------------------------- 步骤 2
        _step(
            "提交第一句话（含姓名/电话/邮箱/学校/项目）",
            "HTTP 202，立刻返回 runId，请求不被模型阻塞",
        )
        started = time.time()
        response = client.post(
            "/api/runs",
            json={
                "instruction": FIRST_INSTRUCTION,
                "document": document,
                "targetJob": "Python 后端开发",
            },
            headers=csrf,
        )
        assert response.status_code == 202, response.text
        run_id = response.json()["runId"]
        cost_ms = (time.time() - started) * 1000
        assert response.json()["status"] in {"running", "awaiting_user"}
        _ok(f"202，runId={run_id}，{cost_ms:.0f}ms 返回（异步执行）")

        # ---------------------------------------------------------- 步骤 3
        _step(
            "等智能体出结果",
            "状态停在 awaiting_user，给出提案（operations 非空），但文档还没被改",
        )
        snapshot = _wait(client, run_id)
        assert snapshot["status"] == "awaiting_user", snapshot
        assert snapshot["intent"] == "build", snapshot["intent"]
        proposal = snapshot["proposal"]
        assert proposal and proposal["operations"], "一句话应能生成提案"
        kinds = [op["op"] if "op" in op else op.get("kind") for op in proposal["operations"]]
        print(f"  提案摘要：{snapshot['message'][:60]}…")
        print(f"  操作类型：{kinds}")
        # 提案只是"草稿"：baseRevision 必须等于用户当前的 0
        assert proposal["baseRevision"] == 0, proposal["baseRevision"]
        # 服务端工作副本也不能自己往前跑
        assert snapshot["revision"] == 0, snapshot["revision"]
        _ok(f"{len(proposal['operations'])} 个操作，baseRevision=0，文档仍为 v0")

        # ---------------------------------------------------------- 步骤 4
        _step(
            "整批采纳提案",
            "applied=True，revision 只 +1，模块补齐，硬事实进入文档",
        )
        accepted = client.post(
            f"/api/runs/{run_id}/decisions",
            json={"kind": "proposal", "action": "accept", "document": document},
            headers=csrf,
        )
        assert accepted.status_code == 200, accepted.text
        body = accepted.json()
        assert body["applied"] is True, body
        document_v1 = body["document"]
        assert document_v1["revision"] == 1, document_v1["revision"]
        assert _module_count(document_v1) > len(document["modules"]), _module_count(document_v1)
        types = sorted({m["type"] for m in document_v1["modules"]})
        assert "project" in types, types
        text_v1 = _all_text(document_v1)
        missing = [token for token in MUST_KEEP if token not in text_v1]
        assert not missing, f"提案把事实弄丢了：{missing}\n{text_v1}"
        _ok(
            f"revision=1，模块 {_module_count(document_v1)} 个 {types}，"
            f"事实齐全（{'/'.join(MUST_KEEP)}）"
        )

        # ---------------------------------------------------------- 步骤 5
        _step(
            "用户手滑，把同一个提案再点一次「采纳」",
            "返回 replayed=True，版本仍是 1（幂等，不重复加模块）",
        )
        replay = client.post(
            f"/api/runs/{run_id}/decisions",
            json={"kind": "proposal", "action": "accept", "document": document},
            headers=csrf,
        )
        assert replay.status_code == 200, replay.text
        replayed = replay.json()
        assert replayed.get("replayed") is True, replayed
        assert replayed["document"]["revision"] == 1
        assert _module_count(replayed["document"]) == _module_count(document_v1)
        _ok("replayed=True，revision 保持 1，模块数量不变")

        # ---------------------------------------------------------- 步骤 6
        _step(
            "基于 v1 提第二轮要求：「更专业，不要改数字」",
            "再次出提案；用被篡改过的文档尝试采纳应被 409 拒绝",
        )
        second = client.post(
            "/api/runs",
            json={
                "instruction": SECOND_INSTRUCTION,
                "document": document_v1,
                "targetJob": "Python 后端开发",
            },
            headers=csrf,
        )
        assert second.status_code == 202, second.text
        run2 = second.json()["runId"]
        snapshot2 = _wait(client, run2)
        assert snapshot2["status"] == "awaiting_user", snapshot2
        assert snapshot2["intent"] == "edit", snapshot2["intent"]
        assert snapshot2["proposal"]["operations"], "第二轮应给出改写提案"
        assert snapshot2["proposal"]["baseRevision"] == 1

        # 6a 拿一份"被前端改坏了"的文档（版本号对不上）去采纳 → 必须拒绝
        tampered = json.loads(json.dumps(document_v1))
        tampered["revision"] = 99
        rejected = client.post(
            f"/api/runs/{run2}/decisions",
            json={"kind": "proposal", "action": "accept", "document": tampered},
            headers=csrf,
        )
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["error"]["code"] in {"revision_conflict", "candidate_mismatch"}
        _ok(f"篡改文档被拒（409 {rejected.json()['error']['code']}），提案未被偷偷应用")

        # ---------------------------------------------------------- 步骤 7
        _step(
            "用正确的 v1 采纳第二轮提案",
            "revision=2，措辞有变化，但手机号/邮箱/300 一个都不能变",
        )
        accepted2 = client.post(
            f"/api/runs/{run2}/decisions",
            json={"kind": "proposal", "action": "accept", "document": document_v1},
            headers=csrf,
        )
        assert accepted2.status_code == 200, accepted2.text
        document_v2 = accepted2.json()["document"]
        assert document_v2["revision"] == 2, document_v2["revision"]
        text_v2 = _all_text(document_v2)
        for token in MUST_KEEP:
            assert token in text_v2, f"改写后事实丢失：{token}"
        # 措辞应真的变了（否则就是空提案，属于另一类缺陷）
        changed = [
            op for op in snapshot2["proposal"]["operations"] if op.get("before") != op.get("after")
        ]
        assert changed, "第二轮提案应至少有一处真实改动"
        _ok(f"revision=2，{len(changed)} 处字段被改写，事实全部保留")

        print("\n结果：PASS —— 一句话建简历、整批采纳、幂等重放、多轮改写、事实守恒均符合预期")
    finally:
        services.shutdown()
        client.close()


if __name__ == "__main__":
    test_tc001_one_sentence_to_resume()
