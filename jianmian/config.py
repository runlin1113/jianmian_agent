"""集中配置。

所有可能因部署形态而变化的量都在这里，且全部可通过环境变量覆盖：
本地隐私档、课程演示档、公开多人档只需改环境变量，不改代码。

注意：模型 Key 只从服务端环境变量读取，**不**进入任何返回体、日志或前端状态。
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "apps" / "web"
KNOWLEDGE_DIR = BASE_DIR / "knowledge" / "jobs"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


#: 服务端允许转发的模型白名单。浏览器传来的 model 只能落在集合内。
ALLOWED_MODELS: tuple[str, ...] = ("deepseek-chat", "deepseek-reasoner")


@dataclass(frozen=True)
class Settings:
    """不可变配置快照。测试通过 `Settings(...)` 直接构造替身。"""

    app_name: str = "简面智能体 · Demo"
    env: str = field(default_factory=lambda: os.getenv("JIANMIAN_ENV", "demo"))
    debug: bool = field(default_factory=lambda: _env_bool("JIANMIAN_DEBUG", True))

    # ---- 模型 ----
    # mock：完全离线、确定性、零成本（默认，保证 demo 开箱可跑）
    # deepseek：真实云模型，需要 OWNER_KEY 或请求级 BYOK
    model_provider: str = field(default_factory=lambda: os.getenv("JIANMIAN_MODEL_PROVIDER", "mock"))
    model_name: str = field(default_factory=lambda: os.getenv("JIANMIAN_MODEL_NAME", "deepseek-chat"))
    model_base_url: str = field(
        default_factory=lambda: os.getenv("JIANMIAN_MODEL_BASE_URL", "https://api.deepseek.com")
    )
    owner_key: str | None = field(default_factory=lambda: os.getenv("JIANMIAN_OWNER_KEY") or None)
    allow_byok: bool = field(default_factory=lambda: _env_bool("JIANMIAN_ALLOW_BYOK", True))
    model_timeout_seconds: float = field(default_factory=lambda: _env_float("JIANMIAN_MODEL_TIMEOUT", 45.0))
    model_max_retries: int = field(default_factory=lambda: _env_int("JIANMIAN_MODEL_RETRIES", 2))

    # ---- 编排上限（第 8.3 节，待压测的初始保护值）----
    max_tool_calls_per_run: int = field(default_factory=lambda: _env_int("JIANMIAN_MAX_TOOL_CALLS", 8))
    max_format_repairs: int = field(default_factory=lambda: _env_int("JIANMIAN_MAX_FORMAT_REPAIRS", 2))
    max_compress_attempts: int = field(default_factory=lambda: _env_int("JIANMIAN_MAX_COMPRESS", 2))
    run_budget_seconds: float = field(default_factory=lambda: _env_float("JIANMIAN_RUN_BUDGET", 120.0))
    min_font_pt: float = field(default_factory=lambda: _env_float("JIANMIAN_MIN_FONT_PT", 10.5))

    # ---- 运行状态与事件 TTL（第 13.2 节）----
    run_ttl_seconds: int = field(default_factory=lambda: _env_int("JIANMIAN_RUN_TTL", 1800))
    event_ttl_seconds: int = field(default_factory=lambda: _env_int("JIANMIAN_EVENT_TTL", 900))
    max_events_per_run: int = field(default_factory=lambda: _env_int("JIANMIAN_MAX_EVENTS", 400))

    # ---- 上传边界 ----
    max_upload_bytes: int = field(default_factory=lambda: _env_int("JIANMIAN_MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
    max_pdf_pages: int = field(default_factory=lambda: _env_int("JIANMIAN_MAX_PDF_PAGES", 20))

    # ---- 会话与限流 ----
    session_secret: str = field(
        default_factory=lambda: os.getenv("JIANMIAN_SESSION_SECRET") or secrets.token_urlsafe(32)
    )
    session_cookie: str = "jm_sid"
    csrf_header: str = "x-jm-csrf"
    rate_limit_per_minute: int = field(default_factory=lambda: _env_int("JIANMIAN_RATE_PER_MIN", 40))
    rate_limit_burst: int = field(default_factory=lambda: _env_int("JIANMIAN_RATE_BURST", 12))
    daily_token_budget: int = field(default_factory=lambda: _env_int("JIANMIAN_DAILY_TOKENS", 60_000))
    #: 预算/配额设施缺失时，站长 Key 路径必须关闭（第 13.1 节）
    require_budget_infra: bool = field(default_factory=lambda: _env_bool("JIANMIAN_REQUIRE_BUDGET", True))

    # ---- 联网检索 ----
    web_search_enabled: bool = field(default_factory=lambda: _env_bool("JIANMIAN_WEB_SEARCH", False))
    web_fetch_timeout: float = field(default_factory=lambda: _env_float("JIANMIAN_WEB_TIMEOUT", 8.0))

    # ---- 公共岗位库 ----
    job_db_path: str = field(
        default_factory=lambda: os.getenv("JIANMIAN_JOB_DB", str(BASE_DIR / "knowledge" / "jobs.sqlite3"))
    )

    # ---- 前端 ----
    web_dir: Path = WEB_DIR

    def public_view(self) -> dict:
        """可安全下发给前端的配置子集（绝不含密钥）。"""
        return {
            "appName": self.app_name,
            "env": self.env,
            "modelProvider": self.model_provider,
            "modelName": self.model_name,
            "allowByok": self.allow_byok,
            "webSearchEnabled": self.web_search_enabled,
            "minFontPt": self.min_font_pt,
            "maxUploadBytes": self.max_upload_bytes,
            "maxPdfPages": self.max_pdf_pages,
            "maxToolCallsPerRun": self.max_tool_calls_per_run,
            "maxCompressAttempts": self.max_compress_attempts,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """测试用：让环境变量改动生效。"""
    get_settings.cache_clear()
