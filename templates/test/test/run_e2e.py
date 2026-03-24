"""
端到端测试：验证棘轮判定器的三种场景

1. 全部通过（无回归）→ PASS
2. 有回归（之前通过的测试挂了）→ FAIL
3. 有新通过（修了之前挂的测试）→ PASS + 报告 new passes

用法: python run_e2e.py
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
TEST_DIR = SCRIPT_DIR / ".test_verify"
JUDGE = SCRIPT_DIR.parent / "test_judge.py"
INIT_BL = SCRIPT_DIR.parent / "init_baseline.py"
CONFIG = SCRIPT_DIR.parent / "test.yaml"

# 清理
if TEST_DIR.exists():
    shutil.rmtree(TEST_DIR)
TEST_DIR.mkdir()

passed_all = 0
failed_any = 0


def run_judge(baseline_path, result_path, verdict_path):
    r = subprocess.run(
        [sys.executable, str(JUDGE), str(CONFIG), str(baseline_path), str(result_path), str(verdict_path)],
    )
    with open(verdict_path) as f:
        return json.load(f), r.returncode


def make_result(passed, failed, skipped=None):
    """生成模拟的采集器结果。"""
    failed_list = [{"name": n, "message": f"{n} failed", "file": "test.py:1"} for n in failed]
    total = len(passed) + len(failed) + len(skipped or [])
    num_passed = len(passed)
    return {
        "version": "1.0",
        "commit": "test",
        "metrics": {
            "test_total": {"value": total, "unit": "count", "lower_is_better": False},
            "test_passed": {"value": num_passed, "unit": "count", "lower_is_better": False},
            "test_failed": {"value": len(failed), "unit": "count", "lower_is_better": True},
            "test_skipped": {"value": len(skipped or []), "unit": "count", "lower_is_better": True},
            "pass_rate": {"value": round(num_passed / total * 100, 1) if total else 0, "unit": "%", "lower_is_better": False},
            "test_duration_sec": {"value": 10, "unit": "seconds", "lower_is_better": True},
            "coverage_pct": {"value": 80, "unit": "%", "lower_is_better": False},
        },
        "tests": {
            "passed": passed,
            "failed": failed_list,
            "skipped": skipped or [],
        },
    }


print("=" * 60)
print("  Test Reward Signal — E2E Verification")
print("=" * 60)

# ===== 场景1: 初始化 baseline，然后全部通过 =====
print("\n[1/3] No regressions → PASS")

initial = make_result(
    passed=["test_a", "test_b", "test_c", "test_d"],
    failed=["test_e"],
)
initial_path = TEST_DIR / "initial.json"
with open(initial_path, "w") as f:
    json.dump(initial, f)

# 初始化 baseline
bl_path = TEST_DIR / "baseline.json"
subprocess.run([sys.executable, str(INIT_BL), str(initial_path), str(bl_path)], check=True)

# 同样的结果再跑一遍
same_result = TEST_DIR / "same_result.json"
with open(same_result, "w") as f:
    json.dump(initial, f)

verdict, code = run_judge(bl_path, same_result, TEST_DIR / "verdict_1.json")
assert verdict["verdict"] == "PASS", f"Expected PASS, got {verdict['verdict']}"
assert verdict["ratchet"]["regression_count"] == 0
print(f"  Verdict: {verdict['verdict']} — {verdict['summary']}")
passed_all += 1

# ===== 场景2: 之前通过的 test_b 挂了 → FAIL =====
print("\n[2/3] Regression (test_b broke) → FAIL")

regression_result = make_result(
    passed=["test_a", "test_c", "test_d"],
    failed=["test_b", "test_e"],
)
reg_path = TEST_DIR / "regression.json"
with open(reg_path, "w") as f:
    json.dump(regression_result, f)

verdict, code = run_judge(bl_path, reg_path, TEST_DIR / "verdict_2.json")
assert verdict["verdict"] == "FAIL", f"Expected FAIL, got {verdict['verdict']}"
assert "test_b" in verdict["ratchet"]["regressions"]
assert code != 0
print(f"  Verdict: {verdict['verdict']} — {verdict['summary']}")
print(f"  Regressions: {verdict['ratchet']['regressions']}")
passed_all += 1

# ===== 场景3: test_e 从失败变成通过 → PASS + new passes =====
print("\n[3/3] New pass (test_e fixed) → PASS with new_passes")

fixed_result = make_result(
    passed=["test_a", "test_b", "test_c", "test_d", "test_e"],
    failed=[],
)
fix_path = TEST_DIR / "fixed.json"
with open(fix_path, "w") as f:
    json.dump(fixed_result, f)

verdict, code = run_judge(bl_path, fix_path, TEST_DIR / "verdict_3.json")
assert verdict["verdict"] == "PASS", f"Expected PASS, got {verdict['verdict']}"
assert "test_e" in verdict["ratchet"]["new_passes"]
assert code == 0
print(f"  Verdict: {verdict['verdict']} — {verdict['summary']}")
print(f"  New passes: {verdict['ratchet']['new_passes']}")
passed_all += 1

# ===== 清理 =====
shutil.rmtree(TEST_DIR)

print(f"\n{'=' * 60}")
print(f"  All {passed_all} scenarios passed!")
print(f"{'=' * 60}")
