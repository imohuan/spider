"""58 厨具商家 AI 评估 workflow — 图片下载 → 压缩 → 合并宫格 → AI 视觉分析 → 高德周边搜索。

功能链路：
  1. 从 Parser row（shengyizr_detail）自动提取 photos + 商家字段
  2. 同步下载图片（hash 缓存去重，参考 ImageDownloader 两级去重）
  3. Pillow 压缩（限最大边长 + JPEG 质量）
  4. 多图合并宫格图（自适应行列数）
  5. base64 编码 → 调用 core.ai.AIClient 做视觉评估
  6. 返回结构化 JSON（评分/评级/维度详评/收购建议）
  7. 高德地图附近搜索：地址解析 → 周边餐饮/商场 POI，写入 nearby_pois

调用方式::

    # 方式1：Parser 自动入队（row 来自 shengyizr_detail 解析结果）
    self.storage.enqueue_workflow("58-ai-check", {
        "table": self.table_name,
        "url": url,
        "row": row,  # 含 photos / title / price / area / district 等
    })

    # 方式2：手动传入图片 URL
    enqueue_workflow("58-ai-check", {
        "image_urls": ["https://pic.58.com/xxx.jpg"],
        "extra_context": "期望转让费 5 万以内",
    })
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from core.ai import AIClient
from core.image_utils import (
    DEFAULT_MAX_SIZE,
    DEFAULT_QUALITY,
    DEFAULT_MAX_COLS,
    download_sync,
    compress,
    merge_grid,
    image_to_base64,
)
from core.logger import get_logger

logger = get_logger("workflow.58-ai-check")

# 高德周边搜索配置
_AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
_AMAP_AROUND_URL = "https://restapi.amap.com/v3/place/around"
_NEARBY_KEYWORDS = "餐饮|餐厅|厨具|商场|超市"
_NEARBY_RADIUS = 1000   # 搜索半径（米）
_NEARBY_LIMIT = 20      # 最多返回 POI 数量

# ═══════════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一个厨具二手批发商，有多年商用厨房设备采购经验。
你需要浏览商家发布的转让/出售信息中的图片，评估哪些商家更有合作潜力。

请从以下维度逐一分析图片，并结合商家提供的文本信息，给出综合评估：

1. **铺面规模** — 店面/仓库面积大小，是否能容纳大量设备库存
2. **设备状况** — 设备新旧程度、品牌档次、摆放是否整齐有序
3. **经营品类** — 设备种类的丰富度和市场需求匹配度
4. **信息可靠性** — 图片是否真实拍摄（非网图/PS）、是否展示实际场景
5. **转让诚意** — 从图片中判断商家是否真正想出手（如店面清仓、搬迁迹象）

请综合商家文本信息（租金、转让费、面积、位置、经营类型等）与图片内容，
判断该商家与厨具二手批发业务的匹配程度，以及是否有合作收购价值。

**最终输出必须是严格的 JSON 格式，不要包含 markdown 代码块标记：**
{
    "score": <1-10 整数>,
    "level": "<潜力极高 | 值得关注 | 一般 | 不推荐>",
    "summary": "<一句话总结>",
    "details": {
        "scale": "<铺面规模评价>",
        "equipment": "<设备状况评价>",
        "category": "<经营品类评价>",
        "reliability": "<信息可靠性评价>",
        "intent": "<转让诚意评价>"
    },
    "advice": "<具体建议：是否值得联系，预期收购价范围，注意事项>"
}"""

_MAX_IMAGES = 9  # 单次最多处理图片数（避免 token 爆炸）


# ═══════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════

async def execute(params: dict, storage=None, ref_id=None) -> dict:
    """工作流入口。

    支持两种入参模式：

    **Parser 模式** — 直接从 shengyizr_detail row 提取：
        - table: str — 数据表名
        - url: str — 原始 URL
        - row: dict — 解析后的数据行（含 photos / title / price / area 等）

    **手动模式** — 直接传图片 URL：
        - image_urls: list[str] — 图片 URL 列表
        - extra_context: str — 额外描述

    通用参数：
        - max_size: int — 压缩最大边长，默认 1024
        - quality: int — JPEG 质量 1-100，默认 75
        - max_cols: int — 宫格最大列数，默认 3
        - system_prompt: str — 覆盖默认系统提示词

    :param storage: Storage 实例（workflow_scheduler 注入）
    :param ref_id: 关联 ID（workflow_scheduler 注入）
    :returns: 结构化评估结果
    """
    # ── 0. 提取图片 URL（兼容两种模式）──
    row: dict | None = params.get("row")
    image_urls: list[str]
    listing_info: str = ""  # 商家文本信息（Parser 模式用）

    if row:
        # Parser 模式：从 row.photos 提取（| 分隔的 URL 列表）
        photos_raw = row.get("photos", "")
        image_urls = _parse_photos(photos_raw)
        listing_info = _build_listing_info(row, params.get("url", ""))
        if not image_urls:
            return {
                "status": "skipped",
                "message": "商家无图片",
                "url": params.get("url"),
                "title": row.get("title", ""),
            }
    else:
        # 手动模式
        image_urls = params.get("image_urls", [])
        if params.get("extra_context"):
            listing_info = f"补充信息：{params['extra_context']}"
        if not image_urls:
            return {"status": "error", "message": "缺少 image_urls 或 row 参数"}

    # 截断到最大处理数
    if len(image_urls) > _MAX_IMAGES:
        logger.warning(f"图片数 {len(image_urls)} 超过上限 {_MAX_IMAGES}，截断处理")
        image_urls = image_urls[:_MAX_IMAGES]

    max_size = int(params.get("max_size", DEFAULT_MAX_SIZE))
    quality = int(params.get("quality", DEFAULT_QUALITY))
    max_cols = int(params.get("max_cols", DEFAULT_MAX_COLS))
    system_prompt = params.get("system_prompt", SYSTEM_PROMPT)

    # ── 1. 下载图片 ──
    logger.info(f"开始评估 {len(image_urls)} 张图片"
                f"{' 标题: ' + row.get('title', '') if row else ''}")
    local_paths: list[str] = []
    failed_urls: list[str] = []
    for url in image_urls:
        path = download_sync(url)
        if path:
            local_paths.append(path)
        else:
            failed_urls.append(url)

    logger.info(f"下载完成: 成功 {len(local_paths)} / 失败 {len(failed_urls)}")

    if not local_paths:
        return {
            "status": "error",
            "message": "所有图片下载失败",
            "failed_urls": failed_urls,
        }

    # ── 2. 压缩图片 ──
    compressed: list[bytes] = []
    for path in local_paths:
        try:
            data = compress(path, max_size=max_size, quality=quality)
            compressed.append(data)
        except Exception as e:
            logger.warning(f"图片压缩失败 {path}: {e}")

    if not compressed:
        return {
            "status": "error",
            "message": "所有图片压缩失败",
            "failed_urls": failed_urls,
        }

    # ── 3. 合并宫格 ──
    try:
        merged = merge_grid(compressed, max_cols=max_cols, quality=quality)
    except Exception as e:
        logger.error(f"宫格合并失败: {e}")
        return {"status": "error", "message": f"图片合并失败: {e}"}

    # ── 4. base64 编码 ──
    image_uri = image_to_base64(merged)

    # ── 5. 构建提示词 ──
    user_text = "请评估以下商家图片。"
    if listing_info:
        user_text += f"\n\n{listing_info}"

    # ── 6. AI 调用 ──
    try:
        client = AIClient.from_config()
    except Exception as e:
        return {"status": "error", "message": f"AI 客户端初始化失败: {e}"}

    missing = client.check_configured()
    if missing:
        return {"status": "error", "message": f"AI 配置不完整: {'; '.join(missing)}"}

    logger.info(f"发送 AI vision 请求, 图片大小: {len(merged)} bytes, 模型: {client.model}")
    try:
        resp, duration_ms = await client.chat_completion_vision(
            system_prompt=system_prompt,
            user_text=user_text,
            images_base64=[image_uri],
            max_tokens=2048,
            temperature=0.3,
            timeout=120,
        )
    except Exception as e:
        logger.error(f"AI 请求异常: {e}")
        return {"status": "error", "message": f"AI 请求失败: {e}"}

    # ── 7. 解析响应 ──
    try:
        resp_data = resp.json()
    except Exception:
        return {
            "status": "error",
            "message": f"AI 响应无法解析: HTTP {resp.status_code}",
            "raw_text": resp.text[:500],
        }

    if not AIClient.response_ok(resp):
        return {
            "status": "error",
            "message": f"AI API 错误: {AIClient.error_message(resp, resp_data)}",
            "http_status": resp.status_code,
        }

    content = AIClient.extract_content(resp_data)
    if not content:
        return {
            "status": "error",
            "message": "AI 返回空内容",
            "usage": AIClient.extract_usage(resp_data),
        }

    # ── 8. 提取 JSON ──
    eval_result = _extract_json(content)
    if eval_result is None:
        return {
            "status": "partial",
            "message": "AI 返回无法解析为 JSON",
            "raw_content": content[:1000],
            "usage": AIClient.extract_usage(resp_data),
            "duration_ms": duration_ms,
        }

    # ── 9. 高德附近搜索 ──
    nearby_pois: list[dict] = []
    amap_error: str = ""
    if row and storage:
        try:
            from core.config_manager import ConfigManager
            cfg = ConfigManager(storage)
            amap_webapi_key = cfg.get("amap_webapi_key", "")
            if amap_webapi_key:
                nearby_pois, amap_error = await _search_nearby(row, amap_webapi_key)
            else:
                amap_error = "未配置 amap_webapi_key"
        except Exception as e:
            amap_error = f"周边搜索异常: {e}"
            logger.warning(amap_error)

    # ── 10. 组装最终结果 ──
    return {
        "status": "ok",
        "result": eval_result,
        "nearby_pois": nearby_pois,
        "nearby_error": amap_error if amap_error else None,
        "meta": {
            "info_id": params.get("info_id"),
            "url": params.get("url"),
            "title": row.get("title") if row else None,
            "total_images": len(image_urls),
            "downloaded": len(local_paths),
            "failed_urls": failed_urls,
            "merged_size": len(merged),
            "model": AIClient.extract_model(resp_data),
            "usage": AIClient.extract_usage(resp_data),
            "duration_ms": duration_ms,
        },
    }


# ═══════════════════════════════════════════════════════════════════
# 图片 URL 提取
# ═══════════════════════════════════════════════════════════════════

def _parse_photos(photos_raw: str) -> list[str]:
    """从 | 分隔的图片 URL 字符串提取有效 URL 列表。

    样例: ``"https://a.jpg|https://b.jpg|"`` → ``["https://a.jpg", "https://b.jpg"]``
    """
    if not photos_raw or not photos_raw.strip():
        return []
    return [
        url.strip() for url in photos_raw.split("|")
        if url.strip().startswith("http")
    ]


# ═══════════════════════════════════════════════════════════════════
# 商家信息 → 提示词拼接
# ═══════════════════════════════════════════════════════════════════

def _build_listing_info(row: dict, url: str = "") -> str:
    """将 shengyizr_detail row 拼成结构化的商家信息文本。

    样例输出::

        标题：餐饮设备齐全转租
        位置：北京 朝阳区 望京
        月租：8000 元/月
        转让费：面议
        面积：120 m2
        商铺类型：临街商铺
        经营状态：经营中
        经营类型：餐饮美食
        标签：临街, 可空转, 转让费便宜
        描述：店铺已经营5年，设备齐全，因回老家忍痛转让...
    """
    parts: list[str] = []

    # 标题
    title = row.get("title", "")
    if title:
        parts.append(f"标题：{title}")

    # 价格
    price = _fmt_price(row)
    if price:
        parts.append(f"月租：{price}")

    # 转让费
    transfer = row.get("transfer_fee", "").strip()
    if transfer:
        parts.append(f"转让费：{transfer}")

    # 位置
    district = row.get("district", "").strip()
    block = row.get("block", "").strip()
    address = row.get("address", "").strip()
    loc_parts = [p for p in [district, block, address] if p]
    if loc_parts:
        parts.append(f"位置：{' '.join(loc_parts)}")

    # 面积
    area = row.get("area", "").strip()
    if area:
        parts.append(f"面积：{area}")

    # 商铺类型 / 性质
    prop_type = row.get("property_type", "").strip()
    if prop_type:
        parts.append(f"商铺类型：{prop_type}")
    prop_nature = row.get("property_nature", "").strip()
    if prop_nature:
        parts.append(f"商铺性质：{prop_nature}")

    # 楼层
    floor = row.get("floor", "").strip()
    if floor:
        parts.append(f"楼层：{floor}")

    # 租期
    lease = row.get("remaining_lease", "").strip()
    if lease:
        parts.append(f"剩余租期：{lease}")

    # 经营状态 / 类型
    biz_status = row.get("biz_status", "").strip()
    if biz_status:
        parts.append(f"经营状态：{biz_status}")
    biz_type = row.get("biz_type", "").strip()
    if biz_type:
        parts.append(f"经营类型：{biz_type}")

    # 转让类型
    transfer_type = row.get("transfer_type", "").strip()
    if transfer_type:
        parts.append(f"转让类型：{transfer_type}")

    # 标签
    tags = row.get("tags", "").strip()
    if tags:
        parts.append(f"标签：{tags}")

    # 配套设施
    facilities = row.get("facilities", "").strip()
    if facilities:
        # 格式: "上水:有|下水:有|天然气:无" → "上水、下水、天然气"
        facility_names = [
            f.split(":")[0]
            for f in facilities.split("|") if f.strip()
        ]
        parts.append(f"配套设施：{'、'.join(facility_names)}")

    # 描述
    desc = row.get("description", "").strip()
    if desc:
        # 截断过长描述（留 500 字给 AI）
        if len(desc) > 500:
            desc = desc[:500] + "..."
        parts.append(f"描述：{desc}")

    # 链接
    if url:
        parts.append(f"链接：{url}")

    return "\n".join(parts)


def _fmt_price(row: dict) -> str:
    """格式化价格: 8000 元/月"""
    num = row.get("price_num", "").strip()
    unit = row.get("price_unit", "").strip()
    if not num:
        return ""
    return f"{num} {unit}" if unit else num


# ═══════════════════════════════════════════════════════════════════
# JSON 提取工具
# ═══════════════════════════════════════════════════════════════════

def _extract_json(text: str) -> dict[str, Any] | None:
    """从 AI 响应中提取 JSON 对象。

    处理三种常见情况：
      1. 纯 JSON 文本
      2. 被 markdown ```json ... ``` 包裹
      3. 文本中间包含 JSON 对象
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None


# ═══════════════════════════════════════════════════════════════════
# 高德地图附近搜索
# ═══════════════════════════════════════════════════════════════════

async def _geocode_address(address: str, key: str) -> tuple[float, float] | None:
    """调用高德 Geocode API，将地址字符串解析为经纬度坐标。

    :returns: (lng, lat) 或 None（解析失败）
    """
    if not address.strip():
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _AMAP_GEOCODE_URL,
                params={"address": address, "key": key, "output": "JSON"},
            )
            data = resp.json()
    except Exception as e:
        logger.warning(f"Geocode 请求失败: {e}")
        return None

    if data.get("status") != "1" or not data.get("geocodes"):
        logger.warning(f"Geocode 解析失败 address={address!r}: {data.get('info')}")
        return None

    loc_str: str = data["geocodes"][0].get("location", "")
    if not loc_str:
        return None
    try:
        lng_s, lat_s = loc_str.split(",")
        return float(lng_s), float(lat_s)
    except ValueError:
        return None


async def _search_nearby(row: dict, key: str) -> tuple[list[dict], str]:
    """用商家地址查询高德附近 POI。

    先从 row 拼出尽量完整的地址，Geocode 解析坐标，再调 /v3/place/around。

    :returns: (pois_list, error_msg)。
              pois_list 每项包含 id/name/type/address/tel/distance/rating/cost/location。
              error_msg 非空表示发生了可容忍错误（结果可为空列表）。
    """
    # 拼地址：优先用 district + block + address，如果都没有就跳过
    parts = [
        row.get("district", "").strip(),
        row.get("block", "").strip(),
        row.get("address", "").strip(),
    ]
    full_address = " ".join(p for p in parts if p)
    if not full_address:
        return [], "商家地址为空，跳过周边搜索"

    coords = await _geocode_address(full_address, key)
    if coords is None:
        return [], f"地址解析失败: {full_address!r}"

    lng, lat = coords
    location_str = f"{lng},{lat}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _AMAP_AROUND_URL,
                params={
                    "key": key,
                    "location": location_str,
                    "keywords": _NEARBY_KEYWORDS,
                    "radius": str(_NEARBY_RADIUS),
                    "sortrule": "distance",
                    "offset": str(_NEARBY_LIMIT),
                    "page": "1",
                    "extensions": "all",
                    "output": "JSON",
                },
            )
            data = resp.json()
    except Exception as e:
        return [], f"周边搜索请求失败: {e}"

    if data.get("status") != "1":
        return [], f"周边搜索 API 错误: {data.get('info')}"

    raw_pois: list[dict] = data.get("pois", []) or []
    pois: list[dict] = []
    for p in raw_pois:
        loc = p.get("location", "")
        loc_dict: dict = {}
        if loc and "," in loc:
            try:
                plng, plat = loc.split(",")
                loc_dict = {"lng": float(plng), "lat": float(plat)}
            except ValueError:
                pass
        biz = p.get("biz_ext") or {}
        pois.append({
            "id": p.get("id", ""),
            "name": p.get("name", ""),
            "type": p.get("type", ""),
            "address": p.get("address", ""),
            "tel": p.get("tel") or biz.get("tel", ""),
            "distance": int(p.get("distance") or 0),
            "rating": biz.get("rating", ""),
            "cost": biz.get("cost", ""),
            "location": loc_dict,
            "photos": [ph.get("url", "") for ph in (p.get("photos") or [])[:3]],
        })

    logger.info(
        f"周边搜索完成 addr={full_address!r} coords=({lng},{lat}) "
        f"找到 {len(pois)} 个 POI"
    )
    return pois, ""
