#!/usr/bin/env python3
"""
circuit_breaker.py — 熔断器 + 人类审查点

检查是否需要暂停自动循环，让人类介入。

四档判定：
  AUTO      — 正常继续
  NOTIFY    — 继续但通知人类
  PAUSE     — 暂停等人类确认
  HALT      — 强制停止

用法: python circuit_breaker.py <signals_dir> <config>

exit code: 0=AUTO/NOTIFY, 1=PAUSE, 2=HALT
"""

import json
import os
import sys
import yaml
from datetime import datetime, timezone


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_trajectory(traj_path):
    if not os.path.exists(traj_path):
        return []
    entries = []
    with open(traj_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    return entries


def check_consecutive_failures(trajectory, threshold):
    """连续失败次数。"""
    count = 0
    for entry in reversed(trajectory):
        v = entry.get("overall", "")
        if v != "PASS":
            count += 1
        else:
            break
    return count, count >= threshold


def check_total_unreviewed(history_path, review_interval):
    """自上次人类审查以来合并了多少次。"""
    if not os.path.exists(history_path):
        return 0, False

    history = load_json(history_path)
    merged = history.get("merged", history.get("merged_improvements", []))
    last_review = history.get("last_human_review_round", 0)

    unreviewed = [m for m in merged if m.get("round", 0) > last_review]
    return len(unreviewed), len(unreviewed) >= review_interval


def check_oscillation(trajectory, window=6):
    """检测 PASS/FAIL 振荡（A→B→A→B 模式）。"""
    if len(trajectory) < window:
        return False, ""

    recent = trajectory[-window:]
    verdicts = [e.get("overall", "") for e in recent]

    # 检查交替模式
    alternating = 0
    for i in range(1, len(verdicts)):
        if verdicts[i] != verdicts[i - 1]:
            alternating += 1

    # 如果 80%+ 的转换都是交替的，可能在振荡
    if alternating >= window - 2:
        return True, f"Verdict oscillation detected: {' → '.join(verdicts)}"

    # 检查描述是否重复（AI 在做同样的事）
    descriptions = [e.get("plan", e.get("description", "")) for e in recent]
    unique = set(descriptions)
    if len(unique) <= 2 and len(descriptions) >= 4:
        return True, f"Repeating same strategies: {unique}"

    return False, ""


def check_cumulative_changes(signals_dir, max_total_lines):
    """累计代码变更量是否过大。"""
    traj = read_trajectory(os.path.join(signals_dir, "trajectory.jsonl"))
    # 这里简化处理——实际应该从 git log 统计
    # 用轮次数 * 估算每轮平均变更量作为近似
    total_rounds = len(traj)
    estimated_lines = total_rounds * 50  # 粗估
    return estimated_lines, estimated_lines > max_total_lines


def main():
    if len(sys.argv) < 3:
        print("用法: python circuit_breaker.py <signals_dir> <config>")
        sys.exit(1)

    signals_dir = sys.argv[1]
    config_path = sys.argv[2]

    config = load_yaml(config_path)
    cb_cfg = config.get("circuit_breaker", {})

    # 配置参数
    max_consecutive_failures = cb_cfg.get("max_consecutive_failures", 5)
    notify_after_failures = cb_cfg.get("notify_after_failures", 3)
    review_interval = cb_cfg.get("human_review_interval", 10)
    max_cumulative_lines = cb_cfg.get("max_cumulative_lines", 2000)
    detect_oscillation = cb_cfg.get("detect_oscillation", True)

    # 读取数据
    traj_path = os.path.join(signals_dir, "trajectory.jsonl")
    trajectory = read_trajectory(traj_path)

    history_candidates = [
        os.path.join(signals_dir, "history.json"),
        os.path.join(signals_dir, "..", "history.json"),
    ]
    history_path = None
    for hp in history_candidates:
        if os.path.exists(hp):
            history_path = hp
            break

    # --- 检查 ---
    issues = []

    # 1. 连续失败
    fail_count, too_many_fails = check_consecutive_failures(trajectory, max_consecutive_failures)
    if too_many_fails:
        issues.append({
            "level": "HALT",
            "reason": f"Consecutive failures: {fail_count} (limit: {max_consecutive_failures})",
        })
    elif fail_count >= notify_after_failures:
        issues.append({
            "level": "NOTIFY",
            "reason": f"Consecutive failures: {fail_count}",
        })

    # 2. 未审查合并数
    if history_path:
        unreviewed, needs_review = check_total_unreviewed(history_path, review_interval)
        if needs_review:
            issues.append({
                "level": "PAUSE",
                "reason": f"Unreviewed merges: {unreviewed} (review every {review_interval})",
            })

    # 3. 振荡检测
    if detect_oscillation:
        is_oscillating, osc_detail = check_oscillation(trajectory)
        if is_oscillating:
            issues.append({
                "level": "PAUSE",
                "reason": f"Oscillation detected: {osc_detail}",
            })

    # 4. 累计变更量
    estimated_lines, too_much = check_cumulative_changes(signals_dir, max_cumulative_lines)
    if too_much:
        issues.append({
            "level": "PAUSE",
            "reason": f"Estimated cumulative changes: ~{estimated_lines} lines (limit: {max_cumulative_lines})",
        })

    # --- 判定 ---
    if not issues:
        level = "AUTO"
        summary = "All clear"
    else:
        # 取最严重的级别
        severity_order = {"HALT": 3, "PAUSE": 2, "NOTIFY": 1, "AUTO": 0}
        issues.sort(key=lambda x: severity_order.get(x["level"], 0), reverse=True)
        level = issues[0]["level"]
        summary = "; ".join(i["reason"] for i in issues)

    # --- 输出 ---
    print(f"{'=' * 60}")
    print(f"  Circuit Breaker: {level}")
    if issues:
        for i in issues:
            print(f"  [{i['level']}] {i['reason']}")
    else:
        print(f"  {summary}")
    print(f"{'=' * 60}")

    # 读取目标（如果有）
    goal = ""
    goal_path = os.path.join(signals_dir, "goal.txt")
    if os.path.exists(goal_path):
        with open(goal_path, encoding="utf-8") as f:
            goal = f.read().strip()

    result = {
        "level": level,
        "summary": summary,
        "issues": issues,
        "trajectory_length": len(trajectory),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    # 写 JSON（机器读）
    output_path = os.path.join(signals_dir, "circuit_breaker.json")
    os.makedirs(signals_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # 写阻断诊断报告（人读）— 只在 PAUSE/HALT 时生成
    if level in ("PAUSE", "HALT"):
        diag_lines = [
            "# Blocker Diagnosis",
            "",
            f"**Status**: {level}",
            f"**Time**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        ]
        if goal:
            diag_lines.append(f"**Goal**: {goal}")
        diag_lines.append("")
        diag_lines.append("## What's blocking")
        diag_lines.append("")
        for i in issues:
            diag_lines.append(f"- [{i['level']}] {i['reason']}")
        diag_lines.append("")
        diag_lines.append("## What's needed to continue")
        diag_lines.append("")
        for i in issues:
            lv = i["level"]
            reason = i["reason"]
            if "Consecutive failures" in reason:
                diag_lines.append(
                    "- **Check the failing signal**: look at the latest verdict.json "
                    "to understand why changes keep failing. The AI may be stuck on "
                    "an impossible optimization or a broken test."
                )
            elif "Unreviewed merges" in reason:
                diag_lines.append(
                    "- **Human review needed**: too many changes merged without review. "
                    "Check trajectory.jsonl, verify the changes make sense, then "
                    "`touch .signals/human_approved` to resume."
                )
            elif "Oscillation" in reason:
                diag_lines.append(
                    "- **Strategy is going in circles**: the AI is alternating between "
                    "the same approaches. Consider changing the goal, narrowing the "
                    "target files, or manually fixing the underlying issue."
                )
            elif "cumulative" in reason.lower():
                diag_lines.append(
                    "- **Too many total changes**: the accumulated diff is large. "
                    "Review what's been done so far, then decide whether to continue "
                    "or start a fresh round with updated baselines."
                )

        diag_path = os.path.join(signals_dir, "blocker-diagnosis.md")
        with open(diag_path, "w", encoding="utf-8") as f:
            f.write("\n".join(diag_lines))
        print(f"\n  Diagnosis written to: {diag_path}")

    exit_codes = {"AUTO": 0, "NOTIFY": 0, "PAUSE": 1, "HALT": 2}
    sys.exit(exit_codes.get(level, 0))


if __name__ == "__main__":
    main()
