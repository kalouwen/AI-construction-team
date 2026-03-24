#!/usr/bin/env python3
"""
质量信号判定器 — 棘轮模式：指标只能降，不能升

首次运行：创建基准线，PASS
后续运行：任何指标高于基准线 → FAIL
         指标低于基准线 → PASS 并更新基准线（棘轮往低拧）

用法: python judge.py <config> <baseline> <result.json> <verdict.json>
"""

import json
import os
import sys


def main():
    baseline_path = sys.argv[2]
    result_path = sys.argv[3]
    verdict_path = sys.argv[4]

    with open(result_path, encoding="utf-8") as f:
        result = json.load(f)

    current_metrics = result.get("metrics", {})

    # 首次运行：无基准线 → 创建，PASS
    if not os.path.exists(baseline_path):
        os.makedirs(os.path.dirname(baseline_path) or ".", exist_ok=True)
        with open(baseline_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        verdict = {
            "version": "1.0",
            "verdict": "PASS",
            "summary": "Initial quality baseline created",
        }
        with open(verdict_path, "w", encoding="utf-8") as f:
            json.dump(verdict, f, indent=2, ensure_ascii=False)
        print("PASS — Initial baseline created")
        sys.exit(0)

    # 读基准线
    with open(baseline_path, encoding="utf-8") as f:
        baseline = json.load(f)

    baseline_metrics = baseline.get("metrics", {})

    # 逐项对比
    failures = []
    for name, current in current_metrics.items():
        base_val = baseline_metrics.get(name, {}).get("value", 0)
        cur_val = current.get("value", 0)
        lower_better = current.get("lower_is_better", True)

        if lower_better and cur_val > base_val:
            failures.append(f"{name}: {base_val} → {cur_val} (+{cur_val - base_val})")
        elif not lower_better and cur_val < base_val:
            failures.append(f"{name}: {base_val} → {cur_val} ({cur_val - base_val})")

    if failures:
        verdict = {
            "version": "1.0",
            "verdict": "FAIL",
            "summary": f"Quality regression: {'; '.join(failures)}",
        }
        exit_code = 1
        print(f"FAIL — {verdict['summary']}")
    else:
        # 更新基准线（棘轮往低拧）
        with open(baseline_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        verdict = {
            "version": "1.0",
            "verdict": "PASS",
            "summary": "Quality within baseline (baseline updated)",
        }
        exit_code = 0
        print(f"PASS — {verdict['summary']}")

    with open(verdict_path, "w", encoding="utf-8") as f:
        json.dump(verdict, f, indent=2, ensure_ascii=False)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
