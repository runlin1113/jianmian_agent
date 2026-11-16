"""DeepSeek（OpenAI 兼容）模型适配器。

安全与工程约束：
- Key 只从构造参数/服务端环境进入，绝不回传、绝不写日志；
- `model` 必须落在服务端白名单内，客户端传什么都会被覆盖；
- 45 秒单次超时；仅网络/429/部分 5xx 做带抖动的有限重试，参数与校验失败不重试；
- `finish_reason=length` 明确标记截断，不尝试应用半截数据；
- 超时可能已被上游计费 → 返回 `usagePending`，不承诺"重试恰好一次计费"。
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any

import httpx

from ..ports.model import (
    ModelCapabilities,
    ModelProvider,
    ModelRequest,
    ModelResult,
    ModelUsage,
    finish_reason_type,
)
from ..prompts.registry import prompt_version, render_prompt

#: 粗略价格（元 / 千 token），用于演示期成本可见；真实计费以供应商账单为准
PRICING_CNY_PER_1K: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.001, 0.002),
    "deepseek-reasoner": (0.004, 0.016),
}


class DeepSeekProvider(ModelProvider):
    name = "deepseek"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.deepseek.com",
        default_model: str = "deepseek-chat",
        allowed_models: tuple[str, ...] = ("deepseek-chat", "deepseek-reasoner"),
        timeout: float = 45.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("缺少服务端模型 Key")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._allowed = allowed_models
        self._timeout = timeout
        self._max_retries = max_retries
        self._transport = transport
        self.capabilities = ModelCapabilities(
            nativeToolCalling=True,
            jsonMode=True,
            jsonSchema=False,
            vision=False,
            streaming=True,
            maxContextTokens=65_536,
        )

    def _pick_model(self, requested: str | None) -> str:
        """服务端覆盖客户端传来的模型（第 8.3 节）。"""
        if requested and requested in self._allowed:
            return requested
        return self._default_model

    def _price(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        inp, out = PRICING_CNY_PER_1K.get(model, (0.002, 0.008))
        return round(prompt_tokens / 1000 * inp + completion_tokens / 1000 * out, 6)

    async def generate(self, request: ModelRequest) -> ModelResult:
        model = self._pick_model(request.model)
        system, user, version = render_prompt(request.task, request.inputs)
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": request.temperature,
            "max_tokens": min(request.maxTokens, 3000),
            "response_format": {"type": "json_object"},
            "stream": False,
        }

        last_error: str | None = None
        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout, transport=self._transport
                ) as client:
                    resp = await client.post(
                        f"{self._base_url}/chat/completions",
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                    )
                if resp.status_code in {429, 500, 502, 503, 504}:
                    last_error = f"upstream_status_{resp.status_code}"
                    if attempt < self._max_retries:
                        await asyncio.sleep(0.4 * (2**attempt) + random.uniform(0, 0.3))
                        continue
                    return ModelResult(
                        ok=False,
                        finishReason="error",
                        error=last_error,
                        model=model,
                        provider=self.name,
                        promptVersion=version,
                    )
                if resp.status_code >= 400:
                    # 参数/权限问题不重试，也不把上游原文抛给用户
                    return ModelResult(
                        ok=False,
                        finishReason="error",
                        error=f"upstream_status_{resp.status_code}",
                        model=model,
                        provider=self.name,
                        promptVersion=version,
                    )

                body = resp.json()
                choice = (body.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                content = message.get("content") or ""
                finish = finish_reason_type(choice.get("finish_reason"))
                usage_raw = body.get("usage") or {}
                prompt_tokens = int(usage_raw.get("prompt_tokens") or 0)
                completion_tokens = int(usage_raw.get("completion_tokens") or 0)

                structured: dict[str, Any] | None = None
                if finish != "length" and content.strip():
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, dict):
                            structured = parsed
                    except json.JSONDecodeError:
                        structured = None

                return ModelResult(
                    ok=structured is not None,
                    structured=structured,
                    text=content,
                    usage=ModelUsage(
                        promptTokens=prompt_tokens,
                        completionTokens=completion_tokens,
                        totalTokens=int(usage_raw.get("total_tokens") or prompt_tokens + completion_tokens),
                        costCny=self._price(model, prompt_tokens, completion_tokens),
                    ),
                    finishReason=finish,
                    model=model,
                    provider=self.name,
                    promptVersion=version,
                    error=None if structured is not None else "invalid_json_or_truncated",
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = type(exc).__name__
                if attempt < self._max_retries:
                    await asyncio.sleep(0.4 * (2**attempt) + random.uniform(0, 0.3))
                    continue
                return ModelResult(
                    ok=False,
                    finishReason="error",
                    error=last_error,
                    model=model,
                    provider=self.name,
                    promptVersion=version,
                    usagePending=True,
                )
        return ModelResult(
            ok=False,
            finishReason="error",
            error=last_error or "unknown_error",
            model=model,
            provider=self.name,
            promptVersion=version,
        )
