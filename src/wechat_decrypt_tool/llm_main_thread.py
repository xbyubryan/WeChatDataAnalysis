"""LLM 生成"当前可见主线"（member overview v2）。

设计要点：
- 走 OpenAI 兼容协议（/chat/completions），默认 OpenRouter，可换任何兼容端点。
- 配置全部来自环境变量，不落盘、不进 git：
    WECHAT_TOOL_LLM_BASE_URL  默认 https://openrouter.ai/api/v1
    WECHAT_TOOL_LLM_API_KEY   必填（未配置时调用方回退规则式主线）
    WECHAT_TOOL_LLM_MODEL     默认 deepseek/deepseek-chat
    WECHAT_TOOL_LLM_TIMEOUT   默认 60 秒
    WECHAT_TOOL_LLM_MAX_MEMBERS 默认 20（每群最多为前 N 名成员生成）
- 每个群一次批量调用：把 Top N 成员的统计 + 最近发言样本打包进一个 prompt，
  要求模型按 wxid 返回 JSON，避免逐成员调用造成的成本与延迟爆炸。
- 结果按"输入内容 hash"做磁盘缓存：成员统计或样本变化会自动换 key，
  不会读到过期结论；缓存与规则式主线缓存相互独立。

隐私说明：开启后会把成员的"显示名 + 统计 + 最近若干条发言截断样本"
发送到配置的在线模型端点。这是用户显式 opt-in 的行为（main_thread=llm），
默认关闭（rule）。样本在发送前做长度截断，不发送原始 payload 全量。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "deepseek/deepseek-chat"
_DEFAULT_TIMEOUT = 60.0
_DEFAULT_MAX_MEMBERS = 20

_MAX_SAMPLES_PER_MEMBER = 8
_SAMPLE_CHARS = 60
_LINE_MAX_CHARS = 60

_CACHE_DIR_NAME = "member_overview_llm"
_CACHE_TTL_SECONDS = 24 * 3600


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    timeout: float
    max_members: int

    @property
    def enabled(self) -> bool:
        return bool(self.api_key.strip())


def load_llm_config(env: Optional[dict[str, str]] = None) -> LLMConfig:
    """从环境变量加载配置；测试时可注入 dict。"""

    src = env if env is not None else os.environ
    base_url = str(src.get("WECHAT_TOOL_LLM_BASE_URL") or _DEFAULT_BASE_URL).strip().rstrip("/")
    api_key = str(src.get("WECHAT_TOOL_LLM_API_KEY") or "").strip()
    model = str(src.get("WECHAT_TOOL_LLM_MODEL") or _DEFAULT_MODEL).strip()
    try:
        timeout = float(src.get("WECHAT_TOOL_LLM_TIMEOUT") or _DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT
    try:
        max_members = int(src.get("WECHAT_TOOL_LLM_MAX_MEMBERS") or _DEFAULT_MAX_MEMBERS)
    except (TypeError, ValueError):
        max_members = _DEFAULT_MAX_MEMBERS
    return LLMConfig(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=max(5.0, timeout),
        max_members=max(1, min(50, max_members)),
    )


# --------------------------------------------------------------------------- #
# Prompt 构建与解析
# --------------------------------------------------------------------------- #

_SYSTEM_PROMPT = (
    "你是微信群聊分析助手。输入是一个群里若干活跃成员的统计数据和最近发言样本，"
    "你的任务是为每个成员写一句“当前可见主线”：这个人最近在群里关心什么、"
    "在推动或跟进什么事、扮演什么角色（如组织者/提问者/分享者/潜水围观）。"
    "要求："
    "1. 每句不超过 40 个汉字，直接陈述，不要引号、不要编号、不要称呼“该成员”；"
    "2. 基于样本里有依据的内容，样本太少就围绕主题词概括，不要编造具体事件；"
    "3. 语气中性客观，像数据分析报告的备注栏；"
    "4. 严格输出 JSON：{\"lines\": {\"<wxid>\": \"<一句话>\"}}，覆盖输入中的每个 wxid，"
    "不要输出任何其他内容。"
)


def _truncate(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def build_prompt_members(
    members: list[dict[str, Any]],
    samples_by_wxid: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """组装发给模型的成员上下文（也是缓存 key 的一部分）。"""

    ctx: list[dict[str, Any]] = []
    for m in members:
        wxid = str(m.get("wxid") or "")
        topics = [
            str(t.get("word") or "")
            for t in (m.get("topics") or [])
            if isinstance(t, dict) and t.get("word")
        ][:5]
        samples = [
            _truncate(s, _SAMPLE_CHARS)
            for s in (samples_by_wxid.get(wxid) or [])
            if str(s or "").strip()
        ][:_MAX_SAMPLES_PER_MEMBER]
        ctx.append(
            {
                "wxid": wxid,
                "name": str(m.get("displayName") or wxid),
                "messages": int(m.get("messageCount") or 0),
                "share_pct": m.get("share"),
                "topics": topics,
                "recent_samples": samples,
            }
        )
    return ctx


def build_user_prompt(ctx: list[dict[str, Any]]) -> str:
    return (
        "以下是群成员数据（按发言量降序）。请为每个 wxid 写一句“当前可见主线”。\n\n"
        + json.dumps(ctx, ensure_ascii=False, indent=1)
    )


def parse_llm_lines(raw: str, wxids: list[str]) -> dict[str, str]:
    """容错解析模型输出。容忍 markdown 代码栅栏和首尾杂散文本。"""

    text = str(raw or "").strip()
    if not text:
        return {}
    # 去掉 ```json ... ``` 栅栏
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
        text = text.strip()
    # 截取第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    lines = obj.get("lines") if isinstance(obj, dict) else None
    if not isinstance(lines, dict):
        return {}
    out: dict[str, str] = {}
    wanted = set(wxids)
    for k, v in lines.items():
        key = str(k).strip()
        val = _truncate(str(v or "").strip(), _LINE_MAX_CHARS)
        if key in wanted and val:
            out[key] = val
    return out


# --------------------------------------------------------------------------- #
# 磁盘缓存
# --------------------------------------------------------------------------- #


def _cache_key(ctx: list[dict[str, Any]], model: str) -> str:
    blob = json.dumps({"model": model, "ctx": ctx}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _read_llm_cache(cache_dir: Path, key: str) -> Optional[dict[str, str]]:
    path = cache_dir / f"{key}.json"
    try:
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > _CACHE_TTL_SECONDS:
            return None
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("lines"), dict):
            return {str(k): str(v) for k, v in data["lines"].items() if str(v).strip()}
    except Exception:
        return None
    return None


def _write_llm_cache(cache_dir: Path, key: str, lines: dict[str, str]) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / f"{key}.json"
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump({"lines": lines, "writtenAt": int(time.time())}, fh, ensure_ascii=False)
        tmp.replace(path)
    except Exception as e:
        logger.warning("[llm-main-thread] write cache failed: %s", str(e))


# --------------------------------------------------------------------------- #
# 调用
# --------------------------------------------------------------------------- #


def _chat_completions(config: LLMConfig, ctx: list[dict[str, Any]]) -> str:
    """调用 OpenAI 兼容端点，返回 content 原文。抛异常由调用方兜底。"""

    import httpx  # 延迟导入：未配置 LLM 的环境不引入依赖成本

    url = f"{config.base_url}/chat/completions"
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(ctx)},
        ],
        "temperature": 0.3,
        "max_tokens": 2000,
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


def generate_main_threads(
    *,
    members: list[dict[str, Any]],
    samples_by_wxid: dict[str, list[str]],
    config: LLMConfig,
    cache_dir: Path,
    http_post: Optional[Any] = None,
) -> dict[str, Any]:
    """为成员生成 LLM 主线。

    返回 {"lines": {wxid: str}, "cached": bool, "model": str, "error": str|None}。
    任何失败都返回 error 且 lines 为空，由调用方回退规则式，绝不抛出。

    http_post 仅供测试注入（签名同 _chat_completions），正常调用传 None。
    """

    result: dict[str, Any] = {"lines": {}, "cached": False, "model": config.model, "error": None}

    if not config.enabled:
        result["error"] = "LLM 未配置（缺少 WECHAT_TOOL_LLM_API_KEY）"
        return result

    targets = [m for m in members if str(m.get("wxid") or "")][: config.max_members]
    if not targets:
        result["error"] = "没有可生成的成员"
        return result

    ctx = build_prompt_members(targets, samples_by_wxid)
    wxids = [c["wxid"] for c in ctx]
    key = _cache_key(ctx, config.model)

    cached = _read_llm_cache(cache_dir, key)
    if cached is not None:
        result["lines"] = {w: cached[w] for w in wxids if w in cached}
        result["cached"] = True
        return result

    caller = http_post or _chat_completions
    try:
        raw = caller(config, ctx)
        lines = parse_llm_lines(raw, wxids)
    except Exception as e:
        logger.warning("[llm-main-thread] request failed model=%s error=%s", config.model, str(e))
        result["error"] = f"LLM 调用失败：{str(e)[:200]}"
        return result

    if not lines:
        result["error"] = "LLM 返回内容无法解析"
        return result

    _write_llm_cache(cache_dir, key, lines)
    result["lines"] = lines
    return result
