"""统一错误契约（第 12.1 节）。

对外永远只有 {code, message, requestId, retryable, details?}；
堆栈、上游响应、密钥一律不出网。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..domain.errors import DomainError
from ..security.net import UnsafeUrl, UploadRejected

log = logging.getLogger("jianmian.api")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or request.headers.get("x-request-id", "")


def _body(code: str, message: str, request: Request, *, retryable: bool = False, details: dict | None = None):
    payload = {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "requestId": _request_id(request),
        }
    }
    if details:
        payload["error"]["details"] = details
    return payload


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError):
        if exc.status >= 500:
            log.warning("domain_error_5xx code=%s request=%s", exc.code, _request_id(request))
        return JSONResponse(
            status_code=exc.status,
            content=_body(exc.code, exc.message, request, retryable=exc.retryable, details=exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        issues = [
            {"path": ".".join(str(p) for p in err.get("loc", [])[1:]), "reason": err.get("msg", "")}
            for err in exc.errors()[:8]
        ]
        return JSONResponse(
            status_code=422,
            content=_body("contract_violation", "请求参数不符合契约", request, details={"issues": issues}),
        )

    @app.exception_handler(UploadRejected)
    async def _upload(request: Request, exc: UploadRejected):
        status = 413 if exc.code in {"payload_too_large", "zip_bomb"} else 422
        return JSONResponse(
            status_code=status,
            content=_body(exc.code, exc.message, request, details=None),
        )

    @app.exception_handler(UnsafeUrl)
    async def _unsafe(request: Request, exc: UnsafeUrl):
        return JSONResponse(status_code=400, content=_body("unsafe_url", str(exc), request))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed", 413: "payload_too_large"}.get(
            exc.status_code, "http_error"
        )
        message = {
            404: "资源不存在",
            405: "方法不被支持",
            413: "请求体过大",
        }.get(exc.status_code, str(exc.detail) if isinstance(exc.detail, str) else "请求失败")
        return JSONResponse(status_code=exc.status_code, content=_body(code, message, request))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error request=%s", _request_id(request))
        return JSONResponse(
            status_code=500,
            content=_body("internal_error", "服务出现内部错误，请稍后重试", request, retryable=True),
        )
