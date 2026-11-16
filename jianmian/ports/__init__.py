"""端口（接口）定义。

具体模型、解析器、检索、预算设施都实现这些端口；domain 与 workflows 只依赖端口。
换模型 / 换 OCR / 换岗位库不需要改业务规则。
"""

from .model import ModelCapabilities, ModelProvider, ModelRequest, ModelResult, ModelUsage
from .parser import DocumentBlock, ParseResult, ParserAdapter
from .search import SearchProvider
from .budget import BudgetLease, BudgetStore
from .store import EventRecord, RunRecord, RunStore

__all__ = [
    "ModelCapabilities",
    "ModelProvider",
    "ModelRequest",
    "ModelResult",
    "ModelUsage",
    "DocumentBlock",
    "ParseResult",
    "ParserAdapter",
    "SearchProvider",
    "BudgetLease",
    "BudgetStore",
    "EventRecord",
    "RunRecord",
    "RunStore",
]
