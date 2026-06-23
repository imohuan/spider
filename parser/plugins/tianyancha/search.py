"""天眼查搜索页解析器。

从 ``https://www.tianyancha.com/nsearch?key=xxx`` 页面提取 ``__NEXT_DATA__``
JSON 中的 ``companyList``，返回公司搜索结果的标准化数据。

核心流程：
    1. 从 HTML 中提取 ``<script id="__NEXT_DATA__" type="application/json">``
    2. 递归遍历 JSON 树找到第一个 ``companyList`` 列表
    3. 返回标准化公司数据行

天眼查搜索页是 SSR (Next.js) 页面，无需浏览器渲染，优选 HTTP 模式。
"""

from __future__ import annotations

import json
from typing import Any

from parser.base import BaseParser


def _find_company_list(data: Any) -> list[dict] | None:
    """递归查找 JSON 树中的第一个 ``companyList`` 列表。"""
    if isinstance(data, dict):
        if "companyList" in data and isinstance(data["companyList"], list):
            return data["companyList"]
        for v in data.values():
            result = _find_company_list(v)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _find_company_list(item)
            if result is not None:
                return result
    return None


def _safe_str(value: Any) -> str | None:
    """安全转换为字符串，None / 空串返回 None。"""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _merge_phones(company: dict) -> str | None:
    """合并 phoneList + phoneNum，去重后返回 JSON 数组字符串。

    phoneList 是字符串列表；phoneNum 是单个字符串。
    phoneInfoList（若存在）逐项提取电话号码。
    去重保留原始顺序，过滤空值。
    """
    seen: set[str] = set()
    result: list[str] = []

    def _add(v):
        s = str(v).strip()
        if s and s not in seen:
            seen.add(s)
            result.append(s)

    # phoneNum（单值）
    if company.get("phoneNum"):
        _add(company["phoneNum"])

    # phoneList（列表）
    for phone in (company.get("phoneList") or []):
        _add(phone)

    # phoneInfoList（对象数组，取 phone_num 字段）
    for info in (company.get("phoneInfoList") or []):
        if isinstance(info, dict):
            if info.get("phone_num"):
                _add(info["phone_num"])
            if info.get("phoneNum"):
                _add(info["phoneNum"])

    return json.dumps(result, ensure_ascii=False) if result else None


def _safe_int(value: Any) -> int | None:
    """安全转换为 int。"""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class TianyanchaSearchParser(BaseParser):
    """天眼查搜索结果页解析器。

    匹配 URL: ``https://www.tianyancha.com/nsearch?key=...``
    数据源: ``<script id="__NEXT_DATA__" type="application/json">`` (Next.js SSR)
    """

    url_pattern = r"tianyancha\.com/nsearch"
    preferred_fetch_mode = "browser"
    requires_browser = False

    table_name = "tianyancha_search"
    table_schema = """
        CREATE TABLE tianyancha_search (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id         BIGINT,
            name               TEXT,
            alias              TEXT,
            legal_person_name  TEXT,
            legal_person_id    TEXT,
            estiblish_time     TEXT,
            reg_capital        TEXT,
            reg_status         TEXT,
            score              TEXT,
            credit_code        TEXT,
            reg_number         TEXT,
            org_number         TEXT,
            reg_location       TEXT,
            reg_institute      TEXT,
            business_scope     TEXT,
            base               TEXT,
            province           TEXT,
            city               TEXT,
            district           TEXT,
            category_lv1       TEXT,
            category_lv2       TEXT,
            category_lv3       TEXT,
            category_lv4       TEXT,
            org_type           TEXT,
            phone              TEXT,
            tax_code           TEXT,
            company_type       INTEGER,
            is_branch          INTEGER,
            self_risk_count    INTEGER,
            related_risk_count INTEGER,
            history_risk_count INTEGER,
            search_url         TEXT,
            raw_json           TEXT,
            crawled_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """

    def parse(self, page, url: str) -> list[dict]:
        html = self._get_html(page)
        if not html:
            return []

        next_data = self._extract_next_data(html)
        if next_data is None:
            return []

        companies = _find_company_list(next_data)
        if not companies:
            return []

        rows = []
        for company in companies:
            row = self._normalize_company(company, url)
            rows.append(row)

        return rows

    # ---- 内部方法 ----

    # 标记字符串，用于查找 __NEXT_DATA__ 脚本标签
    _NEXT_DATA_MARKER = 'id="__NEXT_DATA__"'
    _SCRIPT_CLOSE = "</script>"

    @classmethod
    def _extract_next_data(cls, html: str) -> dict | None:
        """从 HTML 中提取 __NEXT_DATA__ JSON（字符串定位，避免大 JSON 正则匹配）。"""
        idx = html.find(cls._NEXT_DATA_MARKER)
        if idx == -1:
            return None

        # 回退到最近的 <script
        start = html.rfind("<script", 0, idx)
        if start == -1:
            return None

        # 跳过 <script ...>
        gt = html.find(">", start) + 1
        if gt <= start:
            return None

        # 找到对应的 </script>
        end = html.find(cls._SCRIPT_CLOSE, gt)
        if end == -1:
            return None

        json_text = html[gt:end].strip()
        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _normalize_company(company: dict, search_url: str) -> dict:
        """将 company 对象标准化为数据库行。"""
        return {
            "company_id":         _safe_int(company.get("id")),
            "name":               _safe_str(company.get("name")),
            "alias":              _safe_str(company.get("alias")),
            "legal_person_name":  _safe_str(company.get("legalPersonName")),
            "legal_person_id":    _safe_str(company.get("legalPersonId")),
            "estiblish_time":     _safe_str(company.get("estiblishTime")),
            "reg_capital":        _safe_str(company.get("regCapital")),
            "reg_status":         _safe_str(company.get("regStatus")),
            "score":              _safe_str(company.get("score")),
            "credit_code":        _safe_str(company.get("creditCode")),
            "reg_number":         _safe_str(company.get("regNumber")),
            "org_number":         _safe_str(company.get("orgNumber")),
            "reg_location":       _safe_str(company.get("regLocation")),
            "reg_institute":      _safe_str(company.get("registerInstitute")),
            "business_scope":     _safe_str(company.get("businessScope")),
            "base":               _safe_str(company.get("base")),
            "province":           _safe_str(company.get("provinceName")),
            "city":               _safe_str(company.get("cityName")),
            "district":           _safe_str(company.get("districtName")),
            "category_lv1":       _safe_str(company.get("categoryNameLv1")),
            "category_lv2":       _safe_str(company.get("categoryNameLv2")),
            "category_lv3":       _safe_str(company.get("categoryNameLv3")),
            "category_lv4":       _safe_str(company.get("categoryNameLv4")),
            "org_type":           _safe_str(company.get("orgType")),
            "phone":              _merge_phones(company),
            "tax_code":           _safe_str(company.get("taxCode")),
            "company_type":       _safe_int(company.get("companyType")),
            "is_branch":          _safe_int(company.get("isBranch")),
            "self_risk_count":    _safe_int(company.get("selfRiskCount")),
            "related_risk_count": _safe_int(company.get("relatedRiskCount")),
            "history_risk_count": _safe_int(company.get("historyRiskCount")),
            "search_url":         search_url,
            "raw_json":           json.dumps(company, ensure_ascii=False),
        }

    @staticmethod
    def _get_html(page) -> str:
        """从 page 对象提取 HTML 字符串。

        兼容 Playwright Page 对象和纯字符串（HTTP 模式）。
        """
        if isinstance(page, str):
            return page
        try:
            content = page.content()
            return content if isinstance(content, str) else ""
        except Exception:
            return ""
