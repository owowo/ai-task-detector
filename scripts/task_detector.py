#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai-task-detector :: task_detector.py
====================================
Token-minimal AI task completion detector.

Design goal: do ALL the heavy lifting (diffing task snapshots, generating
brief intros) in plain Python so the LLM never has to re-read full task
history or re-summarize anything. The agent only feeds in a small JSON
snapshot and reads back a compact *delta* (only what changed).

State files (under --state-dir, default ./.ai_task_detector):
  state.json    -> last seen snapshot (id -> {status, subject, description})
  briefs.json   -> id -> generated brief intro (cached, never recomputed)
  progress.md   -> human-readable live report (regenerated from briefs)

Commands:
  init                  create state dir + empty state
  detect                read snapshot (--snapshot FILE or stdin), diff,
                        update state, refresh briefs + progress.md,
                        print the compact delta (only changes)
  report                print current progress.md path / contents
  reset                 wipe state (keeps nothing)

Snapshot JSON schema:
  {
    "tasks": [
      {"id": "1", "subject": "...", "description": "...",
       "status": "completed", "owner": "..."},
      ...
    ]
  }
Status values: pending | in_progress | completed | deleted
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_STATE_DIR = ".ai_task_detector"
STATE_FILE = "state.json"
BRIEFS_FILE = "briefs.json"
PROGRESS_FILE = "progress.md"

STATUS_ORDER = ["completed", "in_progress", "pending", "deleted"]

# Sentences starting with these markers are treated as the "result" of a task
RESULT_MARKERS = (
    "结果", "完成", "产出", "交付", "输出", "总结", "结论", "修复", "实现",
    "result", "done", "deliverable", "output", "fixed", "implemented",
)

SENT_SPLIT = "。！？!?\n；;"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def ensure_dir(state_dir: str) -> None:
    os.makedirs(state_dir, exist_ok=True)


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_state(state_dir: str) -> dict:
    p = os.path.join(state_dir, STATE_FILE)
    if os.path.exists(p):
        try:
            return _read_json(p)
        except Exception:
            return {}
    return {}


def load_briefs(state_dir: str) -> dict:
    p = os.path.join(state_dir, BRIEFS_FILE)
    if os.path.exists(p):
        try:
            return _read_json(p)
        except Exception:
            return {}
    return {}


def compress(text: str, max_sentences: int = 2, max_chars: int = 90) -> str:
    """Extract a short summary from free text: first 1-2 sentences, plus any
    result-marked sentence, each truncated. Pure string ops, no model."""
    if not text:
        return ""
    text = " ".join(text.split())  # collapse whitespace
    # naive sentence split
    parts = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in SENT_SPLIT:
            parts.append(buf.strip())
            buf = ""
    if buf.strip():
        parts.append(buf.strip())
    parts = [p for p in parts if p]

    chosen = []
    for p in parts[:max_sentences]:
        chosen.append(p[:max_chars])
    # ensure a result-marked sentence is included even if beyond the first ones
    for p in parts[max_sentences:]:
        low = p.lower()
        if any(low.startswith(m) for m in RESULT_MARKERS):
            chosen.append(p[:max_chars])
            break
    if not chosen:
        return text[:max_chars].rstrip("。！？!?.") + "。"
    # strip trailing punctuation from each piece, then join with a single "。"
    cleaned = [c.rstrip("。！？!?.") for c in chosen]
    return "。".join(cleaned) + "。"


def make_brief(task: dict) -> str:
    subject = (task.get("subject") or "").strip() or "(未命名任务)"
    desc = (task.get("description") or "").strip()
    status = (task.get("status") or "").strip()
    summary = compress(desc)
    lines = [f"### {subject}"]
    if summary:
        lines.append(summary)
    lines.append(f"- 状态：`{status}` · 更新：{now_iso()}")
    return "\n".join(lines)


def progress_path(state_dir: str) -> str:
    return os.path.join(state_dir, PROGRESS_FILE)


def regenerate_progress(state_dir: str, snapshot_tasks: list, briefs: dict) -> None:
    """Rebuild progress.md from cached briefs + current snapshot.
    Only completed / in_progress tasks get a detailed brief; pending are listed."""
    counts = {"completed": 0, "in_progress": 0, "pending": 0, "deleted": 0}
    for t in snapshot_tasks:
        s = (t.get("status") or "pending")
        counts[s] = counts.get(s, 0) + 1
    total = len(snapshot_tasks)

    by_status = {k: [] for k in STATUS_ORDER}
    for t in snapshot_tasks:
        s = (t.get("status") or "pending")
        if s not in by_status:
            by_status[s] = by_status.get(s, [])
        by_status[s].append(t)

    out = []
    out.append("# AI 任务进度（自动检测）")
    out.append("")
    out.append(f"> 由 `ai-task-detector` 实时生成 · 最后更新：{now_iso()}")
    out.append("")
    out.append(
        f"**总览**：已完成 {counts['completed']} / 共 {total}"
        f"（进行中 {counts['in_progress']}，待处理 {counts['pending']}）"
    )
    out.append("")

    section_titles = {
        "completed": "## ✅ 已完成",
        "in_progress": "## 🔄 进行中",
        "pending": "## ⏳ 待处理",
        "deleted": "## 🗑 已移除",
    }

    for st in STATUS_ORDER:
        tasks = by_status.get(st, [])
        if not tasks:
            continue
        out.append(section_titles[st])
        out.append("")
        if st == "pending":
            for t in tasks:
                subj = (t.get("subject") or "").strip() or "(未命名任务)"
                tid = t.get("id", "?")
                out.append(f"- #{tid} {subj}")
            out.append("")
        else:
            for t in tasks:
                tid = t.get("id", "?")
                brief = briefs.get(str(tid)) or briefs.get(tid)
                if not brief:
                    brief = make_brief(t)
                    briefs[str(tid)] = brief
                out.append(brief)
                out.append("")

    with open(progress_path(state_dir), "w", encoding="utf-8") as f:
        f.write("\n".join(out).rstrip() + "\n")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_init(args) -> int:
    ensure_dir(args.state_dir)
    if not os.path.exists(os.path.join(args.state_dir, STATE_FILE)):
        _write_json(os.path.join(args.state_dir, STATE_FILE), {})
    if not os.path.exists(os.path.join(args.state_dir, BRIEFS_FILE)):
        _write_json(os.path.join(args.state_dir, BRIEFS_FILE), {})
    print(f"initialized state dir: {args.state_dir}")
    return 0


def cmd_detect(args) -> int:
    # 1. Read snapshot
    if args.snapshot:
        with open(args.snapshot, "r", encoding="utf-8") as f:
            snap = json.load(f)
    else:
        snap = json.load(sys.stdin)

    tasks = snap.get("tasks", [])
    current = {str(t.get("id")): t for t in tasks if "id" in t}

    state_dir = args.state_dir
    ensure_dir(state_dir)
    prev = load_state(state_dir)
    briefs = load_briefs(state_dir)

    # 2. Diff
    delta_lines = []
    next_state = {}
    for tid, t in current.items():
        cur_status = (t.get("status") or "pending")
        subj = (t.get("subject") or "").strip() or "(未命名任务)"
        prev_t = prev.get(tid)
        if prev_t is None:
            delta_lines.append(f"🆕 NEW   #{tid} {subj}")
        elif prev_t.get("status") != cur_status:
            arrow = "✅ DONE " if cur_status == "completed" else "🔄 PROG "
            delta_lines.append(f"{arrow} #{tid} {subj}  ({prev_t.get('status','?')}→{cur_status})")
        # Generate / refresh brief.
        # - On transition to completed: always (re)generate so the finished
        #   intro reflects the final status. This is the key event, and the
        #   generation is template-based (no model call), so cost is trivial.
        # - While in_progress: generate once and cache (avoid recompute).
        prev_entry = prev.get(tid)
        prev_status = prev_entry.get("status") if isinstance(prev_entry, dict) else None
        if cur_status == "completed":
            if tid not in briefs or prev_status != "completed":
                briefs[tid] = make_brief(t)
        elif cur_status == "in_progress" and tid not in briefs:
            briefs[tid] = make_brief(t)
        next_state[tid] = {
            "status": cur_status,
            "subject": subj,
            "description": (t.get("description") or "").strip(),
        }

    # removed tasks
    for tid, pt in prev.items():
        if tid not in current:
            delta_lines.append(f"🗑 RM    #{tid} {(pt.get('subject') or '').strip()}")

    # 3. Persist
    _write_json(os.path.join(state_dir, STATE_FILE), next_state)
    _write_json(os.path.join(state_dir, BRIEFS_FILE), briefs)

    # 4. Regenerate report (unless skipped)
    if not args.no_report:
        regenerate_progress(state_dir, tasks, briefs)

    # 5. Emit compact delta (only changes). Empty == nothing changed.
    if delta_lines and not args.quiet:
        print("\n".join(delta_lines))
    # else: print nothing -> minimal tokens. Exit code still 0.
    return 0


def cmd_report(args) -> int:
    p = progress_path(args.state_dir)
    if not os.path.exists(p):
        print(f"no progress report yet at {p} (run `detect` first)", file=sys.stderr)
        return 1
    if args.cat:
        with open(p, "r", encoding="utf-8") as f:
            sys.stdout.write(f.read())
    else:
        print(p)
    return 0


def cmd_reset(args) -> int:
    import shutil
    if os.path.isdir(args.state_dir):
        shutil.rmtree(args.state_dir)
    print(f"reset: removed {args.state_dir}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="task_detector.py",
        description="Token-minimal AI task completion detector.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("init", help="create state dir + empty state")
    pi.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    pi.set_defaults(func=cmd_init)

    pd = sub.add_parser("detect", help="diff snapshot, refresh briefs + progress.md")
    pd.add_argument("--snapshot", help="path to snapshot JSON (else read stdin)")
    pd.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    pd.add_argument("--no-report", action="store_true", help="skip progress.md regen")
    pd.add_argument("--quiet", action="store_true", help="suppress delta output")
    pd.set_defaults(func=cmd_detect)

    pr = sub.add_parser("report", help="show progress report path / contents")
    pr.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    pr.add_argument("--cat", action="store_true", help="print report contents")
    pr.set_defaults(func=cmd_report)

    prs = sub.add_parser("reset", help="wipe state dir")
    prs.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    prs.set_defaults(func=cmd_reset)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
