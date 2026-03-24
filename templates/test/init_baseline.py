#!/usr/bin/env python3
"""
init_baseline.py — 从首次测试结果初始化 test_baseline.json

读取采集器输出的 result.json，提取通过测试名单和指标数值，
生成棘轮 baseline。

用法: python init_baseline.py <result.json> <baseline_output> [--known-failures test1,test2]
"""

import json
import os
import sys
from datetime import datetime, timezone


def main():
    if len(sys.argv) < 3:
        print("用法: python init_baseline.py <result.json> <baseline_output> [--known-failures test1,test2]")
        sys.exit(1)

    result_path = sys.argv[1]
    output_path = sys.argv[2]

    known_failures = []
    if "--known-failures" in sys.argv:
        idx = sys.argv.index("--known-failures")
        if idx + 1 < len(sys.argv):
            known_failures = [t.strip() for t in sys.argv[idx + 1].split(",") if t.strip()]

    with open(result_path) as f:
        result = json.load(f)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    commit = result.get("commit", "unknown")

    # 提取通过测试名单
    passed = result.get("tests", {}).get("passed", [])

    # 提取指标
    metrics = {}
    for name, data in result.get("metrics", {}).items():
        metrics[name] = {"value": data["value"]}

    baseline = {
        "version": "1.0",
        "commit": commit,
        "created_at": now,
        "passing_tests": sorted(passed),
        "known_failures": sorted(known_failures),
        "metrics": metrics,
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2, ensure_ascii=False)

    failed_names = [
        t["name"] if isinstance(t, dict) else t
        for t in result.get("tests", {}).get("failed", [])
    ]

    print(f"Test baseline created: {output_path}")
    print(f"  Commit: {commit}")
    print(f"  Passing tests: {len(passed)}")
    print(f"  Known failures: {len(known_failures)}")
    if failed_names:
        print(f"  Currently failing ({len(failed_names)}):")
        for t in failed_names[:10]:
            print(f"    - {t}")
        if len(failed_names) > 10:
            print(f"    ... and {len(failed_names) - 10} more")


if __name__ == "__main__":
    main()
