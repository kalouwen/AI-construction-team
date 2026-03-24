#!/usr/bin/env python3
"""
test_judge.py — 测试奖励信号判定器

棘轮 + 阈值混合判定：
  1. 棘轮：之前通过的测试现在挂了 → FAIL（硬约束）
  2. 阈值：pass_rate / duration / coverage 的变化超过阈值 → FAIL/WARN

用法: python test_judge.py <config> <baseline> <result.json> <output>
  config   — test.yaml 路径
  baseline — test_baseline.json 路径
  result   — 采集器输出的 result.json 路径
  output   — verdict.json 输出路径

依赖: pyyaml
"""

import json
import os
import sys
import yaml
from datetime import datetime, timezone


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def ratchet_check(baseline, result, config):
    """
    棘轮检查：之前通过的测试现在必须仍然通过。

    返回 (regressions, new_passes, details_str)
    """
    ratchet_cfg = config.get("ratchet", {})
    if not ratchet_cfg.get("enabled", True):
        return [], [], "ratchet disabled"

    baseline_passing = set(baseline.get("passing_tests", []))
    known_failures = set(baseline.get("known_failures", []))

    current_passed = set(result.get("tests", {}).get("passed", []))
    current_failed_names = set(
        t["name"] if isinstance(t, dict) else t
        for t in result.get("tests", {}).get("failed", [])
    )

    # 回归 = 之前通过但现在不在通过列表中
    regressions_raw = baseline_passing - current_passed

    # 排除 known_failures（如果配置允许）
    if ratchet_cfg.get("allow_known_failures", True):
        regressions = regressions_raw - known_failures
    else:
        regressions = regressions_raw

    # 只保留确实在 failed 列表中的（排除 skipped 等情况）
    confirmed_regressions = regressions & current_failed_names

    # 新通过 = 现在通过但之前不在通过列表中
    new_passes = current_passed - baseline_passing

    return list(sorted(confirmed_regressions)), list(sorted(new_passes))


def threshold_check(config, baseline, result):
    """
    阈值检查：复用 perf 系统的逻辑。
    返回 details dict。
    """
    metrics_config = config.get("metrics", {})
    current_metrics = result.get("metrics", {})
    baseline_metrics = baseline.get("metrics", {})

    details = {}
    hard_failures = 0
    soft_failures = 0
    max_soft = config.get("judge", {}).get("max_soft_failures", 1)

    for name, mcfg in metrics_config.items():
        if name not in current_metrics:
            continue

        measured = current_metrics[name]["value"]
        lower_is_better = mcfg.get("lower_is_better", True)
        tier = mcfg.get("tier", "info")
        threshold_rel = mcfg.get("threshold_relative", 5)
        threshold_abs = mcfg.get("threshold_absolute", 10)

        detail = {
            "measured": measured,
            "tier": tier,
            "lower_is_better": lower_is_better,
        }

        reasons = []

        base_val = baseline_metrics.get(name, {}).get("value")
        if base_val is not None and base_val != 0:
            if lower_is_better:
                change = ((measured - base_val) / base_val) * 100
                degraded = change > threshold_rel
            else:
                change = ((base_val - measured) / base_val) * 100
                degraded = change > threshold_rel

            detail["baseline"] = base_val
            detail["change"] = f"{'+' if change > 0 else ''}{change:.1f}%"
            detail["threshold"] = f"{threshold_rel}%"

            if degraded:
                reasons.append(f"degraded {detail['change']} (threshold: {threshold_rel}%)")

        metric_verdict = "PASS"
        if reasons:
            metric_verdict = "FAIL"
            if tier == "hard":
                hard_failures += 1
            elif tier == "soft":
                soft_failures += 1

        detail["verdict"] = metric_verdict
        if reasons:
            detail["reason"] = "; ".join(reasons)

        details[name] = detail

    return details, hard_failures, soft_failures


def build_failure_diagnostics(result):
    """从测试结果中提取失败测试的诊断信息。"""
    failed_tests = result.get("tests", {}).get("failed", [])
    diagnostics = []

    for t in failed_tests:
        if isinstance(t, dict):
            diagnostics.append({
                "name": t["name"],
                "message": t.get("message", ""),
                "file": t.get("file", ""),
                "duration_sec": t.get("duration_sec", 0),
            })
        else:
            diagnostics.append({"name": t, "message": "", "file": ""})

    return diagnostics


def main():
    if len(sys.argv) < 5:
        print("用法: python test_judge.py <config> <baseline> <result.json> <output>")
        sys.exit(1)

    config_path, baseline_path, result_path, output_path = sys.argv[1:5]

    config = load_config(config_path)
    baseline = load_json(baseline_path)
    result = load_json(result_path)

    # --- 1. 棘轮检查 ---
    regressions, new_passes = ratchet_check(baseline, result, config)

    # --- 2. 阈值检查 ---
    metric_details, hard_failures, soft_failures = threshold_check(config, baseline, result)

    # --- 3. 失败诊断 ---
    failure_diagnostics = build_failure_diagnostics(result)

    # --- 4. 综合判定 ---
    ratchet_failed = len(regressions) > 0
    max_soft = config.get("judge", {}).get("max_soft_failures", 1)

    if ratchet_failed:
        overall = "FAIL"
        summary = f"Ratchet violation: {len(regressions)} previously-passing test(s) now failing"
    elif hard_failures > 0:
        overall = "FAIL"
        summary = f"{hard_failures} hard metric(s) failed"
    elif soft_failures > max_soft:
        overall = "FAIL"
        summary = f"{soft_failures} soft metric(s) failed (max allowed: {max_soft})"
    else:
        overall = "PASS"
        parts = []
        if new_passes:
            parts.append(f"{len(new_passes)} new test(s) passing")
        total_passed = result.get("metrics", {}).get("test_passed", {}).get("value", "?")
        total = result.get("metrics", {}).get("test_total", {}).get("value", "?")
        parts.append(f"{total_passed}/{total} tests passed")
        summary = ". ".join(parts)

    # --- 5. 组装输出 ---
    verdict = {
        "version": "1.0",
        "verdict": overall,
        "commit": result.get("commit", "unknown"),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": summary,
        "ratchet": {
            "regressions": regressions,
            "new_passes": new_passes,
            "regression_count": len(regressions),
            "new_pass_count": len(new_passes),
        },
        "details": metric_details,
        "failure_diagnostics": failure_diagnostics[:20],  # 最多20个
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(verdict, f, indent=2, ensure_ascii=False)

    # --- 6. 打印报告 ---
    print(f"\n{'=' * 60}")
    print(f"  VERDICT: {overall}")
    print(f"  {summary}")
    print(f"{'=' * 60}")

    if regressions:
        print(f"\n  REGRESSIONS ({len(regressions)} test(s) broke):")
        # 找到对应的诊断信息
        diag_map = {d["name"]: d for d in failure_diagnostics}
        for r in regressions:
            d = diag_map.get(r, {})
            msg = d.get("message", "")
            loc = d.get("file", "")
            line = f"    - {r}"
            if loc:
                line += f" ({loc})"
            if msg:
                line += f"\n      {msg}"
            print(line)

    if new_passes:
        print(f"\n  NEW PASSES ({len(new_passes)} test(s) fixed):")
        for p in new_passes[:10]:
            print(f"    + {p}")
        if len(new_passes) > 10:
            print(f"    ... and {len(new_passes) - 10} more")

    if metric_details:
        print(f"\n  METRICS:")
        for name, d in metric_details.items():
            status = "PASS" if d["verdict"] == "PASS" else "FAIL"
            line = f"    [{status}] {name}: {d['measured']}"
            if "change" in d:
                line += f" ({d['change']})"
            print(line)

    print(f"{'=' * 60}\n")

    sys.exit(0 if overall == "PASS" else 1)


if __name__ == "__main__":
    main()
