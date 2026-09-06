"""群成员发言总览（build_member_overview）真实数据验证脚本。

用法（项目根目录、项目 venv）：
    .venv\\Scripts\\python.exe scripts\\validate_member_overview.py \
        --username 38687331998@chatroom [--username ...] [--topics 8]

对每个群做四件事：
1. 基准 SQL：直接查 chat_search_index.db 的 message_meta，与函数同口径聚合。
2. 调 build_member_overview：refresh=True 冷算计时，再调一次命中缓存计时。
3. 比对：成员数 / 总消息数 / 逐成员 messageCount，另跑一个近 30 天时间窗验证 range。
4. 采样导出：Top 10 成员的 topics / mainThread / 最近 3 条原文，供人工质检。

输出：
- 控制台摘要表
- output/validation/member_overview_YYYYMMDD_HHMM/ 下的 detail JSON 与 sample 报告
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import os

os.chdir(ROOT)  # 数据目录解析依赖 cwd（WECHAT_TOOL_DATA_DIR 未设时取 cwd）

from wechat_decrypt_tool.routers.chat_member_overview import (  # noqa: E402
    _collect_member_rows,
    _sample_texts,
    build_member_overview,
)

ACCOUNT = "wxid_k569o60da46922"
INDEX_DB = ROOT / "output" / "databases" / ACCOUNT / "chat_search_index.db"


def open_ro() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{INDEX_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def baseline(conn: sqlite3.Connection, username: str,
             start_ts: int | None = None, end_ts: int | None = None) -> dict[str, int]:
    """与 _collect_member_rows 同口径的基准聚合：sender -> count。"""
    rows = _collect_member_rows(
        conn,
        username=username,
        start_ts=start_ts,
        end_ts=end_ts,
        include_hidden=False,
        include_official=False,
    )
    return {str(r["sender_username"]): int(r["c"]) for r in rows}


def compare(base: dict[str, int], members: list[dict]) -> list[str]:
    """返回差异描述列表，空列表 = 完全一致。"""
    diffs: list[str] = []
    got = {str(m["wxid"]): int(m["messageCount"]) for m in members}
    if set(base) != set(got):
        only_base = sorted(set(base) - set(got))
        only_got = sorted(set(got) - set(base))
        if only_base:
            diffs.append(f"基准有而结果缺 {len(only_base)} 人: {only_base[:5]}")
        if only_got:
            diffs.append(f"结果有而基准缺 {len(only_got)} 人: {only_got[:5]}")
    for sender in sorted(set(base) & set(got)):
        if base[sender] != got[sender]:
            diffs.append(f"计数不一致 {sender}: 基准={base[sender]} 结果={got[sender]}")
    return diffs


def validate_group(username: str, topics: int, out_dir: Path) -> dict:
    conn = open_ro()
    report: dict = {"username": username}

    # ---- 全量窗口 ----
    base_all = baseline(conn, username)

    t0 = time.perf_counter()
    res_cold = build_member_overview(account=ACCOUNT, username=username,
                                     topics=topics, refresh=True)
    cold_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    res_cached = build_member_overview(account=ACCOUNT, username=username,
                                       topics=topics, refresh=False)
    cached_ms = (time.perf_counter() - t0) * 1000

    members = res_cold.get("members") or []
    diffs = compare(base_all, members)

    # ---- 近 30 天时间窗 ----
    end_ts = int(time.time())
    start_ts = end_ts - 30 * 86400
    base_win = baseline(conn, username, start_ts, end_ts)
    res_win = build_member_overview(account=ACCOUNT, username=username,
                                    start_time=start_ts, end_time=end_ts,
                                    topics=topics, refresh=True)
    win_diffs = compare(base_win, res_win.get("members") or [])
    rng = res_win.get("range") or {}
    range_ok = (rng.get("startTime") == start_ts and rng.get("endTime") == end_ts
                and rng.get("messageCount") == sum(base_win.values()))

    # ---- 采样：Top 10 成员 ----
    samples = []
    for m in members[:10]:
        texts, _fallback = _sample_texts(
            conn,
            username=username,
            sender=str(m["wxid"]),
            start_ts=None, end_ts=None,
            include_hidden=False, include_official=False,
            limit=3,
        )
        samples.append({
            "wxid": m["wxid"],
            "displayName": m.get("displayName"),
            "messageCount": m.get("messageCount"),
            "share": m.get("share"),
            "topics": [t.get("word") for t in (m.get("topics") or [])],
            "mainThread": m.get("mainThread"),
            "recentTexts": texts[:3],
        })

    report.update({
        "status": res_cold.get("status"),
        "cachedFlagSecondCall": bool(res_cached.get("cached")),
        "totals": res_cold.get("totals"),
        "baseline": {"members": len(base_all), "messages": sum(base_all.values())},
        "perf": {"coldMs": round(cold_ms, 1), "cachedMs": round(cached_ms, 1)},
        "countDiffs": diffs,
        "window": {
            "start": start_ts, "end": end_ts,
            "baselineMessages": sum(base_win.values()),
            "rangeOk": range_ok,
            "countDiffs": win_diffs,
        },
        "samples": samples,
    })

    safe = username.replace("@", "_")
    (out_dir / f"{safe}.detail.json").write_text(
        json.dumps({"cold": res_cold, "window": res_win}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (out_dir / f"{safe}.report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    conn.close()
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", action="append", required=True)
    ap.add_argument("--topics", type=int, default=8)
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = ROOT / "output" / "validation" / f"member_overview_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for username in args.username:
        print(f"[validate] {username} ...", flush=True)
        r = validate_group(username, args.topics, out_dir)
        ok = (not r["countDiffs"]) and r["window"]["rangeOk"] and not r["window"]["countDiffs"]
        rows.append([
            username, r["status"],
            f"{r['totals']['members']}/{r['baseline']['members']}",
            f"{r['totals']['messages']}/{r['baseline']['messages']}",
            f"{r['perf']['coldMs']:.0f}ms", f"{r['perf']['cachedMs']:.0f}ms",
            "PASS" if ok else "FAIL",
        ])

    print()
    header = ["group", "status", "members(res/base)", "messages(res/base)",
              "cold", "cached", "verdict"]
    widths = [max(len(str(x)) for x in [h] + [row[i] for row in rows]) for i, h in enumerate(header)]
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(header)))
    for row in rows:
        print("  ".join(str(v).ljust(widths[i]) for i, v in enumerate(row)))
    print(f"\n输出目录: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
