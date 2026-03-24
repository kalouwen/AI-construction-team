#!/usr/bin/env python3
"""
judge.py — 性能奖励信号判定器

读取采集结果（多次运行）和 baseline，取中位数对比，输出 verdict.json
技术栈无关：任何采集器只要输出标准 result.json 格式即可

用法: python judge.py <config> <baseline> <results_dir> <output>
依赖: pyyaml
"""

import json
import glob
import os
import sys
import yaml
from datetime import datetime, timezone


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def compute_medians(results_dir):
    """收集 result_*.json，对每个指标取中位数。"""
    files = sorted(glob.glob(os.path.join(results_dir, "result_*.json")))
    if not files:
        print("ERROR: no result files found in", results_dir, file=sys.stderr)
        sys.exit(1)

    results = [load_json(f) for f in files]

    # 公共信息
    commit = results[0].get("commit", "unknown")
    environment = results[0].get("environment", {})

    # 每个指标收集所有值
    metrics_values = {}
    for r in results:
        for name, data in r.get("metrics", {}).items():
            metrics_values.setdefault(name, []).append(data["value"])

    # 取中位数
    medians = {}
    for name, values in metrics_values.items():
        values.sort()
        n = len(values)
        medians[name] = values[n // 2] if n % 2 == 1 else (values[n // 2 - 1] + values[n // 2]) / 2

    # 取最后一次的 diagnostics
    diagnostics = results[-1].get("diagnostics", {})

    return {
        "commit": commit,
        "environment": environment,
        "total_runs": len(results),
        "medians": medians,
        "diagnostics": diagnostics,
    }


def judge(config, baseline, medians_data):
    """核心判定逻辑：对比双基准线，输出结构化结果。"""
    medians = medians_data["medians"]
    diagnostics = medians_data.get("diagnostics", {})
    max_soft_failures = config.get("judge", {}).get("max_soft_failures", 1)

    details = {}
    hard_failures = 0
    soft_failures = 0

    for metric_name, metric_config in config.get("metrics", {}).items():
        if metric_name not in medians:
            continue

        measured = medians[metric_name]
        lower_is_better = metric_config.get("lower_is_better", True)
        tier = metric_config.get("tier", "info")
        threshold_rel = metric_config.get("threshold_relative", 5)
        threshold_abs = metric_config.get("threshold_absolute", 10)

        detail = {
            "measured": measured,
            "tier": tier,
            "lower_is_better": lower_is_better,
        }

        reasons = []

        # 对比两条基准线
        for label, baseline_key, threshold in [
            ("relative", "relative", threshold_rel),
            ("absolute", "absolute", threshold_abs),
        ]:
            base_val = (
                baseline.get(baseline_key, {})
                .get("metrics", {})
                .get(metric_name, {})
                .get("value")
            )

            if base_val is None or base_val == 0:
                continue

            if lower_is_better:
                change = ((measured - base_val) / base_val) * 100
                degraded = change > threshold
            else:
                change = ((base_val - measured) / base_val) * 100
                degraded = change > threshold

            detail[f"baseline_{label}"] = base_val
            detail[f"change_vs_{label}"] = f"{'+' if change > 0 else ''}{change:.1f}%"
            detail[f"threshold_{label}"] = f"{threshold}%"

            if degraded:
                reasons.append(
                    f"exceeded {label} threshold ({detail[f'change_vs_{label}']} vs {threshold}%)"
                )

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

        # 诊断提示
        if metric_name in diagnostics:
            contribs = diagnostics[metric_name].get("top_contributors", [])
            if contribs:
                top = contribs[0]
                detail["diagnostics_hint"] = (
                    f"Top contributor: {top['source']} at "
                    f"{top['value']}{top.get('unit', '')} ({top['pct']}%)"
                )

        details[metric_name] = detail

    # 整体判定
    if hard_failures > 0:
        overall = "FAIL"
        summary = f"{hard_failures} hard metric(s) failed"
    elif soft_failures > max_soft_failures:
        overall = "FAIL"
        summary = f"{soft_failures} soft metric(s) failed (max allowed: {max_soft_failures})"
    else:
        overall = "PASS"
        passed = sum(1 for d in details.values() if d["verdict"] == "PASS")
        summary = f"All {passed} metrics passed"
        if soft_failures > 0:
            summary += f" ({soft_failures} soft warning(s))"

    return {
        "version": "1.0",
        "verdict": overall,
        "commit": medians_data["commit"],
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": summary,
        "total_runs_median": medians_data["total_runs"],
        "details": details,
    }


def print_verdict(verdict):
    """打印人类/AI 可读的判定报告。"""
    v = verdict["verdict"]
    print(f"\n{'=' * 60}")
    print(f"  VERDICT: {v}")
    print(f"  {verdict['summary']}")
    print(f"{'=' * 60}")

    for name, d in verdict["details"].items():
        status = "PASS" if d["verdict"] == "PASS" else "FAIL"
        line = f"  [{status}] {name}: {d['measured']}"
        if "change_vs_relative" in d:
            line += f" ({d['change_vs_relative']} vs relative)"
        if d["verdict"] == "FAIL" and "reason" in d:
            line += f"  <- {d['reason']}"
        print(line)
        if "diagnostics_hint" in d:
            print(f"    hint: {d['diagnostics_hint']}")

    print(f"{'=' * 60}\n")


def main():
    if len(sys.argv) < 5:
        print("用法: python judge.py <config> <baseline> <results_dir> <output>")
        sys.exit(1)

    config_path, baseline_path, results_dir, output_path = sys.argv[1:5]

    config = load_config(config_path)
    baseline = load_json(baseline_path)
    medians_data = compute_medians(results_dir)

    verdict = judge(config, baseline, medians_data)

    # 写入文件
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(verdict, f, indent=2, ensure_ascii=False)

    # 打印到 stdout
    print_verdict(verdict)

    # exit code: 0=PASS, 1=FAIL
    sys.exit(0 if verdict["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
