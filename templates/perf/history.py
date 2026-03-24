#!/usr/bin/env python3
"""
history.py — 历史摘要管理器

每轮循环后调用，更新 history.json 和 trajectory.jsonl
为下一轮 AI 提供策略输入

用法: python history.py <config> <verdict> <round_info_json> <history_file> <trajectory_file>

round_info_json 示例:
  '{"round": 4, "description": "压缩纹理格式", "expected": "memory -40MB", "duration_sec": 180}'

依赖: pyyaml
"""

import json
import os
import sys
import yaml
from datetime import datetime, timezone


def main():
    if len(sys.argv) < 6:
        print(
            "用法: python history.py <config> <verdict> <round_info_json> "
            "<history_file> <trajectory_file>"
        )
        sys.exit(1)

    config_path = sys.argv[1]
    verdict_path = sys.argv[2]
    round_info_str = sys.argv[3]
    history_path = sys.argv[4]
    trajectory_path = sys.argv[5]

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    with open(verdict_path, encoding="utf-8") as f:
        verdict = json.load(f)

    round_info = json.loads(round_info_str)
    max_recent = config.get("history", {}).get("max_recent_rounds", 10)

    # -----------------------------------------------------------------------
    # 1. 追加 trajectory 记录
    # -----------------------------------------------------------------------
    actual = {}
    for name, detail in verdict.get("details", {}).items():
        if "change_vs_relative" in detail:
            actual[name] = detail["change_vs_relative"]

    trajectory_entry = {
        "round": round_info["round"],
        "timestamp": verdict.get(
            "timestamp",
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
        "commit": verdict.get("commit", "unknown"),
        "plan": round_info.get("description", ""),
        "expected": round_info.get("expected", ""),
        "actual": actual,
        "verdict": verdict["verdict"],
        "summary": verdict["summary"],
        "duration_sec": round_info.get("duration_sec", 0),
    }

    with open(trajectory_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(trajectory_entry, ensure_ascii=False) + "\n")

    # -----------------------------------------------------------------------
    # 2. 更新 history.json
    # -----------------------------------------------------------------------
    if os.path.exists(history_path):
        with open(history_path, encoding="utf-8") as f:
            history = json.load(f)
    else:
        history = {
            "version": "1.0",
            "total_rounds": 0,
            "merged_improvements": [],
            "failed_attempts": [],
            "remaining_bottlenecks": [],
            "convergence": {
                "recent_improvement_rate": "0%",
                "rounds_without_improvement": 0,
                "strategy_switches": 0,
            },
        }

    history["total_rounds"] = round_info["round"]

    if verdict["verdict"] == "PASS":
        impact = {}
        for name, detail in verdict.get("details", {}).items():
            if "change_vs_relative" in detail:
                impact[name] = detail["change_vs_relative"]

        history["merged_improvements"].append(
            {
                "round": round_info["round"],
                "commit": verdict.get("commit", ""),
                "description": round_info.get("description", ""),
                "impact": impact,
            }
        )
        history["convergence"]["rounds_without_improvement"] = 0
    else:
        fail_reasons = []
        for name, detail in verdict.get("details", {}).items():
            if detail["verdict"] == "FAIL":
                fail_reasons.append(f"{name}: {detail.get('reason', 'unknown')}")

        history["failed_attempts"].append(
            {
                "round": round_info["round"],
                "description": round_info.get("description", ""),
                "reason": "; ".join(fail_reasons),
            }
        )
        history["convergence"]["rounds_without_improvement"] += 1

    # 更新瓶颈
    bottlenecks = []
    for name, detail in verdict.get("details", {}).items():
        if "diagnostics_hint" in detail:
            bottlenecks.append({"metric": name, "hint": detail["diagnostics_hint"]})
    history["remaining_bottlenecks"] = bottlenecks

    # 裁剪历史
    if len(history["failed_attempts"]) > max_recent:
        history["failed_attempts"] = history["failed_attempts"][-max_recent:]
    if len(history["merged_improvements"]) > max_recent:
        history["merged_improvements"] = history["merged_improvements"][-max_recent:]

    # 计算近期改善率
    total = history["total_rounds"]
    recent_passes = [
        m
        for m in history["merged_improvements"]
        if m["round"] > total - 5
    ]
    if total > 0:
        rate = (len(recent_passes) / min(5, total)) * 100
        history["convergence"][
            "recent_improvement_rate"
        ] = f"{rate:.0f}% pass rate in last 5 rounds"

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    # -----------------------------------------------------------------------
    # 3. 打印摘要
    # -----------------------------------------------------------------------
    r = round_info["round"]
    print(f"\n--- History Summary (round {r}) ---")
    print(f"Merged improvements: {len(history['merged_improvements'])}")
    print(f"Failed attempts: {len(history['failed_attempts'])}")
    print(
        f"Rounds without improvement: "
        f"{history['convergence']['rounds_without_improvement']}"
    )
    print(f"Recent rate: {history['convergence']['recent_improvement_rate']}")
    if history["remaining_bottlenecks"]:
        print("Remaining bottlenecks:")
        for b in history["remaining_bottlenecks"]:
            print(f"  - [{b['metric']}] {b['hint']}")
    print("---\n")


if __name__ == "__main__":
    main()
