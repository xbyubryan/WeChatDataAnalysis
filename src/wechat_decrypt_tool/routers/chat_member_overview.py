"""群聊成员发言总览（Member Speaking Overview）。

按会话维度聚合每个成员的发言量、主题词与主线摘要，供前端"成员总览"表格使用。

数据来源: 账号目录下的聊天搜索索引 ``chat_search_index.db``。

- ``message_meta``: 按 ``(username, sender_username)`` 聚合消息计数。
- ``message_fts.payload_json``: 取消息原文做主题词抽取。注意 ``message_meta.text``
  与 ``message_fts.text`` 都是字符级 token（单字、空格分隔、已小写），
  **不能直接做中文分词**，必须从 payload 里的 ``content`` 取原文。

索引未就绪时会自动触发构建（与 ``chat_search_index_senders`` 行为一致）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from ..account_identity import resolve_account_self_username
from ..chat_helpers import (
    _load_contact_rows,
    _load_group_nickname_map_from_contact_db,
    _pick_display_name,
    _resolve_account_dir,
)
from ..chat_search_index import (
    get_chat_search_index_db_path,
    get_chat_search_index_status,
    start_chat_search_index_build,
)
from ..logging_config import get_logger
from ..path_fix import PathFixRoute

logger = get_logger(__name__)

router = APIRouter(route_class=PathFixRoute)


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #

_CACHE_TTL_SECONDS = 300.0
_OVERVIEW_DIR_NAME = "_overview"
_OVERVIEW_SUBDIR = "member"

_DEFAULT_TOPIC_COUNT = 8
_MAX_TOPIC_COUNT = 30
_MAX_TOPIC_MEMBERS = 30  # 只为发言量前 N 名计算主题词，避免大群全量分词
_TOPIC_SAMPLE_LIMIT = 1200  # 每个成员抽样的最新消息数
_MAX_MEMBERS = 5000

_CACHE_LOCK = threading.Lock()


try:  # jieba 是可选依赖，缺失时退化到正则抽取
    import jieba

    try:
        jieba.setLogLevel(logging.ERROR)
    except Exception:  # pragma: no cover - jieba 版本差异
        pass
except Exception:  # pragma: no cover
    jieba = None


# --------------------------------------------------------------------------- #
# 文本处理
# --------------------------------------------------------------------------- #

_URL_RE = re.compile(r"(?i)\bhttps?://\S+")
_MD5_RE = re.compile(r"(?i)\b[0-9a-f]{32}\b")
_XML_RE = re.compile(r"<[^>]{1,200}>")
_CJK_SEQ_RE = re.compile(r"[\u4e00-\u9fff]{2,8}")
_EN_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+#.\-]{1,15}$")
_PUNCT_ONLY_RE = re.compile(r"^[\W_]+$", re.UNICODE)


# 精简版聊天停用词。与 wrapped/cards/card_05_keywords_wordcloud.py 的思路一致，
# 这里保留独立副本以避免分析模块与年度总结卡片耦合。
_STOPWORDS = {
    "的", "了", "是", "我", "你", "他", "她", "它", "们", "我们", "你们", "他们",
    "这", "那", "这个", "那个", "有", "在", "就", "不", "也", "都", "和", "跟",
    "吧", "吗", "呢", "啊", "哦", "嗯", "哈", "呀", "咯", "么", "啥", "怎么",
    "什么", "为什么", "可以", "还是", "但是", "然后", "所以", "因为", "如果",
    "一个", "一下", "这样", "那样", "没有", "不是", "知道", "觉得", "现在",
    "时候", "问题", "东西", "有点", "真的", "好像", "应该", "需要", "之后",
    "之前", "已经", "还有", "就是", "自己", "大家", "一下", "不会", "不能",
    "今天", "明天", "昨天", "晚上", "中午", "早上", "周末", "星期", "周一",
    "周二", "周三", "周四", "周五", "周六", "周日", "上午", "下午", "今年",
    "去年", "明年", "哪天", "几点", "收到", "好的", "好吧", "行吧", "哈哈",
    "the", "a", "an", "is", "are", "to", "of", "and", "or", "it", "this", "that",
    "for", "in", "on", "at", "be", "do", "not", "you", "i", "we", "he", "she",
    "https", "http", "com", "www",
}


def _clean_text(raw: str) -> str:
    """清洗单条消息文本，去掉 URL/表情标记/消息体 XML。"""

    t = str(raw or "").strip()
    if not t:
        return ""
    t = _URL_RE.sub(" ", t)
    t = _MD5_RE.sub(" ", t)
    # 微信表情与引用是 <msg>...</msg> / <emoji ...> 形式，对主题词无意义
    t = _XML_RE.sub(" ", t)
    # [微笑] 这类文本表情
    t = re.sub(r"\[[\u4e00-\u9fffA-Za-z0-9]{1,8}\]", " ", t)
    return t.strip()


def _tokenize(text: str) -> list[str]:
    """中文分词；jieba 不可用时退化为正则抽取。"""

    t = str(text or "")
    if not t:
        return []

    if jieba is not None:
        try:
            return [w for w in jieba.cut(t) if w]
        except Exception:
            pass

    # 退化路径：中文按 2-4 字滑窗太噪，直接用连续 CJK 串 + 英文词
    tokens: list[str] = []
    tokens.extend(_CJK_SEQ_RE.findall(t))
    tokens.extend(w for w in re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{1,15}", t))
    return tokens


def _is_valid_token(token: str) -> bool:
    w = str(token or "").strip()
    if not w:
        return False
    if w.lower() in _STOPWORDS:
        return False
    if len(w) < 2:
        return False
    if _PUNCT_ONLY_RE.match(w):
        return False
    if w.isdigit():
        return False
    if _CJK_SEQ_RE.fullmatch(w):
        return len(w) >= 2
    if _EN_WORD_RE.fullmatch(w):
        return True
    # 混合串（如 "ai模型"）保留，但要含 CJK 或字母
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z]", w))


def _extract_topics(texts: list[str], top_n: int) -> list[dict[str, Any]]:
    """从一批原文中抽取高频主题词。"""

    counter: Counter[str] = Counter()
    for raw in texts:
        cleaned = _clean_text(raw)
        if not cleaned:
            continue
        for w in _tokenize(cleaned):
            if _is_valid_token(w):
                counter[w] += 1

    if not counter:
        return []

    return [
        {"word": w, "count": int(c)}
        for w, c in counter.most_common(int(top_n))
    ]


# --------------------------------------------------------------------------- #
# 主线摘要（规则式；LLM 版本留到后续）
# --------------------------------------------------------------------------- #

_ACTIVE_LEVELS = (
    (30.0, "核心话事人"),
    (15.0, "活跃"),
    (5.0, "常规"),
    (0.0, "潜水"),
)


def _activity_level(share_pct: float) -> str:
    for threshold, label in _ACTIVE_LEVELS:
        if share_pct >= threshold:
            return label
    return "潜水"


def _build_main_thread(
    *,
    display_name: str,
    message_count: int,
    share_pct: float,
    topics: list[dict[str, Any]],
    last_time: int,
    is_self: bool,
) -> str:
    """规则式一句话主线。

    v1 不接 LLM：用"活跃档位 + 高频主题词 + 最近发言时间"拼一句可读的摘要，
    避免把聊天原文外发给任何在线模型。
    """

    level = _activity_level(share_pct)

    now_ts = int(time.time())
    days_idle = -1
    if last_time and last_time > 0:
        days_idle = max(0, (now_ts - int(last_time)) // 86400)

    parts: list[str] = []
    if is_self:
        parts.append("本人")
    parts.append(level)

    if topics:
        words = "、".join(str(t.get("word") or "") for t in topics[:3] if t.get("word"))
        if words:
            parts.append(f"近期主要围绕 {words}")

    parts.append(f"发言 {message_count} 条，占全群 {share_pct:.1f}%")

    if days_idle >= 0:
        if days_idle == 0:
            parts.append("今天有发言")
        elif days_idle <= 7:
            parts.append(f"{days_idle} 天前活跃")
        elif days_idle <= 30:
            parts.append(f"近 {days_idle} 天未发言")
        else:
            parts.append(f"已 {days_idle} 天未发言")

    return " · ".join(parts)


# --------------------------------------------------------------------------- #
# 缓存
# --------------------------------------------------------------------------- #


def _cache_dir(account_dir: Path) -> Path:
    d = account_dir / _OVERVIEW_DIR_NAME / _OVERVIEW_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_file(account_dir: Path, key: str) -> Path:
    return _cache_dir(account_dir) / f"{key}.json"


def _read_cache(account_dir: Path, key: str) -> Optional[dict[str, Any]]:
    path = _cache_file(account_dir, key)
    try:
        if not path.exists():
            return None
        age = time.time() - float(path.stat().st_mtime)
        if age > _CACHE_TTL_SECONDS:
            return None
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_cache(account_dir: Path, key: str, payload: dict[str, Any]) -> None:
    try:
        path = _cache_file(account_dir, key)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        tmp.replace(path)
    except Exception as e:  # 缓存失败不影响主流程
        logger.warning("[member-overview] write cache failed account=%s error=%s", account_dir.name, str(e))


# --------------------------------------------------------------------------- #
# 主逻辑
# --------------------------------------------------------------------------- #


def _payload_text(payload: Any) -> str:
    """从索引 payload_json 中取出可分析的原文。"""

    if not payload:
        return ""
    if isinstance(payload, dict):
        items = [
            str(payload.get("content") or ""),
            str(payload.get("quoteContent") or ""),
            str(payload.get("title") or ""),
            str(payload.get("locationPoiname") or ""),
            str(payload.get("locationLabel") or ""),
        ]
        return "\n".join([x for x in items if x.strip()])
    if isinstance(payload, str):
        try:
            obj = json.loads(payload)
        except Exception:
            return ""
        return _payload_text(obj)
    return ""


def _collect_member_rows(
    conn: sqlite3.Connection,
    *,
    username: str,
    start_ts: Optional[int],
    end_ts: Optional[int],
    include_hidden: bool,
    include_official: bool,
) -> list[sqlite3.Row]:
    where = ["username = ?", "sender_username <> ''"]
    params: list[Any] = [username]

    if not include_hidden:
        where.append("CAST(is_hidden AS INTEGER) = 0")
    if not include_official:
        where.append("CAST(is_official AS INTEGER) = 0")
    if start_ts is not None:
        where.append("CAST(create_time AS INTEGER) >= ?")
        params.append(int(start_ts))
    if end_ts is not None:
        where.append("CAST(create_time AS INTEGER) <= ?")
        params.append(int(end_ts))

    sql = (
        "SELECT sender_username, COUNT(*) AS c, "
        "MIN(CAST(create_time AS INTEGER)) AS first_time, "
        "MAX(CAST(create_time AS INTEGER)) AS last_time "
        "FROM message_meta "
        f"WHERE {' AND '.join(where)} "
        "GROUP BY sender_username "
        "ORDER BY c DESC, sender_username ASC "
        "LIMIT ?"
    )
    params.append(int(_MAX_MEMBERS))

    return list(conn.execute(sql, params).fetchall())


def _sample_texts(
    conn: sqlite3.Connection,
    *,
    username: str,
    sender: str,
    start_ts: Optional[int],
    end_ts: Optional[int],
    include_hidden: bool,
    include_official: bool,
    limit: int,
) -> tuple[list[str], str]:
    """取某成员最近 N 条消息的原文 + 顺带回一个显示名兜底。"""

    where = ["m.username = ?", "m.sender_username = ?"]
    params: list[Any] = [username, sender]

    if not include_hidden:
        where.append("CAST(m.is_hidden AS INTEGER) = 0")
    if not include_official:
        where.append("CAST(m.is_official AS INTEGER) = 0")
    if start_ts is not None:
        where.append("CAST(m.create_time AS INTEGER) >= ?")
        params.append(int(start_ts))
    if end_ts is not None:
        where.append("CAST(m.create_time AS INTEGER) <= ?")
        params.append(int(end_ts))

    sql = (
        "SELECT f.payload_json AS pj "
        "FROM message_meta m "
        "JOIN message_fts f ON f.rowid = m.rowid "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY CAST(m.create_time AS INTEGER) DESC "
        "LIMIT ?"
    )
    params.append(int(limit))

    texts: list[str] = []
    display_fallback = ""
    try:
        for r in conn.execute(sql, params):
            raw = r["pj"]
            if not raw:
                continue
            try:
                obj = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
            except Exception:
                continue
            if isinstance(obj, dict) and not display_fallback:
                candidate = str(obj.get("senderDisplayName") or "").strip()
                if candidate:
                    display_fallback = candidate
            text = _payload_text(obj)
            if text:
                texts.append(text)
    except sqlite3.Error as e:
        logger.warning("[member-overview] sample failed sender=%s error=%s", sender, str(e))

    return texts, display_fallback


def build_member_overview(
    *,
    account: Optional[str] = None,
    username: str = "",
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    topics: int = _DEFAULT_TOPIC_COUNT,
    include_hidden: bool = False,
    include_official: bool = False,
    refresh: bool = False,
) -> dict[str, Any]:
    """计算某个会话的成员发言总览。"""

    username = str(username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required.")

    if topics <= 0:
        topics = _DEFAULT_TOPIC_COUNT
    if topics > _MAX_TOPIC_COUNT:
        topics = _MAX_TOPIC_COUNT

    start_ts = int(start_time) if start_time is not None else None
    end_ts = int(end_time) if end_time is not None else None
    if start_ts is not None and start_ts < 0:
        start_ts = 0
    if end_ts is not None and end_ts < 0:
        end_ts = 0

    account_dir = _resolve_account_dir(account)
    contact_db_path = account_dir / "contact.db"

    index_status = get_chat_search_index_status(account_dir, source="decrypted")
    index = dict(index_status.get("index") or {})
    build = dict(index.get("build") or {})
    build_status = str(build.get("status") or "").strip()
    index_ready = bool(index.get("ready"))

    if (not index_ready) and build_status not in {"building", "error"}:
        start_chat_search_index_build(account_dir, rebuild=bool(index.get("exists")), source="decrypted")
        index_status = get_chat_search_index_status(account_dir, source="decrypted")
        index = dict(index_status.get("index") or {})
        build = dict(index.get("build") or {})
        build_status = str(build.get("status") or "").strip()
        index_ready = bool(index.get("ready"))

    base_payload: dict[str, Any] = {
        "account": account_dir.name,
        "username": username,
        "isGroup": username.endswith("@chatroom"),
        "index": index,
    }

    if build_status == "error":
        return {**base_payload, "status": "index_error", "members": [], "totals": {"members": 0, "messages": 0}}

    if build_status == "building" or not index_ready:
        return {**base_payload, "status": "index_building", "members": [], "totals": {"members": 0, "messages": 0}}

    cache_key = hashlib.sha1(
        "|".join(
            [
                username,
                str(start_ts),
                str(end_ts),
                str(topics),
                str(int(bool(include_hidden))),
                str(int(bool(include_official))),
            ]
        ).encode("utf-8")
    ).hexdigest()

    if not refresh:
        cached = _read_cache(account_dir, cache_key)
        if cached is not None:
            return {**cached, "status": "success", "cached": True}

    with _CACHE_LOCK:
        # 双检：并发请求可能已经在锁内算完并写缓存
        if not refresh:
            cached = _read_cache(account_dir, cache_key)
            if cached is not None:
                return {**cached, "status": "success", "cached": True}

        index_db_path = get_chat_search_index_db_path(account_dir)
        conn = sqlite3.connect(str(index_db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = _collect_member_rows(
                conn,
                username=username,
                start_ts=start_ts,
                end_ts=end_ts,
                include_hidden=include_hidden,
                include_official=include_official,
            )
        except sqlite3.Error as e:
            conn.close()
            logger.error(
                "[member-overview] aggregate failed account=%s username=%s error=%s",
                account_dir.name,
                username,
                str(e),
            )
            raise HTTPException(status_code=500, detail="Failed to aggregate member stats.") from e

        if not rows:
            conn.close()
            payload = {
                **base_payload,
                "status": "success",
                "cached": False,
                "range": {"startTime": start_ts, "endTime": end_ts, "messageCount": 0},
                "members": [],
                "totals": {"members": 0, "messages": 0},
            }
            _write_cache(account_dir, cache_key, payload)
            return payload

        total_messages = sum(int(r["c"] or 0) for r in rows)
        senders = [str(r["sender_username"] or "").strip() for r in rows]
        senders = [s for s in senders if s]

        contact_rows = _load_contact_rows(contact_db_path, senders)
        group_nicknames: dict[str, str] = {}
        if username.endswith("@chatroom"):
            try:
                group_nicknames = _load_group_nickname_map_from_contact_db(
                    contact_db_path, username, senders
                )
            except Exception:
                group_nicknames = {}

        try:
            self_username = str(resolve_account_self_username(account_dir) or "").strip()
        except Exception:
            self_username = ""

        members: list[dict[str, Any]] = []
        for idx, r in enumerate(rows):
            sender = str(r["sender_username"] or "").strip()
            if not sender:
                continue

            count = int(r["c"] or 0)
            first_time = int(r["first_time"] or 0)
            last_time = int(r["last_time"] or 0)
            share_pct = (float(count) / float(total_messages) * 100.0) if total_messages else 0.0

            # 显示名优先级：群昵称 > 备注/昵称/别名 > payload 里的 senderDisplayName > wxid
            display_name = ""
            if sender in group_nicknames and str(group_nicknames.get(sender) or "").strip():
                display_name = str(group_nicknames.get(sender) or "").strip()
            else:
                crow = contact_rows.get(sender)
                if crow is not None:
                    display_name = _pick_display_name(crow, "")

            member_topics: list[dict[str, Any]] = []
            # 只为发言量靠前的成员做分词，控制大群耗时
            if idx < _MAX_TOPIC_MEMBERS:
                texts, fallback_name = _sample_texts(
                    conn,
                    username=username,
                    sender=sender,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    include_hidden=include_hidden,
                    include_official=include_official,
                    limit=_TOPIC_SAMPLE_LIMIT,
                )
                if not display_name and fallback_name:
                    display_name = fallback_name
                member_topics = _extract_topics(texts, topics)

            if not display_name:
                display_name = sender

            members.append(
                {
                    "wxid": sender,
                    "displayName": display_name,
                    "isSelf": bool(self_username and sender == self_username),
                    "messageCount": count,
                    "share": round(share_pct, 2),
                    "firstTime": first_time,
                    "lastTime": last_time,
                    "topics": member_topics,
                    "mainThread": _build_main_thread(
                        display_name=display_name,
                        message_count=count,
                        share_pct=share_pct,
                        topics=member_topics,
                        last_time=last_time,
                        is_self=bool(self_username and sender == self_username),
                    ),
                }
            )

        conn.close()

        payload = {
            **base_payload,
            "status": "success",
            "cached": False,
            "range": {"startTime": start_ts, "endTime": end_ts, "messageCount": int(total_messages)},
            "members": members,
            "totals": {"members": len(members), "messages": int(total_messages)},
            "freshness": {
                "kind": "snapshot",
                "source": "decrypted_index",
                "latestRealtimeIncluded": False,
                "message": "统计基于解密快照索引；先执行 /api/chat/realtime/sync 再带 refresh=true 可纳入最新消息。",
            },
        }
        _write_cache(account_dir, cache_key, payload)
        return payload


# --------------------------------------------------------------------------- #
# 路由
# --------------------------------------------------------------------------- #


@router.get("/api/chat/member-overview", summary="群聊成员发言总览（成员 / wxid / 索引条目 / 主题命中 / 主线）")
def get_member_overview(
    username: str = Query(..., description="会话 username（群聊为 xxx@chatroom）。"),
    account: Optional[str] = Query(None, description="解密后的账号目录名。默认取第一个可用账号。"),
    start_time: Optional[int] = Query(None, description="起始时间（Unix 秒）。"),
    end_time: Optional[int] = Query(None, description="结束时间（Unix 秒）。"),
    topics: int = Query(_DEFAULT_TOPIC_COUNT, description="每个成员返回的主题词数量。", ge=0, le=_MAX_TOPIC_COUNT),
    include_hidden: bool = Query(False, description="包含隐藏会话的消息。"),
    include_official: bool = Query(False, description="包含公众号会话的消息。"),
    refresh: bool = Query(False, description="忽略缓存强制重算。"),
):
    return build_member_overview(
        account=account,
        username=username,
        start_time=start_time,
        end_time=end_time,
        topics=topics,
        include_hidden=include_hidden,
        include_official=include_official,
        refresh=refresh,
    )
