"""模型端口（M14）。

统一的结构化结果 + 用量 + 结束原因 + 可重试错误；能力表单独标记，
因为"OpenAI 兼容消息格式"不代表工具调用/JSON Schema/视觉都兼容。
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

FinishReason = Literal["stop", "length", "tool_calls", "content_filter", "error"]


class ModelCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nativeToolCalling: bool = False
    jsonMode: bool = False
    jsonSchema: bool = False
    vision: bool = False
    streaming: bool = False
    maxContextTokens: int = 32_768


class ModelUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    promptTokens: int = 0
    completionTokens: int = 0
    totalTokens: int = 0
    #: 单位：人民币元；按供应商实际价格与计费单位计算，价格配置带生效日期
    costCny: float = 0.0


class ModelRequest(BaseModel):
    """一次结构化生成请求。

    `task` 是提示词注册表的键（例如 `rewrite_field`），两个适配器用同一套语义：
    mock 适配器按规则生成，DeepSeek 适配器渲染版本化提示词后调用真实模型。
    """

    model_config = ConfigDict(extra="forbid")

    task: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    schemaName: str = ""
    temperature: float = Field(default=0.2, ge=0.0, le=1.5)
    maxTokens: int = 1200
    #: 只允许落在服务端白名单内的模型；客户端传来的值会被覆盖
    model: str | None = None


class ModelResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    structured: dict[str, Any] | None = None
    text: str = ""
    usage: ModelUsage = Field(default_factory=ModelUsage)
    finishReason: FinishReason = "stop"
    model: str = ""
    provider: str = ""
    promptVersion: str = ""
    #: 网络超时可能已被上游计费 → 标记"用量待结算"
    usagePending: bool = False
    error: str | None = None

    @property
    def truncated(self) -> bool:
        return self.finishReason == "length"


class ModelError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@runtime_checkable
class ModelProvider(Protocol):
    name: str
    capabilities: ModelCapabilities

    async def generate(self, request: ModelRequest) -> ModelResult: ...


def estimate_tokens(text: str) -> int:
    """粗略估算：中文按 1 字 ≈ 1 token，英文按 4 字符 ≈ 1 token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return cjk + max(1, other // 4)


_FINISH_MAP: dict[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "tool_calls",
    "content_filter": "content_filter",
}


def finish_reason_type(raw: str | None) -> FinishReason:
    return _FINISH_MAP.get((raw or "").strip(), "error" if raw else "stop")
