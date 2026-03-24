"""
验证统一编排器的核心逻辑（不需要 git/collector，直接测 signal 判定组合）

场景：
  1. 两个信号都 PASS → 整体 PASS
  2. 性能 PASS + 测试 FAIL → 整体 FAIL
  3. 性能 FAIL + 测试 PASS → 整体 FAIL

用法: python test_orchestrator.py
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
WORK = SCRIPT_DIR / ".test_orch"

PERF_JUDGE = SCRIPT_DIR.parent / "perf" / "judge.py"
TEST_JUDGE = SCRIPT_DIR.parent / "test" / "test_judge.py"
PERF_CONFIG = SCRIPT_DIR.parent / "perf" / "perf.yaml"
TEST_CONFIG = SCRIPT_DIR.parent / "test" / "test.yaml"

# 清理
if WORK.exists():
    shutil.rmtree(WORK)
WORK.mkdir()

passed = 0


def make_perf_result(fps, memory):
    return {
        "version": "1.0", "commit": "test",
        "run_index": 1, "total_runs": 1,
        "environment": {"machine_id": "test"},
        "metrics": {
            "fps_avg": {"value": fps, "unit": "fps", "lower_is_better": False},
            "memory_peak_mb": {"value": memory, "unit": "MB", "lower_is_better": True},
        },
        "diagnostics": {},
    }


def make_test_result(passed_tests, failed_tests):
    failed_list = [{"name": n, "message": f"{n} failed", "file": "t.py:1"} for n in failed_tests]
    total = len(passed_tests) + len(failed_tests)
    rate = round(len(passed_tests) / total * 100, 1) if total else 0
    return {
        "version": "1.0", "commit": "test",
        "metrics": {
            "test_total": {"value": total, "unit": "count", "lower_is_better": False},
            "test_passed": {"value": len(passed_tests), "unit": "count", "lower_is_better": False},
            "test_failed": {"value": len(failed_tests), "unit": "count", "lower_is_better": True},
            "test_skipped": {"value": 0, "unit": "count", "lower_is_better": True},
            "pass_rate": {"value": rate, "unit": "%", "lower_is_better": False},
            "test_duration_sec": {"value": 5, "unit": "seconds", "lower_is_better": True},
            "coverage_pct": {"value": 80, "unit": "%", "lower_is_better": False},
        },
        "tests": {
            "passed": passed_tests,
            "failed": failed_list,
            "skipped": [],
        },
    }


def make_perf_baseline(fps, memory):
    return {
        "version": "1.0",
        "absolute": {"commit": "v1", "created_at": "", "metrics": {
            "fps_avg": {"value": fps}, "memory_peak_mb": {"value": memory},
        }},
        "relative": {"commit": "prev", "updated_at": "", "metrics": {
            "fps_avg": {"value": fps}, "memory_peak_mb": {"value": memory},
        }},
    }


def make_test_baseline(passing):
    return {
        "version": "1.0", "commit": "v1", "created_at": "",
        "passing_tests": passing, "known_failures": [],
        "metrics": {
            "pass_rate": {"value": 100},
            "test_duration_sec": {"value": 5},
            "coverage_pct": {"value": 80},
        },
    }


def run_both(perf_result, test_result, perf_baseline, test_baseline, scenario_dir):
    """运行两个 judge，返回 (perf_verdict, test_verdict)。"""
    d = WORK / scenario_dir
    d.mkdir(parents=True, exist_ok=True)

    # 写入文件
    perf_results_dir = d / "perf_results"
    perf_results_dir.mkdir()
    with open(perf_results_dir / "result_1.json", "w") as f:
        json.dump(perf_result, f)
    with open(d / "perf_bl.json", "w") as f:
        json.dump(perf_baseline, f)
    with open(d / "test_result.json", "w") as f:
        json.dump(test_result, f)
    with open(d / "test_bl.json", "w") as f:
        json.dump(test_baseline, f)

    # 运行 perf judge
    perf_v_path = d / "perf_verdict.json"
    subprocess.run([
        sys.executable, str(PERF_JUDGE),
        str(PERF_CONFIG), str(d / "perf_bl.json"), str(perf_results_dir), str(perf_v_path),
    ])

    # 运行 test judge
    test_v_path = d / "test_verdict.json"
    subprocess.run([
        sys.executable, str(TEST_JUDGE),
        str(TEST_CONFIG), str(d / "test_bl.json"), str(d / "test_result.json"), str(test_v_path),
    ])

    with open(perf_v_path, encoding="utf-8") as f:
        pv = json.load(f)
    with open(test_v_path, encoding="utf-8") as f:
        tv = json.load(f)

    return pv, tv


print("=" * 60)
print("  Unified Orchestrator — Verification")
print("=" * 60)

# ===== 场景1: 两个都 PASS =====
print("\n[1/3] Both PASS → merge")

pv, tv = run_both(
    perf_result=make_perf_result(fps=60, memory=500),
    test_result=make_test_result(["t1", "t2", "t3"], []),
    perf_baseline=make_perf_baseline(fps=60, memory=500),
    test_baseline=make_test_baseline(["t1", "t2", "t3"]),
    scenario_dir="s1",
)

both_pass = pv["verdict"] == "PASS" and tv["verdict"] == "PASS"
assert both_pass, f"Expected both PASS, got perf={pv['verdict']} test={tv['verdict']}"
print(f"  perf={pv['verdict']} test={tv['verdict']} → MERGE")
passed += 1

# ===== 场景2: perf PASS, test FAIL (regression) =====
print("\n[2/3] Perf PASS + Test FAIL → reject")

pv, tv = run_both(
    perf_result=make_perf_result(fps=60, memory=500),
    test_result=make_test_result(["t1", "t3"], ["t2"]),  # t2 regressed
    perf_baseline=make_perf_baseline(fps=60, memory=500),
    test_baseline=make_test_baseline(["t1", "t2", "t3"]),
    scenario_dir="s2",
)

assert pv["verdict"] == "PASS" and tv["verdict"] == "FAIL"
assert "t2" in tv["ratchet"]["regressions"]
print(f"  perf={pv['verdict']} test={tv['verdict']} → REJECT (t2 regression)")
passed += 1

# ===== 场景3: perf FAIL (memory spike), test PASS =====
print("\n[3/3] Perf FAIL + Test PASS → reject")

pv, tv = run_both(
    perf_result=make_perf_result(fps=60, memory=600),  # memory +20%
    test_result=make_test_result(["t1", "t2", "t3"], []),
    perf_baseline=make_perf_baseline(fps=60, memory=500),
    test_baseline=make_test_baseline(["t1", "t2", "t3"]),
    scenario_dir="s3",
)

assert pv["verdict"] == "FAIL" and tv["verdict"] == "PASS"
print(f"  perf={pv['verdict']} test={tv['verdict']} → REJECT (memory +20%)")
passed += 1

# 清理
shutil.rmtree(WORK)

print(f"\n{'=' * 60}")
print(f"  All {passed} scenarios passed!")
print(f"{'=' * 60}")
