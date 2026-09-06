#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""llm_group_summary + group-summary 路由的离线自测。

覆盖：
1. parse_summary_json：正常 / 围栏 / 垃圾 / 缺字段 / 截断
2. generate_group_summary：mock 生成、缓存命中、异常回退、消息太少
3. build_group_summary 真实库：未配置 key 时的降级返回 + 采样管线

用法：.venv/Scripts/python.exe scripts/test_group_summary.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wechat_decrypt_tool.llm_group_summary import (  # noqa: E402
    build_summary_user_prompt,
    generate_group_summary,
    parse_summary_json,
)
from wechat_decrypt_tool.llm_main_thread import load_llm_config  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}  {detail}")


VALID_RAW = json.dumps(
    {
        "headline": "群里在讨论 AI 与港股",
        "overview": "这两天主要围绕 AI 产品和港股行情展开。",
        "topics": [
            {"title": "AI 产品", "summary": "讨论了 Gemini 与腾讯股价"},
            {"title": "港股", "summary": "关注恒生指数波动"},
        ],
        "timeline": [
            {"period": "06-28 晚上", "points": ["热议腾讯股价", "分享 AI 新闻"]},
        ],
        "highlights": [
            {"sender": "Carlos", "text": "腾讯 700 以下可以加仓", "reason": "操作建议"},
        ],
    },
    ensure_ascii=False,
)


def test_parse() -> None:
    print("== parse_summary_json ==")
    r = parse_summary_json(VALID_RAW)
    check("正常解析", r is not None and r["headline"] == "群里在讨论 AI 与港股")
    check("topics 规整", r is not None and len(r["topics"]) == 2 and r["topics"][0]["title"] == "AI 产品")
    check("timeline 规整", r is not None and r["timeline"][0]["points"] == ["热议腾讯股价", "分享 AI 新闻"])
    check("highlights 规整", r is not None and r["highlights"][0]["reason"] == "操作建议")

    r2 = parse_summary_json(f"```json\n{VALID_RAW}\n```")
    check("围栏剥离", r2 is not None and r2["headline"] == "群里在讨论 AI 与港股")

    check("垃圾返回 None", parse_summary_json("这不是 JSON") is None)
    check("空对象返回 None", parse_summary_json("{}") is None)
    check("非 dict 返回 None", parse_summary_json("[1,2,3]") is None)

    r3 = parse_summary_json(json.dumps({"overview": "只有摘要"}))
    check("仅 overview 也算有效", r3 is not None and r3["overview"] == "只有摘要")

    r4 = parse_summary_json(json.dumps({"headline": "h", "topics": [{"title": "x" * 100, "summary": "s"}]}))
    check("字段截断", r4 is not None and len(r4["topics"][0]["title"]) <= 41)  # 40 + 省略号


def _sample_messages(n: int = 10) -> list[dict]:
    return [
        {"ts_label": f"06-28 19:{50 + i}", "sender": f"成员{i % 3}", "text": f"第{i}条消息内容"}
        for i in range(n)
    ]


def test_generate() -> None:
    print("== generate_group_summary (mock) ==")
    config = load_llm_config({"WECHAT_TOOL_LLM_API_KEY": "sk-test", "WECHAT_TOOL_LLM_MODEL": "mock-model"})
    with tempfile.TemporaryDirectory() as td:
        cache_dir = Path(td)

        calls = {"n": 0}

        def fake_http(cfg, prompt):
            calls["n"] += 1
            return VALID_RAW

        r1 = generate_group_summary(
            messages=_sample_messages(),
            group_name="测试群",
            member_count=3,
            message_total=10,
            top_members=[{"name": "成员0", "count": 4}],
            config=config,
            cache_dir=cache_dir,
            http_post=fake_http,
        )
        check("mock 生成成功", r1["report"] is not None and r1["error"] is None)
        check("首次非缓存", r1["cached"] is False and calls["n"] == 1)

        r2 = generate_group_summary(
            messages=_sample_messages(),
            group_name="测试群",
            member_count=3,
            message_total=10,
            top_members=[{"name": "成员0", "count": 4}],
            config=config,
            cache_dir=cache_dir,
            http_post=fake_http,
        )
        check("二次命中缓存", r2["cached"] is True and calls["n"] == 1)
        check("缓存内容一致", r2["report"] == r1["report"])

        def boom(cfg, prompt):
            raise RuntimeError("network down")

        r3 = generate_group_summary(
            messages=_sample_messages(6) + [{"ts_label": "x", "sender": "y", "text": "不一样的内容避免缓存"}],
            group_name="测试群",
            member_count=3,
            message_total=7,
            top_members=[],
            config=config,
            cache_dir=cache_dir,
            http_post=boom,
        )
        check("异常回退不抛出", r3["report"] is None and "LLM 调用失败" in (r3["error"] or ""))

        r4 = generate_group_summary(
            messages=_sample_messages(3),
            group_name="测试群",
            member_count=3,
            message_total=3,
            top_members=[],
            config=config,
            cache_dir=cache_dir,
            http_post=fake_http,
        )
        check("消息太少被拒", r4["report"] is None and "太少" in (r4["error"] or ""))

        no_key = load_llm_config({})
        r5 = generate_group_summary(
            messages=_sample_messages(),
            group_name="测试群",
            member_count=3,
            message_total=10,
            top_members=[],
            config=no_key,
            cache_dir=cache_dir,
            http_post=fake_http,
        )
        check("未配置 key 直接回退", r5["report"] is None and r5["error"])

    prompt = build_summary_user_prompt(
        messages=_sample_messages(2),
        group_name="Prompt群",
        member_count=3,
        message_total=2,
        top_members=[{"name": "成员0", "count": 1}],
    )
    check("prompt 含群名", "Prompt群" in prompt)
    check("prompt 含消息", "第0条消息内容" in prompt and "[06-28 19:50]" in prompt)
    check("prompt 含 JSON 指令", '"headline"' in prompt and '"highlights"' in prompt)


def test_build_real() -> None:
    print("== build_group_summary 真实库（未配置 key 降级） ==")
    import os

    for k in ("WECHAT_TOOL_LLM_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(k, None)

    from wechat_decrypt_tool.routers.chat_member_overview import build_group_summary

    payload = build_group_summary(username="38687331998@chatroom", max_messages=60)
    check("status success", payload.get("status") == "success", str(payload.get("status")))
    check("群名解析", bool(payload.get("groupName")), str(payload.get("groupName")))
    check("topMembers 非空", len(payload.get("topMembers") or []) > 0)
    check("未配置时 report 为 None", payload.get("report") is None)
    check("llm.configured=False", payload.get("llm", {}).get("configured") is False)
    check("error 提示变量名", "API key" in str(payload.get("llm", {}).get("error") or ""))
    print(f"     群名: {payload.get('groupName')}  top1: {(payload.get('topMembers') or [{}])[0].get('displayName')}")


def main() -> int:
    test_parse()
    test_generate()
    test_build_real()
    print(f"\n== {PASS} passed, {FAIL} failed ==")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
