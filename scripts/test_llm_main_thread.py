"""llm_main_thread 模块的离线自测（不打真实 LLM）。

覆盖：
1. parse_llm_lines 容错解析（代码栅栏 / 首尾杂散文本 / 截断）。
2. generate_main_threads：mock http_post 的成功路径 + 磁盘缓存命中路径。
3. generate_main_threads：未配置 API key 时安静回退。
4. build_member_overview(main_thread='llm')：无 key 时真实群全链路回退规则式。

用法: .venv/Scripts/python.exe scripts/test_llm_main_thread.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wechat_decrypt_tool.llm_main_thread import (  # noqa: E402
    build_prompt_members,
    generate_main_threads,
    load_llm_config,
    parse_llm_lines,
)

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def test_parse() -> None:
    print("[1] parse_llm_lines")
    wxids = ["wxid_a", "wxid_b"]
    raw = '```json\n{"lines": {"wxid_a": "最近在跟进口鞋团购和售后纠纷", "wxid_b": "主要分享基金行情，偶尔答疑", "wxid_c": "多余的"}}\n```'
    lines = parse_llm_lines(raw, wxids)
    check("代码栅栏可解析", lines.get("wxid_a") == "最近在跟进口鞋团购和售后纠纷", repr(lines))
    check("过滤未知 wxid", "wxid_c" not in lines)
    noisy = '好的，以下是结果：\n{"lines": {"wxid_a": "一句话", "wxid_b": "另一句"}}\n以上。'
    check("首尾杂散文本可解析", parse_llm_lines(noisy, wxids).get("wxid_b") == "另一句")
    check("非 JSON 返回空", parse_llm_lines("完全不是 json", wxids) == {})
    long_line = "长" * 100
    parsed = parse_llm_lines(json.dumps({"lines": {"wxid_a": long_line}}), wxids)
    check("超长截断到 60 字", len(parsed["wxid_a"]) == 60)


def _fake_members(n: int = 3) -> list[dict]:
    return [
        {
            "wxid": f"wxid_{i}",
            "displayName": f"成员{i}",
            "messageCount": 100 - i * 10,
            "share": 20.0 - i,
            "topics": [{"word": "团购", "count": 5}],
        }
        for i in range(n)
    ]


def test_generate() -> None:
    print("[2] generate_main_threads mock 路径")
    with tempfile.TemporaryDirectory() as td:
        cache_dir = Path(td)
        config = load_llm_config({"WECHAT_TOOL_LLM_API_KEY": "sk-test", "WECHAT_TOOL_LLM_MODEL": "test/model"})
        members = _fake_members()
        samples = {"wxid_0": ["这批货什么时候到", "价格再谈谈"], "wxid_1": ["今天行情不错"]}

        calls = []

        def fake_post(cfg, ctx):
            calls.append(ctx)
            return json.dumps({"lines": {c["wxid"]: f"主线{c['wxid']}" for c in ctx}}, ensure_ascii=False)

        r1 = generate_main_threads(
            members=members, samples_by_wxid=samples, config=config, cache_dir=cache_dir, http_post=fake_post
        )
        check("成功生成 3 条", len(r1["lines"]) == 3, repr(r1))
        check("标记非缓存", r1["cached"] is False)
        check("mock 被调一次", len(calls) == 1)
        ctx = calls[0]
        check("上下文带样本截断", ctx[0]["recent_samples"] == ["这批货什么时候到", "价格再谈谈"])

        r2 = generate_main_threads(
            members=members, samples_by_wxid=samples, config=config, cache_dir=cache_dir, http_post=fake_post
        )
        check("第二次命中缓存", r2["cached"] is True and len(r2["lines"]) == 3)
        check("缓存命中不再调 LLM", len(calls) == 1)

        r3 = generate_main_threads(
            members=members,
            samples_by_wxid={"wxid_0": ["新的话题内容出现了"]},
            config=config,
            cache_dir=cache_dir,
            http_post=fake_post,
        )
        check("输入变化换 key 重新调用", len(calls) == 2 and r3["cached"] is False)

        # 换一批样本避开缓存，确认异常被吞
        bad = generate_main_threads(
            members=_fake_members(2), samples_by_wxid={"wxid_0": ["x"]}, config=config, cache_dir=cache_dir,
            http_post=lambda cfg, ctx: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        check("异常安静回退", bad["lines"] == {} and "boom" in (bad["error"] or ""), repr(bad))


def test_unconfigured() -> None:
    print("[3] 未配置回退")
    with tempfile.TemporaryDirectory() as td:
        config = load_llm_config({"WECHAT_TOOL_LLM_API_KEY": ""})
        r = generate_main_threads(
            members=_fake_members(), samples_by_wxid={}, config=config, cache_dir=Path(td)
        )
        check("无 key 直接回退", r["lines"] == {} and "未配置" in (r["error"] or ""))


def test_full_path_rule_fallback() -> None:
    print("[4] build_member_overview(main_thread='llm') 无 key 全链路")
    import os

    os.environ.pop("WECHAT_TOOL_LLM_API_KEY", None)
    from wechat_decrypt_tool.routers.chat_member_overview import build_member_overview

    payload = build_member_overview(username="38687331998@chatroom", main_thread="llm")
    check("状态成功", payload.get("status") == "success")
    check("回退规则式", payload.get("mainThreadMode") == "rule")
    llm = payload.get("llm") or {}
    check("标记未配置", llm.get("configured") is False, repr(llm))
    members = payload.get("members") or []
    check("成员主线仍是规则式", all(m.get("mainThreadSource", "rule") == "rule" for m in members[:10]))


def test_prompt_shape() -> None:
    print("[5] prompt 上下文结构")
    ctx = build_prompt_members(_fake_members(2), {"wxid_0": ["  多条   空白\n合并  "]})
    check("样本清洗", ctx[0]["recent_samples"] == ["多条 空白 合并"], repr(ctx[0]["recent_samples"]))
    check("主题词透传", ctx[0]["topics"] == ["团购"])


if __name__ == "__main__":
    test_parse()
    test_generate()
    test_unconfigured()
    test_prompt_shape()
    test_full_path_rule_fallback()
    print(f"\n== {PASS} passed, {FAIL} failed ==")
    sys.exit(1 if FAIL else 0)
