#!/usr/bin/env python3
"""
orchestrator.py — 统一奖励信号循环编排器

在一个循环中运行多个奖励信号（性能、测试等），
全部 PASS 才合并，任一 FAIL 就回滚。

用法: python orchestrator.py <signals.yaml> [--dry-run] [--single-round]
  --dry-run       只打印流程，不执行
  --single-round  只跑一轮（用于 CI/手动验证）

依赖: pyyaml
"""

import json
import os
import subprocess
import sys
import time
import yaml
from pathlib import Path
from datetime import datetime, timezone


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def git(*args):
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
    )
    return result.stdout.strip(), result.returncode


def resolve_path(base_dir, rel_path):
    """相对于 signals.yaml 所在目录解析路径。"""
    return str((base_dir / rel_path).resolve())


def run_signal(signal_cfg, base_dir, round_num):
    """
    运行单个信号的 collector + judge。
    返回 (verdict_dict, exit_code, verdict_path)
    """
    name = signal_cfg["name"]
    judge_path = resolve_path(base_dir, signal_cfg["judge"])
    collector_path = resolve_path(base_dir, signal_cfg["collector"])
    config_path = resolve_path(base_dir, signal_cfg["config"])
    baseline_path = resolve_path(base_dir, signal_cfg["baseline"])
    results_dir = resolve_path(base_dir, signal_cfg["results_dir"])
    mode = signal_cfg.get("mode", "median")

    round_results = os.path.join(results_dir, f"round_{round_num}")
    os.makedirs(round_results, exist_ok=True)

    # --- 1. 采集 ---
    print(f"    [{name}] Collecting...")
    try:
        subprocess.run(
            ["bash", collector_path, config_path, round_results],
            check=True,
            timeout=300,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"    [{name}] Collector failed: {e}")
        return {"verdict": "ERROR", "summary": f"Collector failed: {e}"}, 1, None

    # --- 2. 判定 ---
    print(f"    [{name}] Judging...")
    verdict_path = os.path.join(round_results, "verdict.json")

    if mode == "single":
        # 测试信号：judge 直接读 result_1.json
        result_file = os.path.join(round_results, "result_1.json")
        if not os.path.exists(result_file):
            return {"verdict": "ERROR", "summary": "No result file"}, 1, None

        judge_result = subprocess.run(
            [sys.executable, judge_path, config_path, baseline_path, result_file, verdict_path],
        )
    else:
        # 性能信号：judge 读 results_dir（多文件取中位数）
        judge_result = subprocess.run(
            [sys.executable, judge_path, config_path, baseline_path, round_results, verdict_path],
        )

    if not os.path.exists(verdict_path):
        return {"verdict": "ERROR", "summary": "Judge produced no verdict"}, 1, None

    with open(verdict_path, encoding="utf-8") as f:
        verdict = json.load(f)

    return verdict, judge_result.returncode, verdict_path


def update_history(history_file, trajectory_file, round_num, signals_results, description, duration):
    """更新统一的历史记录。"""
    # trajectory 条目
    entry = {
        "round": round_num,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": "",
        "plan": description,
        "signals": {},
        "overall": "PASS",
        "duration_sec": duration,
    }

    all_pass = True
    for name, (verdict, _, _) in signals_results.items():
        v = verdict.get("verdict", "ERROR")
        entry["signals"][name] = {
            "verdict": v,
            "summary": verdict.get("summary", ""),
        }
        if v != "PASS":
            all_pass = False

    entry["overall"] = "PASS" if all_pass else "FAIL"
    entry["commit"], _ = git("rev-parse", "--short", "HEAD")

    # 追加 trajectory
    os.makedirs(os.path.dirname(trajectory_file) or ".", exist_ok=True)
    with open(trajectory_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # 更新 history
    if os.path.exists(history_file):
        with open(history_file, encoding="utf-8") as f:
            history = json.load(f)
    else:
        history = {
            "version": "1.0",
            "total_rounds": 0,
            "merged": [],
            "failed": [],
            "convergence": {"rounds_without_improvement": 0},
        }

    history["total_rounds"] = round_num

    if all_pass:
        history["merged"].append({
            "round": round_num,
            "commit": entry["commit"],
            "description": description,
            "signals": {n: s["summary"] for n, s in entry["signals"].items()},
        })
        history["convergence"]["rounds_without_improvement"] = 0
    else:
        failed_signals = [n for n, s in entry["signals"].items() if s["verdict"] != "PASS"]
        history["failed"].append({
            "round": round_num,
            "description": description,
            "failed_signals": failed_signals,
        })
        history["convergence"]["rounds_without_improvement"] += 1

    # 裁剪
    max_recent = 10
    history["merged"] = history["merged"][-max_recent:]
    history["failed"] = history["failed"][-max_recent:]

    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def update_baselines(signals_config, signals_results, base_dir):
    """PASS 的信号更新其 baseline。"""
    for sig_cfg in signals_config:
        name = sig_cfg["name"]
        if name not in signals_results:
            continue
        verdict, code, verdict_path = signals_results[name]
        if verdict.get("verdict") != "PASS" or verdict_path is None:
            continue

        baseline_path = resolve_path(base_dir, sig_cfg["baseline"])
        mode = sig_cfg.get("mode", "median")

        if mode == "median":
            # 性能信号：更新 relative baseline 的 metrics
            if not os.path.exists(baseline_path):
                continue
            with open(baseline_path, encoding="utf-8") as f:
                baseline = json.load(f)

            baseline["relative"]["commit"] = verdict.get("commit", "")
            baseline["relative"]["updated_at"] = verdict.get("timestamp", "")
            for metric_name, detail in verdict.get("details", {}).items():
                baseline["relative"]["metrics"].setdefault(metric_name, {})["value"] = detail["measured"]

            with open(baseline_path, "w", encoding="utf-8") as f:
                json.dump(baseline, f, indent=2, ensure_ascii=False)
            print(f"    [{name}] Baseline updated (relative)")

        elif mode == "single":
            # 测试信号：更新 passing_tests 名单
            if not os.path.exists(baseline_path):
                continue

            # 从最新的 result 中提取 passing tests
            results_dir = resolve_path(base_dir, sig_cfg["results_dir"])
            round_dirs = sorted(Path(results_dir).glob("round_*"))
            if not round_dirs:
                continue
            latest_result = round_dirs[-1] / "result_1.json"
            if not latest_result.exists():
                continue

            with open(latest_result, encoding="utf-8") as f:
                result = json.load(f)
            with open(baseline_path, encoding="utf-8") as f:
                baseline = json.load(f)

            # 棘轮：只添加新通过的测试，不移除
            current_passed = set(result.get("tests", {}).get("passed", []))
            baseline_passed = set(baseline.get("passing_tests", []))
            updated = sorted(baseline_passed | current_passed)
            baseline["passing_tests"] = updated
            baseline["commit"] = verdict.get("commit", baseline.get("commit", ""))

            # 更新 metrics
            for metric_name, data in result.get("metrics", {}).items():
                baseline["metrics"][metric_name] = {"value": data["value"]}

            with open(baseline_path, "w", encoding="utf-8") as f:
                json.dump(baseline, f, indent=2, ensure_ascii=False)
            print(f"    [{name}] Baseline updated (ratchet: {len(updated)} passing tests)")


def main():
    if len(sys.argv) < 2:
        print("用法: python orchestrator.py <signals.yaml> [--dry-run] [--single-round]")
        sys.exit(1)

    config_path = sys.argv[1]
    dry_run = "--dry-run" in sys.argv
    single_round = "--single-round" in sys.argv

    config = load_config(config_path)
    base_dir = Path(config_path).parent

    signals_config = [s for s in config.get("signals", []) if s.get("enabled", True)]
    loop_cfg = config.get("loop", {})
    history_cfg = config.get("history", {})
    merge_strategy = config.get("merge", {}).get("strategy", "all")

    max_rounds = 1 if single_round else loop_cfg.get("max_rounds", 20)
    max_duration_min = loop_cfg.get("max_duration_min", 240)
    stop_after_no_improve = loop_cfg.get("stop_after_no_improve", 5)
    strategy_switch_after = loop_cfg.get("strategy_switch_after", 3)

    history_file = resolve_path(base_dir, history_cfg.get("history_file", ".signals/history.json"))
    trajectory_file = resolve_path(base_dir, history_cfg.get("trajectory_file", ".signals/trajectory.jsonl"))

    base_branch, _ = git("rev-parse", "--abbrev-ref", "HEAD")
    start_time = time.time()

    print("=" * 60)
    print("  Unified Reward Signal Loop")
    print(f"  Signals: {', '.join(s['name'] for s in signals_config)}")
    print(f"  Merge strategy: {merge_strategy}")
    print(f"  Base branch: {base_branch}")
    print(f"  Max rounds: {max_rounds}")
    print("=" * 60)

    if dry_run:
        print("\n[DRY-RUN] Each round will:")
        for s in signals_config:
            print(f"  1. Run [{s['name']}] collector: {s['collector']}")
            print(f"     Run [{s['name']}] judge: {s['judge']}")
        print(f"  2. All PASS → merge to {base_branch}")
        print(f"  3. Any FAIL → discard, AI reads diagnostics, retries")
        return

    rounds_without_improvement = 0
    final_round = 0

    for round_num in range(1, max_rounds + 1):
        final_round = round_num
        elapsed_min = (time.time() - start_time) / 60

        print(f"\n{'━' * 60}")
        print(f"  Round {round_num} / {max_rounds}  ({elapsed_min:.0f}m elapsed)")
        print(f"{'━' * 60}")

        # --- 退出检查 ---
        if elapsed_min >= max_duration_min:
            print(f"  Time limit ({max_duration_min}m). Stopping.")
            break
        if rounds_without_improvement >= stop_after_no_improve:
            print(f"  No improvement for {rounds_without_improvement} rounds. Stopping.")
            break
        if rounds_without_improvement >= strategy_switch_after:
            print(f"  WARNING: {rounds_without_improvement} rounds without improvement. Switch strategy.")

        # --- 创建分支 ---
        branch = f"reward/round-{round_num}"
        git("checkout", base_branch)
        git("checkout", "-b", branch)

        # --- 等待 AI ---
        print(f"\n  Waiting for AI...")
        print(f"  AI should read: {history_file}")
        print(f"  Signal completion: touch .signals/ai_done")

        ai_done = ".signals/ai_done"
        os.makedirs(".signals", exist_ok=True)
        while not os.path.exists(ai_done):
            time.sleep(5)
        os.remove(ai_done)

        round_start = time.time()

        # --- 运行所有信号 ---
        print(f"\n  Running {len(signals_config)} signal(s)...")
        signals_results = {}
        all_pass = True

        for sig_cfg in signals_config:
            name = sig_cfg["name"]
            verdict, code, verdict_path = run_signal(sig_cfg, base_dir, round_num)
            signals_results[name] = (verdict, code, verdict_path)

            v = verdict.get("verdict", "ERROR")
            print(f"    [{name}] → {v}: {verdict.get('summary', '')}")

            if v != "PASS":
                all_pass = False
                if merge_strategy == "all":
                    # 快速失败：如果策略是 all，一个失败就不用继续跑后面的了
                    remaining = [s["name"] for s in signals_config if s["name"] not in signals_results]
                    if remaining:
                        print(f"    Skipping remaining signals: {remaining} (early fail)")
                    break

        round_duration = int(time.time() - round_start)

        # --- 读取描述 ---
        description, _ = git("log", "-1", "--pretty=format:%s")

        # --- 更新历史 ---
        update_history(
            history_file, trajectory_file, round_num,
            signals_results, description or f"round {round_num}", round_duration
        )

        # --- 合并或回滚 ---
        if all_pass:
            print(f"\n  ALL PASS → Merging to {base_branch}")
            git("checkout", base_branch)
            git("merge", branch, "--no-ff", "-m", f"reward: merge round {round_num}")

            if config.get("merge", {}).get("update_baseline_on_pass", True):
                update_baselines(signals_config, signals_results, base_dir)

            rounds_without_improvement = 0
            git("branch", "-d", branch)
        else:
            failed_names = [
                n for n, (v, _, _) in signals_results.items()
                if v.get("verdict") != "PASS"
            ]
            print(f"\n  FAIL ({', '.join(failed_names)}) → Discarding {branch}")
            git("checkout", base_branch)
            git("branch", "-D", branch)
            rounds_without_improvement += 1

    # --- 最终报告 ---
    total_min = (time.time() - start_time) / 60

    print(f"\n{'=' * 60}")
    print(f"  Loop Complete")
    print(f"  Rounds: {final_round} | Duration: {total_min:.0f}m")
    print(f"{'=' * 60}")

    if os.path.exists(trajectory_file):
        entries = []
        with open(trajectory_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))

        passed = [e for e in entries if e["overall"] == "PASS"]
        failed = [e for e in entries if e["overall"] != "PASS"]
        print(f"  Passed: {len(passed)} | Failed: {len(failed)}")
        if entries:
            print(f"  Pass rate: {len(passed)/len(entries)*100:.0f}%")
        if passed:
            print(f"  Merged:")
            for p in passed:
                sigs = ", ".join(f"{n}={s['verdict']}" for n, s in p["signals"].items())
                print(f"    Round {p['round']}: {p['plan']} [{sigs}]")

    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
