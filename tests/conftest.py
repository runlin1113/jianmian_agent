"""测试夹具。

原则：**不打网络、不用真 Key、不写用户目录**。
模型走 mock 适配器，岗位库落临时目录，会话密钥每次随机。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jianmian.application.container import build_container  # noqa: E402
from jianmian.application.services import Services  # noqa: E402
from jianmian.config import Settings  # noqa: E402
from jianmian.domain.resume import add_module, new_document  # noqa: E402


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(
        env="test",
        debug=True,
        model_provider="mock",
        session_secret="test-secret-key-for-hmac-only",
        job_db_path=str(tmp_path / "jobs.sqlite3"),
        rate_limit_per_minute=10_000,
        rate_limit_burst=5_000,
        daily_token_budget=1_000_000,
    )


@pytest.fixture()
def services(settings) -> Services:
    built = Services.build(build_container(settings))
    yield built
    built.shutdown()


@pytest.fixture()
def client(services):
    from fastapi.testclient import TestClient

    from jianmian.api.app import create_app

    app = create_app(services=services, settings=services.container.settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def csrf(client) -> dict[str, str]:
    config = client.get("/api/config").json()
    return {"x-jm-csrf": config["csrfToken"]}


@pytest.fixture()
def empty_doc() -> dict:
    return new_document().model_dump(mode="json")


@pytest.fixture()
def sample_doc() -> dict:
    """一份包含基本信息与两个项目的文档，字段直接给全，避免依赖命令函数的单例限制。"""
    from jianmian.domain.resume import validate_document

    return validate_document(
        {
            "id": "r-sample",
            "revision": 0,
            "targetJob": "Python 后端开发",
            "modules": [
                {
                    "id": "m-basic",
                    "type": "basic",
                    "order": 0,
                    "data": {
                        "name": "张三",
                        "phone": "13800138000",
                        "email": "zhangsan@example.com",
                        "job": "Python 后端开发",
                        "github": "github.com/zhangsan",
                    },
                },
                {
                    "id": "m-proj-1",
                    "type": "project",
                    "order": 1,
                    "data": {
                        "proj_name": "选课系统",
                        "role": "后端",
                        "time": "2025.03-2025.06",
                        "tech": "Flask",
                        "desc": "使用 Flask 实现选课功能，服务 300 名学生",
                    },
                },
                {
                    "id": "m-proj-2",
                    "type": "project",
                    "order": 2,
                    "data": {
                        "proj_name": "图书管理系统",
                        "role": "全栈",
                        "time": "2024.09-2024.12",
                        "tech": "Vue",
                        "desc": "负责前端页面与借阅接口",
                    },
                },
            ],
        }
    ).model_dump(mode="json")


def wait_run(client, run_id: str, *, timeout: float = 10.0) -> dict:
    """等到 run 不再 running / awaiting_*。"""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = client.get(f"/api/runs/{run_id}").json()
        if snapshot["status"] not in {"running"}:
            return snapshot
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} 超时未结束：{snapshot}")


def collect_events(client, run_id: str, *, after: int = 0) -> list[dict]:
    events: list[dict] = []
    with client.stream("GET", f"/api/runs/{run_id}/events?after={after}") as stream:
        for line in stream.iter_lines():
            if line.startswith("data:"):
                import json

                payload = json.loads(line[5:].strip())
                events.append(payload)
    return events
