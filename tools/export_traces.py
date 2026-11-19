#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
码道 CodeArts Agent 使用痕迹导出器
================================================
把 ~/.codeartsdoer/codearts-data/opencode.db 里的会话记录，
导出成评审要的「md 格式 AI 交互过程文档」。

用法:
    python export_traces.py                  # 导出到 ./proof/ai-trace/
    python export_traces.py -o D:/xxx/proof  # 指定输出目录
    python export_traces.py --max-output 500 # 工具输出截断长度

特点:
    - 只读：先把 db 连 WAL 一起拷到临时目录再读，绝不碰原始数据
    - 保留原始毫秒时间戳，可交叉验证
    - 自动统计：会话数/消息数/工具调用数/改动文件数
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

DB_CANDIDATES = [
    Path.home() / ".codeartsdoer" / "codearts-data" / "opencode.db",
    Path(os.environ.get("APPDATA", "")) / "codearts-agent" / "opencode.db",
]


def find_db():
    for p in DB_CANDIDATES:
        if p.exists():
            return p
    return None


def snapshot_db(src: Path, workdir: Path) -> Path:
    """把 db 和 -wal/-shm 一起复制，保证读到最新已提交数据且不锁原库。"""
    dst = workdir / "trace_snapshot.db"
    shutil.copy2(src, dst)
    for suffix in ("-wal", "-shm"):
        side = Path(str(src) + suffix)
        if side.exists():
            shutil.copy2(side, Path(str(dst) + suffix))
    return dst


def ms_to_str(ms):
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ms)


def safe_json(raw, default=None):
    try:
        return json.loads(raw)
    except Exception:
        return default if default is not None else {}


def clip(text, limit):
    if text is None:
        return ""
    text = str(text)
    if limit and len(text) > limit:
        return text[:limit] + f"\n\n> …（已截断，原文 {len(text)} 字符）"
    return text


def render_tool_part(data, max_output):
    """把一次工具调用渲染成 md。兼容 opencode part 结构。"""
    tool = data.get("tool") or data.get("name") or "unknown"
    state = data.get("state") or {}
    status = state.get("status") or data.get("status") or ""
    inp = state.get("input") or data.get("input") or {}
    out = state.get("output") or data.get("output") or ""
    title = state.get("title") or ""

    lines = [f"**🔧 工具调用：`{tool}`**" + (f" — {title}" if title else "")]
    if status:
        lines.append(f"- 状态：{status}")

    if isinstance(inp, dict) and inp:
        # 只挑关键字段，避免刷屏
        keep = {}
        for k in ("command", "filePath", "path", "pattern", "description", "content", "query", "url"):
            if k in inp:
                keep[k] = inp[k]
        if not keep:
            keep = inp
        body = json.dumps(keep, ensure_ascii=False, indent=2)
        lines.append("\n参数：\n```json\n" + clip(body, 1200) + "\n```")

    if out:
        lines.append("\n输出：\n```text\n" + clip(out, max_output) + "\n```")

    return "\n".join(lines)


def render_part(data, max_output):
    ptype = data.get("type", "")
    if ptype == "text":
        return clip(data.get("text", ""), max_output)
    if ptype == "reasoning":
        txt = clip(data.get("text", ""), max_output)
        return "<details><summary>思考过程</summary>\n\n" + txt + "\n\n</details>"
    if ptype == "tool":
        return render_tool_part(data, max_output)
    if ptype == "patch":
        files = data.get("files") or []
        return "**📝 补丁**：" + ", ".join(f"`{f}`" for f in files) if files else ""
    if ptype == "file":
        return "**📎 附件**：" + str(data.get("filename") or data.get("url") or "")
    if ptype in ("step-start", "step-finish", "snapshot"):
        return ""
    raw = json.dumps(data, ensure_ascii=False)
    return "<details><summary>其他事件 (" + ptype + ")</summary>\n\n```json\n" + clip(raw, 800) + "\n```\n\n</details>"


def export(db_path: Path, out_dir: Path, max_output: int):
    with tempfile.TemporaryDirectory() as td:
        snap = snapshot_db(db_path, Path(td))
        con = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row

        sessions = con.execute(
            "SELECT id, title, directory, time_created, time_updated, parent_id "
            "FROM session ORDER BY time_created ASC"
        ).fetchall()

        if not sessions:
            print("⚠️  数据库里还没有任何会话记录。先在码道里聊上几句再来导。")
            return 1

        out_dir.mkdir(parents=True, exist_ok=True)
        index_rows = []
        total_msgs = total_tools = total_files = 0
        first_ts = None
        last_ts = None

        for i, s in enumerate(sessions, 1):
            sid = s["id"]
            msgs = con.execute(
                "SELECT id, data, time_created FROM message WHERE session_id=? "
                "ORDER BY time_created ASC, id ASC",
                (sid,),
            ).fetchall()

            if not msgs:
                continue

            slug = (s["title"] or f"session-{i}").strip()
            safe_slug = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in slug)[:40]
            fname = f"{i:02d}_{safe_slug}.md"
            body = []
            n_tools = 0
            t_start = s["time_created"]
            t_end = s["time_updated"] or s["time_created"]

            for m in msgs:
                mdata = safe_json(m["data"])
                role = mdata.get("role", "unknown")
                ts = ms_to_str(m["time_created"])
                parts = con.execute(
                    "SELECT data, time_created FROM part WHERE message_id=? "
                    "ORDER BY time_created ASC, id ASC",
                    (m["id"],),
                ).fetchall()

                chunks = []
                for p in parts:
                    pd = safe_json(p["data"])
                    if pd.get("type") == "tool":
                        n_tools += 1
                    rendered = render_part(pd, max_output)
                    if rendered:
                        chunks.append(rendered)

                if not chunks:
                    continue

                label = "👤 用户" if role == "user" else ("🤖 码道" if role == "assistant" else role)
                body.append(f"\n---\n\n### {label} · {ts}\n\n" + "\n\n".join(chunks))

            files = con.execute(
                "SELECT COUNT(DISTINCT file_path) FROM cag_file_diff WHERE session_id=?", (sid,)
            ).fetchone()[0]
            n_files = files or 0
            total_files += n_files
            total_msgs += len(msgs)
            total_tools += n_tools
            first_ts = min(first_ts, t_start) if first_ts else t_start
            last_ts = max(last_ts, t_end) if last_ts else t_end

            header = [
                f"# AI 交互过程记录 · {slug}",
                "",
                f"- 会话 ID：`{sid}`",
                f"- 工作目录：`{s['directory']}`",
                f"- 开始时间：{ms_to_str(t_start)}",
                f"- 结束时间：{ms_to_str(t_end)}",
                f"- 消息数：{len(msgs)}　工具调用：{n_tools}　涉及文件：{n_files}",
                "",
                "> 本文档由码道本地会话数据库（opencode.db）自动导出，时间戳为原始记录，未经修改。",
            ]
            (out_dir / fname).write_text("\n".join(header) + "\n" + "\n".join(body), encoding="utf-8")
            index_rows.append((fname, slug, ms_to_str(t_start), ms_to_str(t_end), len(msgs), n_tools, n_files))

        idx = [
            "# 码道使用痕迹总览",
            "",
            f"- 导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 数据来源：`{db_path}`",
            f"- 会话总数：{len(index_rows)}",
            f"- 消息总数：{total_msgs}",
            f"- 工具调用总数：{total_tools}",
            f"- 涉及文件总数：{total_files}",
            f"- 开发时间跨度：{ms_to_str(first_ts)} → {ms_to_str(last_ts)}",
            "",
            "| # | 会话 | 开始 | 结束 | 消息 | 工具调用 | 文件 |",
            "|---|---|---|---|---|---|---|",
        ]
        for i, (fn, slug, a, b, m, t, f) in enumerate(index_rows, 1):
            idx.append(f"| {i} | [{slug}]({fn}) | {a} | {b} | {m} | {t} | {f} |")
        idx += ["", "> 每个会话的文件内含逐条 Prompt 原文、工具调用参数与输出，时间戳均来自本地数据库原始记录。"]
        (out_dir / "00_总览.md").write_text("\n".join(idx), encoding="utf-8")

        con.close()

    print(f"✅ 已导出 {len(index_rows)} 个会话 → {out_dir}")
    print(f"   消息 {total_msgs} 条 / 工具调用 {total_tools} 次 / 涉及文件 {total_files} 个")
    print(f"   时间跨度 {ms_to_str(first_ts)} → {ms_to_str(last_ts)}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="导出码道 CodeArts Agent 会话痕迹为 Markdown")
    ap.add_argument("-o", "--out", default="proof/ai-trace", help="输出目录")
    ap.add_argument("--max-output", type=int, default=2000, help="单条工具输出截断长度")
    ap.add_argument("--db", default=None, help="手动指定 opencode.db 路径")
    args = ap.parse_args()

    db = Path(args.db) if args.db else find_db()
    if not db or not db.exists():
        print("❌ 没找到 opencode.db。用 --db 手动指定，或确认码道已至少启动过一次。")
        return 2
    return export(db, Path(args.out), args.max_output)


if __name__ == "__main__":
    sys.exit(main())
