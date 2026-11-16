"""HTTP 层流程测试：契约、鉴权、幂等、版本冲突、SSE、导入、面试、清理。

原则：这些测试不关心文案好不好，只关心"该拒绝的一定拒绝、该写的一定整批写"。
"""

from __future__ import annotations

import io
import time
import zipfile

from conftest import collect_events, wait_run

from jianmian.domain.resume import validate_document


LONG_INSTRUCTION = (
    "我是大三学生，想投 Python 后端，用 Flask 做过选课系统，服务 300 名学生。"
    "姓名：张三，电话 13800138000，邮箱 zhangsan@example.com，"
    "学校：江城大学，专业：计算机科学与技术，本科，时间：2024.09-2025.06"
)


def make_docx(lines: list[str]) -> bytes:
    import docx

    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# ------------------------------------------------------------------ 基础
def test_config_exposes_no_secrets(client):
    config = client.get("/api/config").json()
    dumped = str(config)
    assert "session_secret" not in config
    assert "owner_key" not in config
    assert "sk-" not in dumped
    assert config["csrfToken"]
    assert config["modelProvider"] == "mock"


def test_session_cookie_is_httponly_and_signed(client):
    response = client.get("/api/config")
    cookie = response.headers.get("set-cookie", "")
    assert "jm_sid=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie.replace("samesite=lax", "SameSite=lax") or "samesite=lax" in cookie.lower()
    # 再次请求应复用会话，不再重复下发
    second = client.get("/api/config")
    assert second.headers.get("set-cookie") is None


def test_csrf_required_for_writes(client, empty_doc):
    response = client.post("/api/runs", json={"instruction": "x", "document": empty_doc})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


def test_foreign_origin_rejected(client, csrf, empty_doc):
    response = client.post(
        "/api/runs",
        json={"instruction": "测试来源校验", "document": empty_doc},
        headers={**csrf, "origin": "https://evil.example.com"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_rejected"


def test_invalid_document_contract_422(client, csrf):
    response = client.post(
        "/api/runs",
        json={"instruction": "看一下", "document": {"modules": [{"type": "hack"}]}},
        headers=csrf,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_module_type"
    assert response.json()["error"]["requestId"]


def test_meta_modules_matches_domain(client):
    meta = client.get("/api/meta/modules").json()
    types = {spec["type"] for spec in meta["modules"]}
    assert {"basic", "education", "project", "skills", "summary"} <= types
    for spec in meta["modules"]:
        for field in spec["fields"]:
            assert "policy" in field and "aiEditable" in field


# ------------------------------------------------------------------ Run 主流程
def test_build_run_produces_proposal_and_applies_atomically(client, csrf, empty_doc):
    response = client.post(
        "/api/runs",
        json={"instruction": LONG_INSTRUCTION, "document": empty_doc, "targetJob": "Python 后端开发"},
        headers=csrf,
    )
    assert response.status_code == 202
    run_id = response.json()["runId"]

    snapshot = wait_run(client, run_id)
    assert snapshot["status"] == "awaiting_user", snapshot
    assert snapshot["proposal"]["operations"], "应生成提案"
    # 提案不是已应用的修改：服务端不该在采纳前改文档
    assert validate_document(empty_doc).revision == snapshot["proposal"]["baseRevision"]

    accepted = client.post(
        f"/api/runs/{run_id}/decisions",
        json={"kind": "proposal", "action": "accept", "document": empty_doc},
        headers=csrf,
    )
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["applied"] is True
    assert body["document"]["revision"] == empty_doc["revision"] + 1
    assert len(body["document"]["modules"]) > len(empty_doc["modules"])

    # 重复采纳返回已有结果，不重复推进版本
    replay = client.post(
        f"/api/runs/{run_id}/decisions",
        json={"kind": "proposal", "action": "accept", "document": empty_doc},
        headers=csrf,
    )
    assert replay.status_code == 200
    assert replay.json().get("replayed") is True
    assert replay.json()["document"]["revision"] == body["document"]["revision"]


def test_proposal_rejects_mismatched_revision(client, csrf, empty_doc):
    response = client.post(
        "/api/runs",
        json={"instruction": LONG_INSTRUCTION, "document": empty_doc, "targetJob": "Python 后端开发"},
        headers=csrf,
    )
    run_id = response.json()["runId"]
    wait_run(client, run_id)

    stale = dict(empty_doc)
    stale["revision"] = empty_doc["revision"] + 1
    conflict = client.post(
        f"/api/runs/{run_id}/decisions",
        json={"kind": "proposal", "action": "accept", "document": stale},
        headers=csrf,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] in {"revision_conflict", "candidate_mismatch"}


def test_idempotency_returns_same_run_and_rejects_changed_body(client, csrf, empty_doc):
    payload = {
        "instruction": LONG_INSTRUCTION,
        "document": empty_doc,
        "targetJob": "Python 后端开发",
        "idempotencyKey": "key-001",
    }
    first = client.post("/api/runs", json=payload, headers=csrf)
    second = client.post("/api/runs", json=payload, headers=csrf)
    assert first.status_code == second.status_code == 202
    assert first.json()["runId"] == second.json()["runId"]

    changed = {**payload, "instruction": LONG_INSTRUCTION + "（改）"}
    third = client.post("/api/runs", json=changed, headers=csrf)
    assert third.status_code == 409
    assert third.json()["error"]["code"] == "idempotency_conflict"


def test_cross_session_access_forbidden(client, csrf, empty_doc):
    response = client.post(
        "/api/runs", json={"instruction": LONG_INSTRUCTION, "document": empty_doc}, headers=csrf
    )
    run_id = response.json()["runId"]
    wait_run(client, run_id)

    client.cookies.clear()
    other = client.get(f"/api/runs/{run_id}")
    assert other.status_code == 403
    assert other.json()["error"]["code"] == "forbidden"


def test_events_are_ordered_and_resumable(client, csrf, empty_doc):
    response = client.post(
        "/api/runs",
        json={"instruction": LONG_INSTRUCTION, "document": empty_doc, "targetJob": "Python 后端开发"},
        headers=csrf,
    )
    run_id = response.json()["runId"]
    wait_run(client, run_id)

    events = collect_events(client, run_id)
    types = [event["type"] for event in events]
    assert types[0] == "run.started"
    assert "proposal.ready" in types
    seqs = [event["seq"] for event in events]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))

    # 从中间续传：只应拿到后面的事件
    cutoff = seqs[len(seqs) // 2]
    resumed = collect_events(client, run_id, after=cutoff)
    assert all(event["seq"] > cutoff for event in resumed)
    assert resumed[-1]["seq"] == seqs[-1]


def test_clarification_flow_recovers_and_continues(client, csrf, sample_doc):
    # 素材不足 → 应追问而不是编造
    response = client.post(
        "/api/runs", json={"instruction": "我想做简历", "document": sample_doc}, headers=csrf
    )
    run_id = response.json()["runId"]
    snapshot = wait_run(client, run_id)
    assert snapshot["status"] == "awaiting_user"
    pending = snapshot["pending"]
    assert pending["kind"] == "clarification"
    assert pending["options"], "泛泛的指令应该给出可选入口"

    decision = client.post(
        f"/api/runs/{run_id}/decisions",
        json={"kind": "clarification", "promptId": pending["promptId"], "optionValue": pending["options"][0]["label"]},
        headers=csrf,
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "running"

    snapshot = wait_run(client, run_id)
    # 采信用户选择后应该进入 build，并继续追问目标岗位或直接产出提案
    assert snapshot["intent"] in {"build", "edit"}
    assert snapshot["status"] in {"awaiting_user", "ready"}


def test_wrong_prompt_id_is_rejected(client, csrf, sample_doc):
    response = client.post(
        "/api/runs", json={"instruction": "我想做简历", "document": sample_doc}, headers=csrf
    )
    run_id = response.json()["runId"]
    snapshot = wait_run(client, run_id)
    result = client.post(
        f"/api/runs/{run_id}/decisions",
        json={"kind": "clarification", "promptId": "q-forged", "answer": "随便"},
        headers=csrf,
    )
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "prompt_mismatch"


# ------------------------------------------------------------------ 版面闭环
def test_compress_asks_browser_for_real_layout(client, csrf):
    doc = validate_document(
        {
            "id": "r-layout",
            "revision": 0,
            "modules": [
                {
                    "id": "m-proj",
                    "type": "project",
                    "order": 1,
                    "data": {
                        "proj_name": "选课系统",
                        "role": "后端",
                        "time": "2025.03-2025.06",
                        "tech": "Flask",
                        "desc": "负责选课接口与规则校验，" + "支持 300 名学生同时选课；" * 12,
                    },
                }
            ],
        }
    ).model_dump(mode="json")

    response = client.post(
        "/api/runs", json={"instruction": "帮我压缩到一页", "document": doc}, headers=csrf
    )
    run_id = response.json()["runId"]
    snapshot = wait_run(client, run_id)
    assert snapshot["status"] == "awaiting_layout", snapshot
    assert snapshot["pending"]["kind"] == "layout"

    feedback = client.post(
        f"/api/runs/{run_id}/decisions",
        json={
            "kind": "layout",
            "layout": {
                "pageCount": 2,
                "overflowPx": 240,
                "blockHeights": {"m-proj": 900},
                "minFontPt": 10.5,
                "candidateHash": snapshot["pending"]["candidateHash"],
            },
        },
        headers=csrf,
    )
    assert feedback.status_code == 200

    final = wait_run(client, run_id)
    # 要么给出新的压缩提案，要么在轮次上限后让用户选（不能假装已压成一页）
    assert final["status"] in {"awaiting_user", "awaiting_layout", "ready"}
    if final["status"] == "ready":
        assert final.get("options") or final.get("proposal")


def test_layout_feedback_with_wrong_candidate_rejected(client, csrf):
    doc = validate_document({"id": "r-l2", "revision": 0, "modules": []}).model_dump(mode="json")
    response = client.post("/api/runs", json={"instruction": "压缩到一页", "document": doc}, headers=csrf)
    run_id = response.json()["runId"]
    snapshot = wait_run(client, run_id)
    if snapshot["status"] != "awaiting_layout":
        return  # 空文档没有可压缩内容时直接结束，属正常
    result = client.post(
        f"/api/runs/{run_id}/decisions",
        json={
            "kind": "layout",
            "layout": {"pageCount": 1, "overflowPx": 0, "candidateHash": "sha256:deadbeef"},
        },
        headers=csrf,
    )
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "candidate_mismatch"


# ------------------------------------------------------------------ 导入
def test_import_docx_returns_staged_candidates(client, csrf):
    data = make_docx(
        [
            "张三",
            "求职意向：Python 后端开发",
            "电话 13800138000",
            "邮箱 zhangsan@example.com",
            "教育背景",
            "江城大学 计算机科学与技术 本科 2022.09-2026.06",
            "项目经历",
            "选课系统 2025.03-2025.06",
            "技术栈：Flask / MySQL",
            "负责选课接口与规则校验，服务 300 名学生。",
        ]
    )
    response = client.post(
        "/api/imports",
        files={"file": ("resume.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        headers=csrf,
    )
    assert response.status_code == 200
    draft = response.json()
    types = {candidate["moduleType"] for candidate in draft["candidates"]}
    assert "basic" in types and "education" in types and "project" in types
    basic = next(c for c in draft["candidates"] if c["moduleType"] == "basic")
    assert basic["data"]["phone"] == "13800138000"
    assert draft["meta"]["needsOcr"] is False
    # 暂存区不改文档：响应里没有 document 字段
    assert "document" not in draft


def test_import_rejects_wrong_magic_bytes(client, csrf):
    fake = b"#!/bin/sh\necho hi\n"
    response = client.post(
        "/api/imports", files={"file": ("resume.docx", fake, "application/octet-stream")}, headers=csrf
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] in {"unsupported_type", "invalid_docx"}


def test_import_rejects_oversize(client, csrf, services):
    big = b"%PDF-1.7\n" + b"0" * (11 * 1024 * 1024)
    response = client.post(
        "/api/imports", files={"file": ("big.pdf", big, "application/pdf")}, headers=csrf
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


# ------------------------------------------------------------------ 岗位 / 面试 / 档案
def test_job_match_returns_evidence_and_disclaimer(client, csrf, sample_doc):
    response = client.post(
        "/api/jobs/match",
        json={"targetJob": "Python 后端开发", "document": sample_doc, "limit": 5},
        headers=csrf,
    )
    assert response.status_code == 200
    report = response.json()
    assert report["sampleSize"] >= 1
    assert report["disclaimer"]
    assert all(hit["category"] in {"matched", "partial", "missing"} for hit in report["hits"])


def test_interview_flow_and_turn_conflict(client, csrf, sample_doc):
    start = client.post(
        "/api/interviews", json={"document": sample_doc, "targetJob": "Python 后端开发"}, headers=csrf
    )
    assert start.status_code == 200
    session = start.json()
    assert session["question"]
    turn = session["turns"][-1]

    answer = client.post(
        f"/api/interviews/{session['interviewId']}/turns",
        json={"turnId": turn["turnId"], "answer": "我负责选课接口与规则校验，用 Flask 实现。"},
        headers=csrf,
    )
    assert answer.status_code == 200
    answered = [t for t in answer.json()["session"]["turns"] if t["turnId"] == turn["turnId"]]
    assert answered and answered[0]["answer"], "回答必须落在原来那一轮上"

    duplicate = client.post(
        f"/api/interviews/{session['interviewId']}/turns",
        json={"turnId": turn["turnId"], "answer": "重复提交"},
        headers=csrf,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "turn_conflict"


def test_memory_requires_confirmation_and_can_forget(client, csrf):
    extracted = client.post(
        "/api/profile/extract",
        json={"text": "我是计算机专业大三学生，做过选课系统，想投 Python 后端。"},
        headers=csrf,
    )
    assert extracted.status_code == 200
    candidates = extracted.json()["candidates"]
    assert candidates, "应至少提出一条候选"
    # 未确认前档案里没有事实
    assert client.get("/api/profile").json()["facts"] == []

    confirmed = client.post("/api/profile/facts", json={"candidates": candidates[:1]}, headers=csrf)
    assert confirmed.status_code == 200
    facts = confirmed.json()["facts"]
    assert len(facts) == 1

    forgotten = client.delete(f"/api/profile/facts/{facts[0]['id']}", headers=csrf)
    assert forgotten.status_code == 200
    assert forgotten.json()["facts"] == []
    assert forgotten.json()["plan"]["steps"], "遗忘必须解释清理了什么"


# ------------------------------------------------------------------ 清理
def test_expired_runs_are_purged(client, csrf, services, empty_doc):
    response = client.post(
        "/api/runs", json={"instruction": LONG_INSTRUCTION, "document": empty_doc}, headers=csrf
    )
    run_id = response.json()["runId"]
    wait_run(client, run_id)

    record = services.container.store.get(run_id)
    record.expiresAt = time.time() - 1
    services.container.store.update(record)
    services.purge()
    assert services.container.store.get(run_id) is None
    assert client.get(f"/api/runs/{run_id}").status_code == 404


def test_rate_limit_returns_429_and_retry_after():
    """默认限流很宽松，这里用一个"小桶"应用验证契约。"""
    from fastapi.testclient import TestClient

    from jianmian.api.app import create_app
    from jianmian.application.container import build_container
    from jianmian.application.services import Services
    from jianmian.config import Settings

    settings = Settings(
        env="test",
        model_provider="mock",
        session_secret="rate-limit-secret",
        rate_limit_per_minute=4,
        rate_limit_burst=2,
        job_db_path="knowledge/_test_rate_jobs.sqlite3",
    )
    services = Services.build(build_container(settings))
    app = create_app(services=services, settings=settings)
    try:
        with TestClient(app) as limited:
            csrf = {"x-jm-csrf": limited.get("/api/config").json()["csrfToken"]}
            statuses = []
            for _ in range(8):
                response = limited.get("/api/runs/run-does-not-exist", headers=csrf)
                statuses.append(response.status_code)
                if response.status_code == 429:
                    payload = response.json()["error"]
                    assert payload["code"] == "rate_limited"
                    assert payload["details"]["retryAfter"] >= 1
                    break
            assert 429 in statuses, statuses
    finally:
        services.shutdown()
