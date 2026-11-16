"""依赖装配（composition root）。

整个应用只有这里知道"哪个实现对应哪个端口"。换成 Redis、换成真实模型、
换成外部岗位库，都只改这个文件，其余层不动。

三种部署形态由配置区分，代码同一份：
- 本地隐私档：mock 模型 + 有界内存 + 不联网；
- 课程演示档：站长 Key + 有界内存 + 种子岗位库；
- 公开多人档：需要 TTL 共享存储与独立预算（端口不变，换实现）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..adapters.budget_memory import InMemoryBudgetStore, UnlimitedBudgetStore
from ..adapters.model_deepseek import DeepSeekProvider
from ..adapters.model_mock import MockModelProvider
from ..adapters.parser_docx import DocxParser
from ..adapters.parser_pdf import PdfParser
from ..adapters.search_local import LocalJobSearchProvider
from ..adapters.store_memory import InMemoryRunStore
from ..config import ALLOWED_MODELS, Settings
from ..domain import errors
from ..ports.model import ModelProvider
from ..ports.parser import ParserAdapter
from ..security.limits import TokenBucketLimiter
from ..security.session import SessionSigner
from ..workflows.tools import build_registry


@dataclass
class AppContainer:
    settings: Settings
    store: InMemoryRunStore
    budget: InMemoryBudgetStore
    unlimited_budget: UnlimitedBudgetStore
    signer: SessionSigner
    limiter: TokenBucketLimiter
    job_provider: LocalJobSearchProvider
    parsers: dict[str, ParserAdapter] = field(default_factory=dict)
    registry: object | None = None

    # ---- 按请求解析模型 ------------------------------------------------
    def model_for(self, byok_key: str | None) -> ModelProvider:
        """返回本次请求应使用的模型适配器。

        优先级：显式 BYOK（且开关允许）> 站长 Key > mock。
        浏览器传来的 base_url / model 一律丢弃，只允许服务端白名单内的模型名。
        """
        provider = (self.settings.model_provider or "mock").lower()
        if provider == "mock":
            return MockModelProvider()
        key = None
        if self.settings.allow_byok and byok_key:
            key = byok_key.strip()
        elif self.settings.owner_key:
            key = self.settings.owner_key
        if not key:
            raise errors.DomainError(
                "model_unavailable",
                "服务端没有可用模型额度，且未提供你自己的 Key。可以切换到离线模式继续编辑。",
                status=503,
                retryable=False,
            )
        return DeepSeekProvider(
            key,
            base_url=self.settings.model_base_url,
            default_model=self.settings.model_name,
            allowed_models=ALLOWED_MODELS,
            timeout=self.settings.model_timeout_seconds,
            max_retries=self.settings.model_max_retries,
        )

    def budget_for(self, *, byok: bool):
        """BYOK 走不计费通道：配额是站长的，不应该限制用户自己的 Key。"""
        return self.unlimited_budget if byok else self.budget


def build_container(settings: Settings | None = None) -> AppContainer:
    settings = settings or Settings()
    store = InMemoryRunStore(max_runs=500, max_events=settings.max_events_per_run)
    budget = InMemoryBudgetStore(daily_tokens=settings.daily_token_budget)
    signer = SessionSigner(settings.session_secret)
    limiter = TokenBucketLimiter(
        per_minute=settings.rate_limit_per_minute, burst=settings.rate_limit_burst
    )
    job_path = Path(settings.job_db_path)
    if not job_path.parent.exists():
        job_path.parent.mkdir(parents=True, exist_ok=True)
    job_provider = LocalJobSearchProvider(job_path)
    parsers: dict[str, ParserAdapter] = {}
    for parser in (PdfParser(), DocxParser()):
        for ext in parser.supports:
            parsers[ext] = parser
    container = AppContainer(
        settings=settings,
        store=store,
        budget=budget,
        unlimited_budget=UnlimitedBudgetStore(),
        signer=signer,
        limiter=limiter,
        job_provider=job_provider,
        parsers=parsers,
        registry=build_registry(settings),
    )
    return container
