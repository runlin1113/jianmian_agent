"""FastAPI 应用装配。

启动顺序有意为之：
1. 先装中间件（会话签名、安全头），保证每个响应都带上安全策略；
2. 再装守卫（限流、CSRF），只作用于 /api；
3. 最后挂静态资源与前端入口。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..application.services import Services
from ..config import Settings, get_settings
from .errors import install_error_handlers
from .guards import make_csrf_guard, make_rate_guard
from .middleware import (
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
    SessionMiddleware,
    build_csp,
)
from .routes import router

log = logging.getLogger("jianmian")
PURGE_INTERVAL_SECONDS = 60.0


def create_app(services: Services | None = None, settings: Settings | None = None) -> FastAPI:
    services = services or Services.build()
    settings = settings or services.container.settings
    secure_cookie = settings.env not in {"demo", "local", "test"}

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(_purge_loop(app))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            app.state.services.shutdown()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/api/docs" if settings.debug else None,
        openapi_url="/api/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )
    app.state.services = services

    app.add_middleware(
        SecurityHeadersMiddleware,
        csp=build_csp(),
    )
    app.add_middleware(
        SessionMiddleware,
        signer=services.container.signer,
        cookie_name=settings.session_cookie,
        secure=secure_cookie,
    )
    app.add_middleware(RequestIdMiddleware)

    install_error_handlers(app)

    guards = [
        Depends(make_rate_guard(services.container.limiter)),
        Depends(make_csrf_guard(services.container.signer, settings.csrf_header)),
    ]
    app.include_router(router, prefix="/api", dependencies=guards)

    _mount_frontend(app, settings)
    return app


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    web_dir: Path = Path(settings.web_dir)
    index = web_dir / "index.html"
    if (web_dir / "css").exists():
        app.mount("/css", StaticFiles(directory=web_dir / "css"), name="css")
    if (web_dir / "js").exists():
        app.mount("/js", StaticFiles(directory=web_dir / "js"), name="js")
    if (web_dir / "assets").exists():
        app.mount("/assets", StaticFiles(directory=web_dir / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def home():
        if not index.exists():
            return JSONResponse(
                status_code=200,
                content={"app": settings.app_name, "hint": "前端文件缺失，请查看 apps/web/index.html"},
            )
        return FileResponse(index, media_type="text/html; charset=utf-8")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        icon = web_dir / "assets" / "favicon.svg"
        if icon.exists():
            return FileResponse(icon, media_type="image/svg+xml")
        return JSONResponse(status_code=204, content=None)


async def _purge_loop(app: FastAPI) -> None:
    """真实的后台清理：过期的 run、导入暂存、面试会话都要被回收。"""
    while True:
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)
        try:
            stats = app.state.services.purge()
            log.debug("purge %s", stats)
        except Exception:  # pragma: no cover - 后台任务不允许拖垮主进程
            log.warning("purge failed", exc_info=True)


def build_default_app() -> FastAPI:
    return create_app(services=Services.build(), settings=get_settings())
