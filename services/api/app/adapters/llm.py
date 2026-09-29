"""LLM 适配器：OpenAI 兼容协议统一封装（DeepSeek / 智谱 / Ollama / Mock）。

职责：
- 统一 chat / chat_json 两个入口；JSON 输出做围栏剥离与首个 JSON 对象抽取；
- 有界重试（超时/5xx/限流），不无限等待；
- 记录 usage 与 provider/model，供成本核算与运行留痕（规格 §14 成本要求）；
- MockLLM 提供确定性输出，用于无密钥开发与测试，execution_mode 必须为 mock。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from ..config import Settings


class LLMError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class UsageRecord:
    def __init__(self) -> None:
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.errors = 0
        self.retries = 0

    def add(self, usage: dict | None, error: bool = False, retry: bool = False) -> None:
        if error:
            self.errors += 1
        if retry:
            self.retries += 1
        if usage:
            self.calls += 1
            self.prompt_tokens += usage.get("prompt_tokens", 0) or 0
            self.completion_tokens += usage.get("completion_tokens", 0) or 0

    def summary(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "errors": self.errors,
            "retries": self.retries,
        }


class OpenAICompatLLM:
    def __init__(self, base_url: str, model: str, api_key: str, settings: Settings):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = settings.llm_timeout_s
        self.max_retries = settings.llm_max_retries
        self.temperature = settings.llm_temperature
        self.thinking = settings.llm_thinking
        self.usage = UsageRecord()

    def chat(self, messages: list[dict], *, temperature: float | None = None, max_tokens: int | None = None) -> str:
        if not self.base_url or not self.model:
            raise LLMError("LLM 未配置：请设置 ZANH_LLM_PROVIDER / ZANH_LLM_API_KEY", retryable=False)
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
        }
        if max_tokens:
            body["max_tokens"] = max_tokens
        if self.thinking:
            body["thinking"] = {"type": self.thinking}
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = httpx.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=self.timeout_s,
                )
                if resp.status_code >= 500 or resp.status_code == 429:
                    raise LLMError(f"LLM 服务暂不可用 ({resp.status_code})", retryable=True)
                if resp.status_code == 402:
                    raise LLMError("LLM 账户余额不足", retryable=False)
                if resp.status_code in (401, 403):
                    raise LLMError("LLM 鉴权失败", retryable=False)
                if resp.status_code >= 400:
                    raise LLMError(f"LLM 请求被拒 ({resp.status_code}): {resp.text[:200]}", retryable=False)
                data = resp.json()
                self.usage.add(data.get("usage"))
                return data["choices"][0]["message"]["content"] or ""
            except LLMError as exc:
                last_err = exc
                if not exc.retryable or attempt == self.max_retries:
                    self.usage.add(None, error=True)
                    raise
                self.usage.add(None, retry=True)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_err = exc
                if attempt == self.max_retries:
                    self.usage.add(None, error=True)
                    raise LLMError(f"LLM 网络失败: {exc}", retryable=True) from exc
                self.usage.add(None, retry=True)
            time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"LLM 调用失败: {last_err}", retryable=True)

    def chat_json(self, messages: list[dict], *, max_tokens: int | None = None) -> Any:
        text = self.chat(messages, max_tokens=max_tokens)
        return extract_json(text)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> Any:
    """从模型输出稳健抽取 JSON：优先整体解析，其次代码围栏，再次首个平衡对象。"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    if start >= 0:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise LLMError("模型输出不是合法 JSON", retryable=False)


class MockLLM:
    """确定性假模型：仅用于无密钥的开发联调与单测；调用方必须标记 mock 模式。"""

    def __init__(self, responder=None):
        self._responder = responder or (lambda messages: "[]")
        self.usage = UsageRecord()

    def chat(self, messages: list[dict], **_: Any) -> str:
        self.usage.calls += 1
        return self._responder(messages)

    def chat_json(self, messages: list[dict], **_: Any) -> Any:
        return extract_json(self.chat(messages))


def build_llm(settings: Settings):
    base, model, key = settings.resolved_llm()
    if settings.llm_provider == "mock":
        return MockLLM()
    return OpenAICompatLLM(base, model, key, settings)
