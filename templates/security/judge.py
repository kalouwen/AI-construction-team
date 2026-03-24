#!/usr/bin/env python3
"""
安全信号判定器 — 任何密钥匹配 = FAIL
不需要基准线，零容忍策略。

用法: python judge.py <config> <baseline> <result.json> <verdict.json>
"""

import json
import sys


def main():
    # 参数对齐其他 judge 的签名（config 和 baseline 在此信号中不使用）
    result_path = sys.argv[3]
    verdict_path = sys.argv[4]

    with open(result_path, encoding="utf-8") as f:
        result = json.load(f)

    matches = result.get("metrics", {}).get("secret_matches", {}).get("value", 0)
    details = result.get("details", "")

    if matches > 0:
        verdict = {
            "version": "1.0",
            "verdict": "FAIL",
            "summary": f"Found {matches} potential secret(s) in changed files",
            "details": details,
        }
        exit_code = 1
    else:
        verdict = {
            "version": "1.0",
            "verdict": "PASS",
            "summary": "No secrets detected in changed files",
        }
        exit_code = 0

    with open(verdict_path, "w", encoding="utf-8") as f:
        json.dump(verdict, f, indent=2, ensure_ascii=False)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
