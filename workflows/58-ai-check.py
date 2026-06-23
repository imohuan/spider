"""58 厨具商家 AI 评估 workflow — 图片下载 → 压缩 → 合并宫格 → AI 视觉分析。

功能链路：
  1. 同步下载图片（hash 缓存去重，参考 ImageDownloader 两级去重）
  2. Pillow 压缩（限最大边长 + JPEG 质量）
  3. 多图合并宫格图（自适应行列数）
  4. base64 编码 → 调用 core.ai.AIClient 做视觉评估
  5. 返回结构化 JSON（评分/评级/维度详评/收购建议）

调用方式::

    from core.workflow_registry import enqueue_workflow

    enqueue_workflow("58-ai-check", {
        "image_urls": [
            "https://pic.58.com/xxx.jpg",
            "https://pic.58.com/yyy.jpg",
        ],
        "city": "北京",                           # 可选
        "extra_context": "期望转让费 5 万以内",    # 可选
    })
"""
from __future__ import annotations

import json
import re
from typing import Any

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

# ═══════════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一个厨具二手批发商，有多年商用厨房设备采购经验。
你需要浏览商家发布的转让/出售信息中的图片，评估哪些商家更有合作潜力。

请从以下维度逐一分析图片，并给出综合评估：

1. **铺面规模** — 店面/仓库面积大小，是否能容纳大量设备库存
2. **设备状况** — 设备新旧程度、品牌档次、摆放是否整齐有序
3. **经营品类** — 设备种类的丰富度和市场需求匹配度
4. **信息可靠性** — 图片是否真实拍摄（非网图/PS）、是否展示实际场景
5. **转让诚意** — 从图片中判断商家是否真正想出手（如店面清仓、搬迁迹象）

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

    :param params:
        - image_urls: list[str] — 图片 URL 列表（必填）
        - city: str — 城市（可选，附加到提示词）
        - extra_context: str — 额外上下文（可选，附加到提示词）
        - max_size: int — 压缩最大边长，默认 1024
        - quality: int — JPEG 质量 1-100，默认 75
        - max_cols: int — 宫格最大列数，默认 3
        - system_prompt: str — 覆盖默认系统提示词（可选）
    :param storage: Storage 实例（workflow_scheduler 注入）
    :param ref_id: 关联 ID（workflow_scheduler 注入）
    :returns: 结构化评估结果
    """
    image_urls: list[str] = params.get("image_urls", [])
    if not image_urls:
        return {"status": "error", "message": "缺少 image_urls 参数"}

    # 截断到最大处理数
    if len(image_urls) > _MAX_IMAGES:
        logger.warning(f"图片数 {len(image_urls)} 超过上限 {_MAX_IMAGES}，截断处理")
        image_urls = image_urls[:_MAX_IMAGES]

    city = params.get("city", "")
    extra_context = params.get("extra_context", "")
    max_size = int(params.get("max_size", DEFAULT_MAX_SIZE))
    quality = int(params.get("quality", DEFAULT_QUALITY))
    max_cols = int(params.get("max_cols", DEFAULT_MAX_COLS))
    system_prompt = params.get("system_prompt", SYSTEM_PROMPT)

    # ── 1. 下载图片 ──
    logger.info(f"开始评估 {len(image_urls)} 张图片")
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
    if city:
        user_text += f" 城市：{city}。"
    if extra_context:
        user_text += f" 补充信息：{extra_context}。"

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

    # ── 9. 组装最终结果 ──
    return {
        "status": "ok",
        "result": eval_result,
        "meta": {
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
# JSON 提取工具
# ═══════════════════════════════════════════════════════════════════

def _extract_json(text: str) -> dict[str, Any] | None:
    """从 AI 响应中提取 JSON 对象。

    处理三种常见情况：
      1. 纯 JSON 文本
      2. 被 markdown ```json ... ``` 包裹
      3. 文本中间包含 JSON 对象
    """
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 尝试提取第一个 { ... } JSON 对象
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None
