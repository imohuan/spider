"""AI 请求工具模块 — OpenAI-compatible API 客户端。

提供统一的 chat completion 调用封装，供 web/api 路由复用。
后续 images.py 等模块的 AI 逻辑也会在此扩展。
"""
from __future__ import annotations

import time
from typing import Any

import httpx


class AIClient:
    """OpenAI-compatible API 客户端。

    封装配置读取、验证和 chat completion 请求，消除各 API 路由中的重复代码。
    """

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    # ------------------------------------------------------------------
    # 工厂方法
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config_mgr=None):
        """从 ConfigManager 读取 AI 配置构建实例。

        不传 config_mgr 则自动创建默认实例。
        """
        if config_mgr is None:
            from core.config_manager import ConfigManager
            from core.storage import Storage

            config_mgr = ConfigManager(Storage())

        base_url = (config_mgr.get("ai_base_url") or "").strip().rstrip("/")
        api_key = (config_mgr.get("ai_api_key") or "").strip()
        model = (config_mgr.get("ai_model") or "").strip()
        return cls(base_url, api_key, model)

    # ------------------------------------------------------------------
    # 配置验证
    # ------------------------------------------------------------------

    @property
    def is_configured(self) -> bool:
        """快速检查三项配置是否都已填写。"""
        return bool(self.base_url and self.api_key and self.model)

    def check_configured(self) -> list[str]:
        """验证配置完整，返回缺失项列表（空列表 = 全部就绪）。"""
        missing: list[str] = []
        if not self.base_url:
            missing.append("AI Base URL 未配置")
        if not self.api_key:
            missing.append("AI API Key 未配置")
        if not self.model:
            missing.append("AI 模型未配置")
        return missing

    # ------------------------------------------------------------------
    # 核心请求
    # ------------------------------------------------------------------

    async def chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        timeout: float = 120,
    ) -> tuple[httpx.Response, int]:
        """发送 chat completion 请求。

        Returns:
            (httpx.Response, duration_ms)

        Raises:
            httpx.ConnectError, httpx.TimeoutException
        """
        t0 = time.perf_counter()

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

        duration_ms = int((time.perf_counter() - t0) * 1000)
        return resp, duration_ms

    # ------------------------------------------------------------------
    # 响应解析（静态方法，纯数据提取）
    # ------------------------------------------------------------------

    @staticmethod
    def response_ok(resp: httpx.Response) -> bool:
        """检查 HTTP 状态码是否成功。"""
        return resp.status_code == 200

    @staticmethod
    def extract_content(resp_data: dict[str, Any]) -> str:
        """从响应提取第一个 choice 的 message content。"""
        choice = (resp_data.get("choices") or [{}])[0]
        return choice.get("message", {}).get("content", "") or ""

    @staticmethod
    def extract_tool_calls(resp_data: dict[str, Any]) -> list[dict[str, Any]]:
        """从响应提取所有 tool_calls。"""
        choice = (resp_data.get("choices") or [{}])[0]
        return choice.get("message", {}).get("tool_calls") or []

    @staticmethod
    def extract_usage(resp_data: dict[str, Any]) -> dict[str, int]:
        """从响应提取 token 用量。"""
        usage = resp_data.get("usage", {})
        return {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        }

    @staticmethod
    def extract_model(resp_data: dict[str, Any]) -> str:
        """从响应提取实际使用的模型名。"""
        return resp_data.get("model", "")

    @staticmethod
    def error_message(resp: httpx.Response, resp_data: dict[str, Any] | None = None) -> str:
        """从错误响应提取可读的错误信息。"""
        if resp_data is None:
            try:
                resp_data = resp.json()
            except Exception:
                return resp.text[:200] or f"HTTP {resp.status_code}"
        return (
            resp_data.get("error", {}).get("message", "")
            or resp.text[:200]
            or f"HTTP {resp.status_code}"
        )
