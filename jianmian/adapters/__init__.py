"""适配器工厂：按配置装配具体实现。

编排层/应用层只拿端口，不知道背后是 mock 还是 deepseek、SQLite 还是内存。
换实现 = 改这里一行，不改业务。
"""

from __future__ import annotations

from ..config import Settings
from ..ports.budget import BudgetStore
from ..ports.model import ModelProvider
from ..ports.parser import ParserAdapter
from ..ports.search import SearchProvider
from ..ports.store import RunStore
from .budget_memory import InMemoryBudgetStore
from .model_deepseek import DeepSeekProvider
from .model_mock import MockModelProvider
from .parser_docx import DocxParser
from .parser_pdf import PdfParser
from .search_local import LocalJobSearchProvider
from .store_memory import InMemoryRunStore
from .web_fetch import JdUrlFetcher, RemoteSearchProvider


class ModelNotConfigured(Exception):
    """配置要求真实模型但没有 Key：明确报错，不静默降级为假数据。"""


def build_model_provider(settings: Settings, *, byok: str | None = None) -> ModelProvider:
    """BYOK 只用于**本次请求**，不写日志、不进状态、不持久化。"""
    if settings.model_provider == "deepseek":
        key = byok or settings.owner_key
        if not key:
            raise ModelNotConfigured("未配置模型 Key")
        return DeepSeekProvider(
            key,
            base_url=settings.model_base_url,
            default_model=settings.model_name,
            timeout=settings.model_timeout_seconds,
            max_retries=settings.model_max_retries,
        )
    return MockModelProvider(settings.model_name)


def build_run_store(settings: Settings) -> RunStore:
    return InMemoryRunStore(max_events=settings.max_events_per_run)


def build_budget_store(settings: Settings) -> BudgetStore:
    return InMemoryBudgetStore(daily_tokens=settings.daily_token_budget)


def build_job_provider(settings: Settings) -> SearchProvider:
    if settings.web_search_enabled:
        remote = RemoteSearchProvider()
        if remote.available:
            return remote
    return LocalJobSearchProvider(settings.job_db_path)


def build_parsers() -> dict[str, ParserAdapter]:
    return {"pdf": PdfParser(), "docx": DocxParser()}


def build_jd_fetcher(settings: Settings) -> JdUrlFetcher:
    return JdUrlFetcher(timeout=settings.web_fetch_timeout)
