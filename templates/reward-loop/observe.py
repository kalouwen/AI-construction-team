#!/usr/bin/env python3
"""
observe.py — 观测器

改代码之前运行。采集当前状态，生成 AI 可读的诊断报告。
让 AI 知道"现在哪里有问题"，而不是盲猜。

用法: python observe.py <signals_dir> [--latest-verdict <verdict.json>]

输出: <signals_dir>/observation.md（喂给 prompt 模板）
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_trajectory(traj_path, max_lines=10):
    """读取最近 N 轮的 trajectory。"""
    if not os.path.exists(traj_path):
        return []
    entries = []
    with open(traj_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    return entries[-max_lines:]


def read_history(history_path):
    """读取历史摘要。"""
    if not os.path.exists(history_path):
        return None
    return load_json(history_path)


def find_latest_verdict(signals_dir):
    """找到最新一轮的 verdict 文件。"""
    verdicts = []
    for root, dirs, files in os.walk(signals_dir):
        for f in files:
            if f == "verdict.json":
                verdicts.append(os.path.join(root, f))

    if not verdicts:
        return None

    # 按修改时间排序取最新
    verdicts.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return verdicts[0]


def generate_report(signals_dir, verdict_path=None):
    """生成观测报告。"""
    lines = []
    lines.append("# Current State Observation")
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    lines.append("")

    # --- 最新判定结果 ---
    if verdict_path is None:
        verdict_path = find_latest_verdict(signals_dir)

    if verdict_path and os.path.exists(verdict_path):
        verdict = load_json(verdict_path)
        lines.append("## Latest Verdict")
        lines.append(f"- Result: **{verdict.get('verdict', 'unknown')}**")
        lines.append(f"- Summary: {verdict.get('summary', '')}")
        lines.append("")

        # 棘轮信息（测试/scorecard）
        ratchet = verdict.get("ratchet", {})
        if ratchet.get("regressions"):
            lines.append("### Regressions (must fix)")
            for r in ratchet["regressions"]:
                lines.append(f"- **{r}**")
            lines.append("")

        if ratchet.get("new_passes"):
            lines.append("### Recent Improvements")
            for p in ratchet["new_passes"]:
                lines.append(f"- {p} (newly passing)")
            lines.append("")

        # 指标详情
        details = verdict.get("details", {})
        if details:
            lines.append("### Metrics")
            for name, d in details.items():
                status = "PASS" if d.get("verdict") == "PASS" else "FAIL"
                measured = d.get("measured", "?")
                change = d.get("change_vs_relative", d.get("change", ""))
                line = f"- [{status}] {name}: {measured}"
                if change:
                    line += f" ({change})"
                if d.get("reason"):
                    line += f" — {d['reason']}"
                lines.append(line)
            lines.append("")

        # 失败诊断
        diags = verdict.get("failure_diagnostics", [])
        if diags:
            lines.append("### Failure Details")
            for d in diags[:5]:
                name = d.get("name", "?")
                msg = d.get("message", "")
                loc = d.get("file", "")
                lines.append(f"- **{name}**" + (f" ({loc})" if loc else ""))
                if msg:
                    lines.append(f"  {msg}")
            lines.append("")

        # 诊断提示（性能瓶颈等）
        for name, d in details.items():
            hint = d.get("diagnostics_hint", "")
            if hint:
                lines.append(f"### Bottleneck: {name}")
                lines.append(f"- {hint}")
                lines.append("")

    # --- 历史摘要 ---
    history_candidates = [
        os.path.join(signals_dir, "history.json"),
        os.path.join(signals_dir, "..", "history.json"),
    ]
    history = None
    for hp in history_candidates:
        if os.path.exists(hp):
            history = load_json(hp)
            break

    if history:
        lines.append("## History")
        lines.append(f"- Total rounds: {history.get('total_rounds', 0)}")

        conv = history.get("convergence", {})
        lines.append(f"- Rounds without improvement: {conv.get('rounds_without_improvement', 0)}")
        lines.append(f"- Recent rate: {conv.get('recent_improvement_rate', 'N/A')}")
        lines.append("")

        # 已合并的改进
        merged = history.get("merged", history.get("merged_improvements", []))
        if merged:
            lines.append("### What worked")
            for m in merged[-5:]:
                desc = m.get("description", m.get("plan", "?"))
                lines.append(f"- Round {m.get('round', '?')}: {desc}")
            lines.append("")

        # 失败的尝试
        failed = history.get("failed", history.get("failed_attempts", []))
        if failed:
            lines.append("### What didn't work (avoid these)")
            for f_item in failed[-5:]:
                desc = f_item.get("description", "?")
                reason = f_item.get("reason", f_item.get("failed_signals", "?"))
                lines.append(f"- {desc} — {reason}")
            lines.append("")

        # 剩余瓶颈
        bottlenecks = history.get("remaining_bottlenecks", [])
        if bottlenecks:
            lines.append("### Remaining bottlenecks")
            for b in bottlenecks:
                lines.append(f"- [{b.get('metric', '?')}] {b.get('hint', '')}")
            lines.append("")

    # --- Self-Heal Context（上一轮失败时的诊断，供本轮参考）---
    heal_ctx_path = os.path.join(signals_dir, "self-heal-context.md")
    if os.path.exists(heal_ctx_path):
        with open(heal_ctx_path, encoding="utf-8") as f:
            heal_ctx = f.read().strip()
        if heal_ctx:
            lines.append("## Previous Round Self-Heal Diagnosis")
            lines.append("(from the AI agent that ran last round)")
            lines.append("")
            lines.append(heal_ctx)
            lines.append("")

    # --- Trajectory（最近几轮的轨迹）---
    traj_candidates = [
        os.path.join(signals_dir, "trajectory.jsonl"),
        os.path.join(signals_dir, "..", "trajectory.jsonl"),
    ]
    for tp in traj_candidates:
        recent = read_trajectory(tp, max_lines=5)
        if recent:
            lines.append("## Recent Trajectory")
            for e in recent:
                r = e.get("round", "?")
                v = e.get("overall", "?")
                plan = e.get("plan", e.get("description", "?"))
                lines.append(f"- Round {r}: [{v}] {plan}")
            lines.append("")
            break

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("用法: python observe.py <signals_dir> [--latest-verdict <verdict.json>]")
        sys.exit(1)

    signals_dir = sys.argv[1]
    verdict_path = None
    if "--latest-verdict" in sys.argv:
        idx = sys.argv.index("--latest-verdict")
        if idx + 1 < len(sys.argv):
            verdict_path = sys.argv[idx + 1]

    report = generate_report(signals_dir, verdict_path)

    # 写到文件
    output_path = os.path.join(signals_dir, "observation.md")
    os.makedirs(signals_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    # 也打印到 stdout
    print(report)
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
