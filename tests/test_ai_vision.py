"""AI Vision API 功能测试。

用法（先启动 dev.py 或 main.py --serve）：::

    python tests/test_ai_vision.py
"""
from __future__ import annotations

import json
import sys
import requests


API = "http://localhost:5000/api/config/ai-vision"

IMAGE_ID = "0c7fc3ab6b6edd93300eafac28e88aed"

# 测试用例
TEST_CASES = [
    {
        "name": "单图 + 商品信息提取",
        "payload": {
            "messages": [
                {"role": "system", "content": "你是一个专业的58同城商品图片分析助手。"},
                {"role": "user", "content": [
                    {"type": "text", "text": "请分析这张图片，提取商品的关键信息。"},
                    {"type": "image_id", "image_id": IMAGE_ID},
                ]},
            ],
            "output_mode": {
                "tool_name": "extract_product",
                "tool_description": "从商品图片中提取关键信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "商品标题或名称"},
                        "price": {"type": "string", "description": "价格，含单位"},
                        "category": {"type": "string", "description": "商品分类"},
                        "description": {"type": "string", "description": "商品简要描述"},
                        "condition": {"type": "string", "description": "新旧程度"},
                    },
                    "required": ["title", "category", "description"],
                },
            },
        },
    },
    {
        "name": "纯文本消息（无图片）",
        "payload": {
            "messages": [
                {"role": "system", "content": "你是一个专业的58同城商品图片分析助手。"},
                {"role": "user", "content": [
                    {"type": "text", "text": "你认识58同城吗？简要回答。"},
                ]},
            ],
            "output_mode": {
                "tool_name": "answer",
                "tool_description": "回答问题",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "answer": {"type": "string", "description": "回答内容"},
                    },
                    "required": ["answer"],
                },
            },
        },
    },
]


def run_test(case: dict) -> bool:
    print(f"\n{'='*60}")
    print(f"测试: {case['name']}")
    print(f"{'='*60}")
    print(f"Payload: {json.dumps(case['payload'], ensure_ascii=False, indent=2)[:500]}...")

    try:
        resp = requests.post(API, json=case["payload"], timeout=130)
    except requests.ConnectionError:
        print("FAIL: 无法连接到后端 (localhost:5000)，请先启动 dev.py")
        return False
    except requests.Timeout:
        print("FAIL: 请求超时")
        return False

    data = resp.json()
    print(f"Status: {resp.status_code}")

    if resp.status_code != 200 and not data.get("ok"):
        print(f"ERROR: {data.get('error', 'unknown')}")
        return False

    print(f"OK: {data['ok']}")
    if data["ok"]:
        print(f"结果: {json.dumps(data.get('result'), ensure_ascii=False, indent=2)}")
        print(f"尝试次数: {data.get('attempts')}  耗时: {data.get('duration_ms')}ms")
        usage = data.get("usage", {})
        print(f"Token: prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')}")
    else:
        print(f"错误: {data.get('error')}")
        if data.get("raw_content"):
            print(f"模型原文: {data['raw_content'][:200]}")
        if data.get("raw_args"):
            print(f"原始参数: {data['raw_args'][:200]}")

    return data["ok"]


def main():
    ok = 0
    fail = 0
    for case in TEST_CASES:
        if run_test(case):
            ok += 1
        else:
            fail += 1

    print(f"\n{'='*60}")
    print(f"结果: {ok} 通过 / {fail} 失败 (共 {len(TEST_CASES)} 用例)")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
