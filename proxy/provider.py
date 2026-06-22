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
    username: str | None = None
    password: str | None = None
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

    async def fetch_async(self, num: int = 10, ttl: int = 60) -> list[ProxyRecord]:
        """异步拉取 IP，用于 acquire_async() 中不阻塞事件循环。

        :return: ``ProxyRecord`` 列表，失败返回空列表
        """
        if not self.api_url:
            logger.warning(f"[{self.name}] api_url 为空，跳过拉取")
            return []
        try:
            raw = await self._do_fetch_async(num, ttl)
            logger.info(f"[{self.name}] 拉取 {len(raw)} 个 IP")
            return raw
        except Exception as e:
            logger.error(f"[{self.name}] 异步拉取失败: {e}", exc_info=True)
            return []

    async def _do_fetch_async(self, num: int, ttl: int) -> list[ProxyRecord]:
        """子类覆盖：异步调用 API。默认回退到同步 _do_fetch。"""
        return self._do_fetch(num, ttl)


class JuliangProvider(ProxyProvider):
    """巨量HTTP 代理提供者。

    文档: https://www.juliangip.com/help/sdk/http/

    请求参数: trade_no + sign（放在 base URL）、num、result_type(json/text)、
              可选: port、city、isp、pt(username+password分隔符)、
              split(分隔符)、sb、filter、dedup、no、mr(max_retries)

    JSON 响应格式::

        {"code": 200, "data": {
            "count": 1, "request_id": "...",
            "proxy_list": [["117.69.63.102", 43787, "username", "password"]]
        }}

    Text 响应格式（每行）::

        117.69.63.102:43787:username:password
    """

    name = "juliang"

    def _do_fetch(self, num: int, ttl: int) -> list[ProxyRecord]:
        params = {"num": str(num), "result_type": "json"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(self.api_url, params=params)
            resp.raise_for_status()
            return self._parse_response(resp.text.strip())

    async def _do_fetch_async(self, num: int, ttl: int) -> list[ProxyRecord]:
        params = {"num": str(num), "result_type": "json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(self.api_url, params=params)
            resp.raise_for_status()
            return self._parse_response(resp.text.strip())

    @staticmethod
    def _parse_response(text: str) -> list[ProxyRecord]:
        """解析 text 或 JSON 响应为 ProxyRecord 列表。"""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return JuliangProvider._parse_text(text)
        return JuliangProvider._parse_json(data)

    @staticmethod
    def _parse_json(data: Any) -> list[ProxyRecord]:
        """解析巨量 JSON 响应。

        结构: {"code":200, "data":{"proxy_list":[["ip",port,"user","pass"]]}}
        """
        records: list[ProxyRecord] = []
        if not isinstance(data, dict):
            return records
        
        # 检查 code（非 200 返回空）
        code = data.get("code", 200)
        if code != 200:
            logger.warning(f"[juliang] API 返回非 200 code: {code}")
            return records
        
        inner = data.get("data")
        if not isinstance(inner, dict):
            return records
        
        proxy_list = inner.get("proxy_list", [])
        if not isinstance(proxy_list, list):
            return records
        
        for item in proxy_list:
            if not isinstance(item, list) or len(item) < 2:
                continue
            ip = item[0]
            try:
                port = int(item[1])
            except (TypeError, ValueError):
                continue
            rec = ProxyRecord(ip=ip, port=port)
            if len(item) >= 3:
                rec.username = str(item[2]) if item[2] else None
            if len(item) >= 4:
                rec.password = str(item[3]) if item[3] else None
            records.append(rec)
        return records

    @staticmethod
    def _parse_text(text: str) -> list[ProxyRecord]:
        """解析巨量 text 格式: 每行 ip:port[:username[:password]]。"""
        records: list[ProxyRecord] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(":")
            if len(parts) < 2:
                continue
            ip = parts[0]
            try:
                port = int(parts[1])
            except ValueError:
                continue
            rec = ProxyRecord(ip=ip, port=port)
            if len(parts) >= 3 and parts[2]:
                rec.username = parts[2]
            if len(parts) >= 4 and parts[3]:
                rec.password = parts[3]
            records.append(rec)
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
