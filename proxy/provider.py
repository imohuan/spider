"""代理提供者模块 - 从外部代理 API 拉取代理 IP。

按设计文档 4.3，支持 ``juliang``（巨量HTTP）和 ``kuaidaili``（快代理）。

接口约定（``ProxyProvider`` 基类）::

    class ProxyProvider:
        def fetch(self, num: int, ttl: int) -> list[ProxyRecord]:
            ...

子类实现 ``_do_fetch``，返回原始 IP 数据。基类负责重试与异常隔离。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from core.logger import get_logger

logger = get_logger("proxy.provider")


@dataclass
class ProxyRecord:
    """代理 IP 记录。"""
    ip: str
    port: int
    protocol: str = "http"
    city: str | None = None
    expire_at: str | None = None  # ISO 字符串
    use_count: int = 0
    max_use: int = 3
    id: int | None = None  # 数据库主键（入库后填充）


class ProxyProvider:
    """代理提供者基类。子类实现 ``_do_fetch``。"""

    name: str = "base"

    def __init__(self, api_url: str, timeout: int = 10) -> None:
        self.api_url = api_url
        self.timeout = timeout

    def fetch(self, num: int = 10, ttl: int = 60) -> list[ProxyRecord]:
        """拉取 ``num`` 个 IP，有效期 ``ttl`` 秒。

        :return: ``ProxyRecord`` 列表，失败返回空列表
        """
        if not self.api_url:
            logger.warning(f"[{self.name}] api_url 为空，跳过拉取")
            return []
        try:
            raw = self._do_fetch(num, ttl)
            logger.info(f"[{self.name}] 拉取 {len(raw)} 个 IP")
            return raw
        except Exception as e:
            logger.error(f"[{self.name}] 拉取失败: {e}", exc_info=True)
            return []

    def _do_fetch(self, num: int, ttl: int) -> list[ProxyRecord]:
        """子类实现：调用 API 并解析为 ProxyRecord 列表。"""
        raise NotImplementedError


class JuliangProvider(ProxyProvider):
    """巨量HTTP 代理提供者。

    API 返回格式（文本，每行一个 ``ip:port``）::

        1.2.3.4:8080
        5.6.7.8:3128

    或 JSON::

        {"code": 0, "data": [{"ip": "1.2.3.4", "port": 8080}, ...]}
    """

    name = "juliang"

    def _do_fetch(self, num: int, ttl: int) -> list[ProxyRecord]:
        params = {"num": str(num), "tt": str(ttl), "format": "json"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(self.api_url, params=params)
            resp.raise_for_status()
            text = resp.text.strip()
        # 尝试 JSON 解析
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 回退到文本格式：每行 ip:port
            return self._parse_text(text)
        return self._parse_json(data)

    @staticmethod
    def _parse_text(text: str) -> list[ProxyRecord]:
        records: list[ProxyRecord] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            ip, _, port_str = line.partition(":")
            try:
                port = int(port_str)
            except ValueError:
                continue
            records.append(ProxyRecord(ip=ip, port=port))
        return records

    @staticmethod
    def _parse_json(data: Any) -> list[ProxyRecord]:
        records: list[ProxyRecord] = []
        # 兼容两种 JSON 结构：{data: [...]} 或直接 [...]
        items = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(items, list):
            return records
        for item in items:
            if not isinstance(item, dict):
                continue
            ip = item.get("ip") or item.get("proxy")
            port = item.get("port")
            if not ip or not port:
                continue
            try:
                port_int = int(port)
            except (TypeError, ValueError):
                continue
            records.append(ProxyRecord(
                ip=ip,
                port=port_int,
                protocol=item.get("protocol", "http"),
                city=item.get("city"),
            ))
        return records


class KuaidailiProvider(ProxyProvider):
    """快代理提供者。API 返回 JSON: ``{"code": 0, "data": {"proxy_list": [...]}}``。"""

    name = "kuaidaili"

    def _do_fetch(self, num: int, ttl: int) -> list[ProxyRecord]:
        params = {"order_id": "", "num": str(num), "format": "json"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(self.api_url, params=params)
            resp.raise_for_status()
            data = resp.json()
        items = (data.get("data") or {}).get("proxy_list", [])
        records: list[ProxyRecord] = []
        for item in items:
            ip = item.get("ip")
            port = item.get("port")
            if not ip or not port:
                continue
            try:
                port_int = int(port)
            except (TypeError, ValueError):
                continue
            records.append(ProxyRecord(
                ip=ip, port=port_int,
                protocol=item.get("protocol", "http"),
                city=item.get("city"),
            ))
        return records


def make_provider(config_api_url: str, provider_name: str = "juliang") -> ProxyProvider | None:
    """根据配置创建 provider 实例。

    :param config_api_url: API 提取 URL
    :param provider_name: ``juliang`` / ``kuaidaili``
    :return: provider 实例，``api_url`` 为空时返回 ``None``
    """
    if not config_api_url:
        return None
    name = (provider_name or "juliang").lower()
    if name == "kuaidaili":
        return KuaidailiProvider(config_api_url)
    return JuliangProvider(config_api_url)
