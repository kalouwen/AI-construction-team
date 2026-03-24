#!/usr/bin/env python3
"""
init_baseline.py — 从首次采集结果初始化 baseline.json

读取 results 目录中的 result_*.json，取中位数，生成 baseline.json。
绝对基准和相对基准初始化为相同值。

用法: python init_baseline.py <results_dir> <baseline_output> [--description "v1.0 release"]
"""

import glob
import json
import os
import sys
from datetime import datetime, timezone


def compute_medians(results_dir):
    files = sorted(glob.glob(os.path.join(results_dir, "result_*.json")))
    if not files:
        print(f"ERROR: no result_*.json found in {results_dir}", file=sys.stderr)
        sys.exit(1)

    results = []
    for f in files:
        with open(f) as fh:
            results.append(json.load(fh))

    commit = results[0].get("commit", "unknown")

    metrics_values = {}
    for r in results:
        for name, data in r.get("metrics", {}).items():
            metrics_values.setdefault(name, []).append(data["value"])

    medians = {}
    for name, values in metrics_values.items():
        values.sort()
        n = len(values)
        medians[name] = values[n // 2] if n % 2 == 1 else (values[n // 2 - 1] + values[n // 2]) / 2

    return commit, medians, len(results)


def main():
    if len(sys.argv) < 3:
        print("用法: python init_baseline.py <results_dir> <baseline_output> [--description \"...\"]")
        sys.exit(1)

    results_dir = sys.argv[1]
    output_path = sys.argv[2]

    description = ""
    if "--description" in sys.argv:
        idx = sys.argv.index("--description")
        if idx + 1 < len(sys.argv):
            description = sys.argv[idx + 1]

    commit, medians, run_count = compute_medians(results_dir)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    metrics_block = {}
    for name, value in medians.items():
        metrics_block[name] = {"value": value}

    baseline = {
        "version": "1.0",
        "absolute": {
            "commit": commit,
            "created_at": now,
            "description": description or f"Initial baseline from {run_count} runs",
            "metrics": metrics_block,
        },
        "relative": {
            "commit": commit,
            "updated_at": now,
            "metrics": json.loads(json.dumps(metrics_block)),  # deep copy
        },
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2, ensure_ascii=False)

    print(f"Baseline created: {output_path}")
    print(f"  Commit: {commit}")
    print(f"  Runs: {run_count}")
    print(f"  Metrics:")
    for name, value in medians.items():
        print(f"    {name}: {value}")


if __name__ == "__main__":
    main()
