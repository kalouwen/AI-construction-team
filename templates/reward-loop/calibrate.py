#!/usr/bin/env python3
"""
calibrate.py — 环境重校准

定期重跑 baseline 场景，检测环境是否漂移。
如果同一份代码的性能结果跟 baseline 差距过大，说明环境变了（不是代码变了），
需要重新录制 baseline。

用法:
  python calibrate.py <config> <baseline> <results_dir>
  python calibrate.py <config> <baseline> <results_dir> --auto-update

参数:
  config      — perf.yaml 路径
  baseline    — baseline.json 路径
  results_dir — 本次校准的采集结果目录（需先跑 collector）
  --auto-update — 如果检测到漂移，自动更新 baseline

exit code: 0=正常, 1=检测到漂移
"""

import glob
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


def compute_medians(results_dir):
    files = sorted(glob.glob(os.path.join(results_dir, "result_*.json")))
    if not files:
        return None

    results = [load_json(f) for f in files]

    metrics_values = {}
    for r in results:
        for name, data in r.get("metrics", {}).items():
            metrics_values.setdefault(name, []).append(data["value"])

    medians = {}
    for name, values in metrics_values.items():
        values.sort()
        n = len(values)
        medians[name] = values[n // 2] if n % 2 == 1 else (values[n // 2 - 1] + values[n // 2]) / 2

    return medians


def check_drift(baseline, current_medians, drift_threshold=15):
    """
    对比 baseline 和当前测量值。
    如果差距超过 drift_threshold%，判定为环境漂移。
    """
    drifts = []

    abs_metrics = baseline.get("absolute", {}).get("metrics", {})

    for name, current_val in current_medians.items():
        base_entry = abs_metrics.get(name, {})
        base_val = base_entry.get("value")

        if base_val is None or base_val == 0:
            continue

        change_pct = abs((current_val - base_val) / base_val) * 100

        if change_pct > drift_threshold:
            drifts.append({
                "metric": name,
                "baseline_value": base_val,
                "current_value": current_val,
                "change_pct": round(change_pct, 1),
                "direction": "higher" if current_val > base_val else "lower",
            })

    return drifts


def update_baseline(baseline_path, baseline, current_medians):
    """用当前测量值更新 baseline 的绝对和相对基准。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for target in ["absolute", "relative"]:
        baseline[target]["updated_at"] = now
        for name, val in current_medians.items():
            baseline[target]["metrics"].setdefault(name, {})["value"] = val

    baseline["absolute"]["description"] = f"Recalibrated on {now}"

    with open(baseline_path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2, ensure_ascii=False)


def main():
    if len(sys.argv) < 4:
        print("用法: python calibrate.py <config> <baseline> <results_dir> [--auto-update]")
        sys.exit(1)

    config_path = sys.argv[1]
    baseline_path = sys.argv[2]
    results_dir = sys.argv[3]
    auto_update = "--auto-update" in sys.argv

    config = load_yaml(config_path)
    drift_threshold = config.get("calibration", {}).get("drift_threshold", 15)

    if not os.path.exists(baseline_path):
        print("ERROR: Baseline file not found:", baseline_path)
        sys.exit(1)

    baseline = load_json(baseline_path)
    current_medians = compute_medians(results_dir)

    if current_medians is None:
        print("ERROR: No result files found in", results_dir)
        sys.exit(1)

    drifts = check_drift(baseline, current_medians, drift_threshold)

    print(f"{'=' * 60}")
    print(f"  Environment Calibration Check")
    print(f"  Drift threshold: {drift_threshold}%")
    print(f"{'=' * 60}")

    if not drifts:
        print(f"  Status: STABLE")
        print(f"  All metrics within {drift_threshold}% of baseline")
        for name, val in current_medians.items():
            base_val = baseline.get("absolute", {}).get("metrics", {}).get(name, {}).get("value", "?")
            print(f"    {name}: {val} (baseline: {base_val})")
        print(f"{'=' * 60}")
        sys.exit(0)

    print(f"  Status: DRIFT DETECTED ({len(drifts)} metric(s))")
    print()
    for d in drifts:
        print(f"  {d['metric']}:")
        print(f"    Baseline: {d['baseline_value']}")
        print(f"    Current:  {d['current_value']} ({d['direction']} by {d['change_pct']}%)")
    print()

    if auto_update:
        print(f"  Auto-updating baseline...")
        update_baseline(baseline_path, baseline, current_medians)
        print(f"  Baseline updated: {baseline_path}")
    else:
        print(f"  Baseline NOT updated. Run with --auto-update to recalibrate.")
        print(f"  Or manually verify that the environment change is expected.")

    print(f"{'=' * 60}")

    # 输出 JSON 结果
    result = {
        "status": "drift",
        "drifts": drifts,
        "threshold": drift_threshold,
        "auto_updated": auto_update,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    result_path = os.path.join(results_dir, "calibration.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    sys.exit(1)


if __name__ == "__main__":
    main()
