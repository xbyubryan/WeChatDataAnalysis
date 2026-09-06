"""LLM 生成"群聊总结报告"（member overview v2 的整群版）。

与 llm_main_thread.py 的分工：
- llm_main_thread：给 Top N 成员各写一句话主线（表格行内）。
- 本模块：为整个群生成一张结构化总结卡片——
  headline（一句定调）/ overview（整体摘要）/ topics（主要话题分块）/
  timeline（时间线要点）/ highlights（高价值消息）。

复用 llm_main_thread 的配置加载与内容 hash 缓存思路；
配置环境变量完全相同（WECHAT_TOOL_LLM_* 或兼容的 DEEPSEEK_API_KEY 等）。

隐私说明：与 main_thread=llm 一样属于显式 opt-in，会把群内
"发送者显示名 + 截断后的消息样本"发送到配置的在线模型端点。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from .llm_main_thread import (
    LLMConfig,
    _cache_key,
    _truncate,
)

logger = logging.getLogger(__name__)

_MAX_MESSAGES = 240          # 送进 prompt 的消息条数上限
_MSG_CHARS = 100             # 单条消息截断长度
_CACHE_DIR_NAME = "group_summary_llm"
_CACHE_TTL_SECONDS = 24 * 3600

_SYSTEM_PROMPT = (
    "你是微信群聊分析助手。用户会给你一段群聊消息流水（含时间与发送者昵称）"
    "和基本统计，请你输出一份结构化的中文群聊总结报告。"
    "要求：客观、具体、有信息密度；不要泛泛而谈；不要编造消息中没有的事实；"
    "涉及金额/价格/数字时保留原文数值。"
)


def build_summary_user_prompt(
    *,
    messages: list[dict[str, Any]],
    group_name: str,
    member_count: int,
    message_total: int,
    top_members: list[dict[str, Any]],
) -> str:
    """组装 user prompt。messages 每项 {ts_label, sender, text}，按时间正序。"""

    lines: list[str] = []
    lines.append(f"群名：{group_name or '未知群聊'}")
    lines.append(f"统计：窗口内 {message_total} 条消息 / {member_count} 位发言成员")
    if top_members:
        tops = "、".join(
            f"{m.get('name', '?')}({m.get('count', 0)}条)" for m in top_members[:5]
        )
        lines.append(f"发言最多的成员：{tops}")
    lines.append("")
    lines.append("以下是消息流水（[时间] 发送者: 内容，已截断）：")
    for msg in messages:
        lines.append(f"[{msg.get('ts_label', '')}] {msg.get('sender', '?')}: {msg.get('text', '')}")
    lines.append("")
    lines.append(
        "请严格输出如下 JSON（不要输出任何其他文字、不要用 markdown 代码块包裹）：\n"
        "{\n"
        '  "headline": "一句话概括这段时间群里在发生什么（<=40字）",\n'
        '  "overview": "整体摘要，2~4句话，说清主线和氛围",\n'
        '  "topics": [{"title": "话题名", "summary": "该话题下大家在讨论什么，1~3句"}],\n'
        '  "timeline": [{"period": "时间段标签，如 06-28 晚上", "points": ["该时间段的1~3个要点"]}],\n'
        '  "highlights": [{"sender": "发送者", "text": "值得关注的原话（可截断）", "reason": "为什么值得关注（<=20字）"}]\n'
        "}\n"
        "topics 取 2~5 个；timeline 按时间顺序 2~6 段；highlights 取 3~8 条。"
    )
    return "\n".join(lines)


def parse_summary_json(raw: str) -> Optional[dict[str, Any]]:
    """容错解析 LLM 返回的总结 JSON。解析不出有效内容返回 None。"""

    text = str(raw or "").strip()
    if not text:
        return None
    # 去掉可能的 ```json 围栏
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    def _s(value: Any, limit: int = 400) -> str:
        return _truncate(str(value or "").strip(), limit)

    report: dict[str, Any] = {
        "headline": _s(data.get("headline"), 80),
        "overview": _s(data.get("overview"), 800),
        "topics": [],
        "timeline": [],
        "highlights": [],
    }

    topics = data.get("topics")
    if isinstance(topics, list):
        for item in topics[:6]:
            if not isinstance(item, dict):
                continue
            title = _s(item.get("title"), 40)
            summary = _s(item.get("summary"), 400)
            if title or summary:
                report["topics"].append({"title": title, "summary": summary})

    timeline = data.get("timeline")
    if isinstance(timeline, list):
        for item in timeline[:8]:
            if not isinstance(item, dict):
                continue
            period = _s(item.get("period"), 40)
            pts = item.get("points")
            points = [_s(p, 200) for p in pts if str(p or "").strip()] if isinstance(pts, list) else []
            if period or points:
                report["timeline"].append({"period": period, "points": points[:5]})

    highlights = data.get("highlights")
    if isinstance(highlights, list):
        for item in highlights[:10]:
            if not isinstance(item, dict):
                continue
            text_h = _s(item.get("text"), 200)
            if not text_h:
                continue
            report["highlights"].append(
                {
                    "sender": _s(item.get("sender"), 40),
                    "text": text_h,
                    "reason": _s(item.get("reason"), 40),
                }
            )

    if not report["headline"] and not report["overview"]:
        return None
    return report


def _read_summary_cache(cache_dir: Path, key: str) -> Optional[dict[str, Any]]:
    path = cache_dir / f"{key}.json"
    try:
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > _CACHE_TTL_SECONDS:
            return None
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("report"), dict):
            return data["report"]
    except Exception:
        return None
    return None


def _write_summary_cache(cache_dir: Path, key: str, report: dict[str, Any]) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / f"{key}.json"
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump({"report": report, "writtenAt": int(time.time())}, fh, ensure_ascii=False)
        tmp.replace(path)
    except Exception as e:
        logger.warning("[llm-group-summary] write cache failed: %s", str(e))


def _chat_completions_summary(config: LLMConfig, user_prompt: str) -> str:
    """调用 OpenAI 兼容端点，返回 content 原文。抛异常由调用方兜底。"""

    import httpx  # 延迟导入

    url = f"{config.base_url}/chat/completions"
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 4000,
    }
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=config.timeout) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("LLM 返回缺少 choices")
    content = (choices[0].get("message") or {}).get("content") or ""
    if not str(content).strip():
        raise RuntimeError("LLM 返回空内容")
    return str(content)


def generate_group_summary(
    *,
    messages: list[dict[str, Any]],
    group_name: str,
    member_count: int,
    message_total: int,
    top_members: list[dict[str, Any]],
    config: LLMConfig,
    cache_dir: Path,
    http_post: Optional[Any] = None,
) -> dict[str, Any]:
    """生成整群总结报告。

    返回 {"report": dict|None, "cached": bool, "model": str, "error": str|None}。
    任何失败都不抛出，report 为 None 且带 error，由调用方决定如何降级。

    http_post 仅供测试注入（签名同 _chat_completions_summary），正常调用传 None。
    """

    result: dict[str, Any] = {"report": None, "cached": False, "model": config.model, "error": None}

    if not config.enabled:
        result["error"] = "LLM 未配置（缺少 API key）"
        return result

    sample = [m for m in messages if str(m.get("text") or "").strip()][:_MAX_MESSAGES]
    if len(sample) < 5:
        result["error"] = "窗口内文本消息太少，无法生成总结"
        return result

    user_prompt = build_summary_user_prompt(
        messages=sample,
        group_name=group_name,
        member_count=member_count,
        message_total=message_total,
        top_members=top_members,
    )
    key = _cache_key([{"prompt": user_prompt}], config.model)

    cached = _read_summary_cache(cache_dir, key)
    if cached is not None:
        result["report"] = cached
        result["cached"] = True
        return result

    caller = http_post or _chat_completions_summary
    try:
        raw = caller(config, user_prompt)
        report = parse_summary_json(raw)
    except Exception as e:
        logger.warning("[llm-group-summary] request failed model=%s error=%s", config.model, str(e))
        result["error"] = f"LLM 调用失败：{str(e)[:200]}"
        return result

    if report is None:
        result["error"] = "LLM 返回内容无法解析"
        return result

    _write_summary_cache(cache_dir, key, report)
    result["report"] = report
    return result
