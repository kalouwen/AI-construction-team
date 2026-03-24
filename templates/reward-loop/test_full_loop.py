#!/usr/bin/env python3
"""
全链路集成测试

模拟完整的进化循环：
  observe → prompt → (mock AI) → guardrail → collect → judge → history → circuit_breaker

三个场景：
  1. 正常轮次：AI 改了合理的代码 → 信号 PASS → 合并
  2. 护栏拦截：AI 碰了冻结区 → guardrail BLOCK → 回滚
  3. 熔断触发：连续失败 → circuit_breaker HALT

不需要真实 AI、真实采集器、真实 git。全部用模拟数据。
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
WORK = SCRIPT_DIR / ".test_full_loop"

passed = 0
failed = 0


def setup_workspace():
    if WORK.exists():
        shutil.rmtree(WORK)
    (WORK / "signals").mkdir(parents=True)


def cleanup():
    if WORK.exists():
        shutil.rmtree(WORK)


def py(script, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT_DIR / script)] + list(args),
        capture_output=True, text=True,
    )


def write_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def assert_eq(name, actual, expected):
    global passed, failed
    if actual == expected:
        passed += 1
        print(f"    PASS: {name}")
    else:
        failed += 1
        print(f"    FAIL: {name} — expected {expected}, got {actual}")


# =========================================================================
# 场景 1: 正常轮次（observe → prompt → judge PASS → history）
# =========================================================================
def test_normal_round():
    print("\n[1/3] Normal round: observe → prompt → judge PASS → history")
    setup_workspace()
    signals_dir = str(WORK / "signals")
    config_path = str(SCRIPT_DIR / "signals.yaml")

    # --- Step 1: 写一个模拟的上一轮 verdict（作为观测输入）---
    verdict = {
        "version": "1.0",
        "verdict": "FAIL",
        "summary": "1 hard metric failed",
        "details": {
            "memory_peak_mb": {
                "measured": 548,
                "tier": "hard",
                "verdict": "FAIL",
                "change_vs_relative": "+7.5%",
                "reason": "exceeded relative threshold",
                "diagnostics_hint": "Top contributor: SceneLoader at 180MB (33%)",
            },
            "fps_avg": {
                "measured": 60,
                "tier": "hard",
                "verdict": "PASS",
                "change_vs_relative": "0.0%",
            },
        },
        "ratchet": {"regressions": [], "new_passes": []},
        "failure_diagnostics": [],
    }
    verdict_dir = WORK / "signals" / "perf" / "results" / "round_0"
    verdict_dir.mkdir(parents=True)
    write_json(str(verdict_dir / "verdict.json"), verdict)

    # --- Step 2: observe —
    r = py("observe.py", signals_dir)
    obs_path = WORK / "signals" / "observation.md"
    assert_eq("observe.py exits 0", r.returncode, 0)
    assert_eq("observation.md created", obs_path.exists(), True)

    obs_content = obs_path.read_text(encoding="utf-8")
    assert_eq("observation contains FAIL", "FAIL" in obs_content, True)
    assert_eq("observation contains bottleneck", "SceneLoader" in obs_content, True)

    # --- Step 3: prompt ---
    r = py("prompt.py", signals_dir, config_path)
    prompt_path = WORK / "signals" / "prompt.md"
    assert_eq("prompt.py exits 0", r.returncode, 0)
    assert_eq("prompt.md created", prompt_path.exists(), True)

    prompt_content = prompt_path.read_text(encoding="utf-8")
    assert_eq("prompt contains strategy level", "Level 1" in prompt_content, True)
    assert_eq("prompt contains frozen boundaries", "DO NOT MODIFY" in prompt_content, True)
    assert_eq("prompt contains observation", "SceneLoader" in prompt_content, True)

    # --- Step 4: 模拟 judge PASS（跳过真实采集，直接写 verdict）---
    pass_verdict = {
        "version": "1.0",
        "verdict": "PASS",
        "commit": "test",
        "timestamp": "2026-03-17T00:00:00Z",
        "summary": "All metrics passed",
        "details": {
            "memory_peak_mb": {"measured": 490, "verdict": "PASS", "change_vs_relative": "-3.5%"},
            "fps_avg": {"measured": 62, "verdict": "PASS", "change_vs_relative": "+3.3%"},
        },
    }
    r1_dir = WORK / "signals" / "perf" / "results" / "round_1"
    r1_dir.mkdir(parents=True)
    write_json(str(r1_dir / "verdict.json"), pass_verdict)

    # --- Step 5: history ---
    history_path = str(WORK / "signals" / "history.json")
    traj_path = str(WORK / "signals" / "trajectory.jsonl")
    round_info = json.dumps({
        "round": 1,
        "description": "Optimize SceneLoader memory",
        "expected": "memory -50MB",
        "duration_sec": 60,
    })

    # 用 perf 的 history.py（与 reward-loop 共享）
    perf_history = SCRIPT_DIR.parent / "perf" / "history.py"
    r = subprocess.run([
        sys.executable, str(perf_history),
        str(SCRIPT_DIR.parent / "perf" / "perf.yaml"),
        str(r1_dir / "verdict.json"),
        round_info,
        history_path,
        traj_path,
    ], capture_output=True, text=True)

    assert_eq("history.py exits 0", r.returncode, 0)
    assert_eq("history.json created", os.path.exists(history_path), True)
    assert_eq("trajectory.jsonl created", os.path.exists(traj_path), True)

    history = read_json(history_path)
    assert_eq("history has 1 merged", len(history.get("merged_improvements", [])), 1)
    assert_eq("rounds without improvement = 0", history["convergence"]["rounds_without_improvement"], 0)

    # --- Step 6: circuit_breaker ---
    r = py("circuit_breaker.py", signals_dir, config_path)
    assert_eq("circuit_breaker AUTO (exit 0)", r.returncode, 0)

    cleanup()


# =========================================================================
# 场景 2: 护栏拦截（guardrail BLOCK）
# =========================================================================
def test_guardrail_block():
    print("\n[2/3] Guardrail: detect reward hacking patterns")
    setup_workspace()
    config_path = str(SCRIPT_DIR / "signals.yaml")

    # guardrail 需要 git diff 输出，但我们不在 git 里。
    # 直接测 detect_reward_hacking 函数。

    sys.path.insert(0, str(SCRIPT_DIR))
    from guardrail import detect_reward_hacking, check_frozen_boundaries, audit_changes, DEFAULT_HACKING_PATTERNS

    # 测试 1: 删除测试
    diff_with_test_deletion = """\
-    def test_payment_flow():
-        assert process_payment(100) == True
+    # removed flaky test
"""
    detections = detect_reward_hacking(diff_with_test_deletion, DEFAULT_HACKING_PATTERNS)
    test_del = [d for d in detections if d["name"] == "test_deletion"]
    assert_eq("detects test deletion", len(test_del) > 0, True)

    # 测试 2: 关闭渲染
    diff_with_render_disable = """\
+    canvas.style.display = 'none';
+    renderer.visible = false;
"""
    detections = detect_reward_hacking(diff_with_render_disable, DEFAULT_HACKING_PATTERNS)
    render = [d for d in detections if d["name"] == "render_disable"]
    assert_eq("detects render disable", len(render) > 0, True)

    # 测试 3: 修改评分逻辑
    diff_with_eval_mod = """\
+    scorecard['build_diversity'].score = 10
+    pass_threshold = 1
"""
    detections = detect_reward_hacking(diff_with_eval_mod, DEFAULT_HACKING_PATTERNS)
    eval_mod = [d for d in detections if d["name"] == "eval_modification"]
    assert_eq("detects eval modification", len(eval_mod) > 0, True)

    # 测试 4: 冻结边界
    changed = ["scripts/reward/judge.py", "src/game.js", ".signals/baseline.json"]
    frozen = ["scripts/reward/", ".signals/"]
    violations = check_frozen_boundaries(changed, frozen)
    assert_eq("detects frozen boundary (2 files)", len(violations), 2)
    clean_files = ["src/game.js", "src/utils.js"]
    violations = check_frozen_boundaries(clean_files, frozen)
    assert_eq("no violation for clean files", len(violations), 0)

    # 测试 5: 变更审计
    warnings = audit_changes(
        {"files_changed": 50, "insertions": 10, "deletions": 800},
        {"max_files_changed": 20, "max_insertions": 500, "max_deletions": 300},
    )
    assert_eq("detects too many files", any(w["type"] == "too_many_files" for w in warnings), True)
    assert_eq("detects too many deletions", any(w["type"] == "too_many_deletions" for w in warnings), True)
    assert_eq("detects suspicious ratio", any(w["type"] == "suspicious_deletion_ratio" for w in warnings), True)

    sys.path.pop(0)
    cleanup()


# =========================================================================
# 场景 3: 熔断触发
# =========================================================================
def test_circuit_breaker():
    print("\n[3/3] Circuit breaker: halt after consecutive failures")
    setup_workspace()
    signals_dir = str(WORK / "signals")
    config_path = str(SCRIPT_DIR / "signals.yaml")

    # 写 5 轮连续失败
    traj_path = WORK / "signals" / "trajectory.jsonl"
    with open(traj_path, "w") as f:
        for i in range(5):
            f.write(json.dumps({
                "round": i + 1,
                "overall": "FAIL",
                "description": f"attempt {i+1}",
            }) + "\n")

    r = py("circuit_breaker.py", signals_dir, config_path)
    assert_eq("HALT after 5 failures (exit 2)", r.returncode, 2)

    # 写振荡模式: PASS FAIL PASS FAIL PASS FAIL
    with open(traj_path, "w") as f:
        for i in range(6):
            v = "PASS" if i % 2 == 0 else "FAIL"
            f.write(json.dumps({
                "round": i + 1,
                "overall": v,
                "description": "same thing",
            }) + "\n")

    r = py("circuit_breaker.py", signals_dir, config_path)
    assert_eq("PAUSE on oscillation (exit 1)", r.returncode, 1)

    # 写正常的 trajectory
    with open(traj_path, "w") as f:
        for i in range(3):
            f.write(json.dumps({
                "round": i + 1,
                "overall": "PASS",
                "description": f"improvement {i+1}",
            }) + "\n")

    r = py("circuit_breaker.py", signals_dir, config_path)
    assert_eq("AUTO when healthy (exit 0)", r.returncode, 0)

    cleanup()


# =========================================================================
# Run
# =========================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("  Full Loop Integration Test")
    print("=" * 60)

    test_normal_round()
    test_guardrail_block()
    test_circuit_breaker()

    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"  Results: {passed}/{total} passed", end="")
    if failed:
        print(f", {failed} FAILED")
    else:
        print()
    print(f"{'=' * 60}")

    sys.exit(1 if failed else 0)
