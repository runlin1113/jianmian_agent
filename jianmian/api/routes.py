"""业务路由（第 12.1 节首批 API）。

刻意**没有** POST /resumes：简历主数据留在浏览器，服务端只保存 run 的工作副本。
这样"服务端不持久化简历正文"不是一句声明，而是路由上根本不存在这个入口。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from ..application.runs import public_view
from ..domain import errors
from ..domain.modules import DENSITY_BUDGETS, MODULE_SPECS, TEMPLATES, THEMES, DEFAULT_APPEARANCE
from ..domain.resume import new_document, validate_document
from ..security.net import UploadRejected
from .guards import client_ip, session_id
from .schemas import (
    Decision,
    ForgetPlanIn,
    InterviewAnswerIn,
    InterviewStartIn,
    JobMatchIn,
    MemoryConfirmIn,
    MemoryExtractIn,
    RunStart,
)

router = APIRouter()


def _services(request: Request):
    return request.app.state.services


def _byok(request: Request) -> str | None:
    """BYOK 只走请求头：不进 JSON、不进日志、不进事件。"""
    settings = _services(request).container.settings
    if not settings.allow_byok:
        return None
    raw = request.headers.get("x-jm-byok") or ""
    return raw.strip() or None


async def _read_upload(request: Request, upload: UploadFile | None) -> tuple[str, bytes]:
    if upload is None:
        raise errors.contract_error("缺少 file 字段")
    limit = _services(request).container.settings.max_upload_bytes
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise UploadRejected("payload_too_large", f"文件超过 {limit // (1024 * 1024)} MB 上限")
    return upload.filename or "upload", data


# ----------------------------------------------------------------------
# 基础
# ----------------------------------------------------------------------
@router.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"ok": True}


@router.post("/session")
async def bootstrap_session(request: Request) -> dict[str, Any]:
    services = _services(request)
    sid = session_id(request)
    return {
        "csrfToken": services.container.signer.csrf_token(sid),
        "expiresIn": services.container.settings.run_ttl_seconds,
    }


@router.get("/config")
async def get_config(request: Request) -> dict[str, Any]:
    services = _services(request)
    settings = services.container.settings
    sid = session_id(request)
    return {
        **settings.public_view(),
        "csrfToken": services.container.signer.csrf_token(sid),
        "limits": {
            "maxInstructionChars": 4000,
            "maxFormatRepairs": settings.max_format_repairs,
            "runBudgetSeconds": settings.run_budget_seconds,
            "runTtlSeconds": settings.run_ttl_seconds,
            "maxEventsPerRun": settings.max_events_per_run,
        },
    }


@router.get("/meta/modules")
async def meta_modules() -> dict[str, Any]:
    """模块注册表：前端据此动态渲染编辑器与字段权限提示。"""
    return {
        "modules": [
            {
                "type": spec.type,
                "zh": spec.zh,
                "icon": spec.icon,
                "slot": spec.slot,
                "multiple": spec.multiple,
                "skippable": spec.skippable,
                "titleField": spec.title_field,
                "aiTarget": spec.ai_target,
                "fields": [
                    {
                        "name": f.name,
                        "label": f.label,
                        "kind": f.kind,
                        "policy": f.policy,
                        "aiEditable": f.ai_editable,
                        "maxLength": f.max_length,
                    }
                    for f in spec.fields
                ],
            }
            for spec in MODULE_SPECS
        ],
        "templates": list(TEMPLATES),
        "themes": list(THEMES),
        "defaultAppearance": DEFAULT_APPEARANCE,
        "densityBudgets": DENSITY_BUDGETS,
    }


@router.get("/meta/toolbox")
async def meta_toolbox(request: Request) -> dict[str, Any]:
    """工具目录（只读）：前端可以展示"智能体能做什么 / 不能做什么"。"""
    registry = _services(request).container.registry
    return {"tools": registry.catalog()}  # type: ignore[union-attr]


# ----------------------------------------------------------------------
# Run
# ----------------------------------------------------------------------
@router.post("/runs")
async def create_run(request: Request, payload: RunStart) -> JSONResponse:
    services = _services(request)
    sid = session_id(request)
    record = await services.runs.create(
        sid, payload, byok_key=_byok(request), request_id=getattr(request.state, "request_id", "")
    )
    return JSONResponse(status_code=202, content=public_view(record))


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str) -> dict[str, Any]:
    record = _services(request).runs.get(run_id, session_id(request))
    return public_view(record)


@router.get("/runs/{run_id}/events")
async def stream_events(request: Request, run_id: str):
    services = _services(request)
    sid = session_id(request)
    record = services.runs.get(run_id, sid)  # 先做所有权校验，再开流

    after = 0
    last_event_id = request.headers.get("last-event-id") or request.query_params.get("after") or "0"
    try:
        after = max(0, int(last_event_id))
    except ValueError:
        after = 0

    async def gen():
        yield "retry: 2000\n\n"
        async for item in services.runs.events_since(record.id, sid, after):
            if item["type"] == "heartbeat":
                yield ": ping\n\n"
                continue
            data = json.dumps(item, ensure_ascii=False)
            head = f"id: {item['seq']}\nevent: {item['type']}\n"
            yield f"{head}data: {data}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/runs/{run_id}/decisions")
async def decide(request: Request, run_id: str, payload: Decision) -> dict[str, Any]:
    services = _services(request)
    return await services.runs.decide(
        run_id, session_id(request), payload, byok_key=_byok(request)
    )


@router.post("/runs/{run_id}/cancel")
async def cancel_run(request: Request, run_id: str) -> dict[str, Any]:
    record = _services(request).runs.cancel(run_id, session_id(request))
    return public_view(record)


# ----------------------------------------------------------------------
# 导入
# ----------------------------------------------------------------------
@router.post("/imports")
async def create_import(request: Request, file: UploadFile | None = File(default=None)) -> dict[str, Any]:
    filename, data = await _read_upload(request, file)
    draft = await _services(request).imports.ingest(session_id(request), filename=filename, data=data)
    return _services(request).imports.public_view(draft)


@router.get("/imports/{import_id}")
async def get_import(request: Request, import_id: str) -> dict[str, Any]:
    services = _services(request)
    draft = services.imports.get(import_id, session_id(request))
    return services.imports.public_view(draft)


# ----------------------------------------------------------------------
# 岗位匹配
# ----------------------------------------------------------------------
@router.post("/jobs/match")
async def match_job(request: Request, payload: JobMatchIn) -> dict[str, Any]:
    document = validate_document(payload.document)
    report = await _services(request).jobs.match(
        target_job=payload.targetJob, document=document, city=payload.city, limit=payload.limit
    )
    return report.model_dump(mode="json")


# ----------------------------------------------------------------------
# 面试
# ----------------------------------------------------------------------
@router.post("/interviews")
async def start_interview(request: Request, payload: InterviewStartIn) -> dict[str, Any]:
    services = _services(request)
    document = validate_document(payload.document)
    session, question = await services.interviews.create(
        session_id(request),
        document=document,
        target_job=payload.targetJob,
        topics=payload.topics,
        byok_key=_byok(request),
    )
    return {"question": question, **services.interviews.public(session)}


@router.get("/interviews/{interview_id}")
async def get_interview(request: Request, interview_id: str) -> dict[str, Any]:
    services = _services(request)
    return services.interviews.public(services.interviews.get(session_id(request), interview_id))


@router.post("/interviews/{interview_id}/turns")
async def answer_interview(
    request: Request, interview_id: str, payload: InterviewAnswerIn
) -> dict[str, Any]:
    services = _services(request)
    return await services.interviews.answer(
        session_id(request),
        interview_id,
        turn_id=payload.turnId,
        text=payload.answer,
        byok_key=_byok(request),
    )


@router.get("/interviews/{interview_id}/report")
async def interview_report(request: Request, interview_id: str) -> dict[str, Any]:
    services = _services(request)
    report = services.interviews.report(session_id(request), interview_id)
    return report.model_dump(mode="json")


# ----------------------------------------------------------------------
# 记忆
# ----------------------------------------------------------------------
@router.get("/profile")
async def get_profile(request: Request) -> dict[str, Any]:
    return _services(request).profile.public(session_id(request))


@router.post("/profile/extract")
async def extract_memory(request: Request, payload: MemoryExtractIn) -> dict[str, Any]:
    services = _services(request)
    candidates = await services.profile.extract(
        session_id(request), payload.text, byok_key=_byok(request)
    )
    return {
        "candidates": [c.model_dump(mode="json") for c in candidates],
        "note": "候选需要你确认后才会保存；不确认就不会进入任何后续上下文。",
    }


@router.post("/profile/facts")
async def confirm_memory(request: Request, payload: MemoryConfirmIn) -> dict[str, Any]:
    services = _services(request)
    services.profile.confirm(session_id(request), payload.candidates)
    return services.profile.public(session_id(request))


@router.delete("/profile/facts/{fact_id}")
async def forget_memory(request: Request, fact_id: str) -> dict[str, Any]:
    services = _services(request)
    profile, plan = services.profile.forget(session_id(request), fact_id)
    return {**services.profile.public(session_id(request)), "plan": plan}


@router.post("/profile/forget-plan")
async def forget_plan(request: Request, payload: ForgetPlanIn) -> dict[str, Any]:
    return _services(request).profile.forget_plan(payload.scope, fact_id=payload.factId)


# ----------------------------------------------------------------------
# 演示辅助（只读、无副作用，便于排查环境）
# ----------------------------------------------------------------------
@router.get("/debug/limits")
async def debug_limits(request: Request) -> dict[str, Any]:
    services = _services(request)
    settings = services.container.settings
    sid = session_id(request)
    return {
        "clientIp": client_ip(request),
        "dailyTokens": settings.daily_token_budget,
        "budgetRemaining": services.container.budget.remaining(sid),
        "runStats": services.container.store.stats(),
        "modelProvider": settings.model_provider,
        "resume": new_document().summary(),
    }
