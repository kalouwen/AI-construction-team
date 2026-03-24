#!/usr/bin/env python3
"""
loop.py — 性能优化自动循环编排器

驱动完整的 观测→策略→执行→判定→学习 循环。
这是一个参考实现，实际使用时需要：
  1. 实现 collector（技术栈相关）
  2. 配置 perf.yaml
  3. 录制 baseline.json

用法: python loop.py <config> [--dry-run]
前提: 在 git 仓库根目录运行

依赖: pyyaml
"""

import json
import os
import subprocess
import sys
import time
import yaml
from pathlib import Path


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def git(*args):
    """运行 git 命令，返回 stdout。"""
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
    )
    return result.stdout.strip(), result.returncode


def main():
    if len(sys.argv) < 2:
        print("用法: python loop.py <config> [--dry-run]")
        sys.exit(1)

    config_path = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    config = load_config(config_path)
    script_dir = Path(__file__).parent

    # 循环参数
    loop_cfg = config.get("loop", {})
    max_rounds = loop_cfg.get("max_rounds", 20)
    max_duration_min = loop_cfg.get("max_duration_min", 240)
    stop_after_no_improve = loop_cfg.get("stop_after_no_improve", 5)
    strategy_switch_after = loop_cfg.get("strategy_switch_after", 3)

    # 路径
    paths = config.get("paths", {})
    baseline_file = paths.get("baseline_file", ".perf/baseline.json")
    results_dir = paths.get("results_dir", ".perf/results")
    history_file = paths.get("history_file", ".perf/history.json")
    trajectory_file = paths.get("trajectory_file", ".perf/trajectory.jsonl")
    artifacts_dir = paths.get("artifacts_dir", ".perf/artifacts")

    # 当前分支
    base_branch, _ = git("rev-parse", "--abbrev-ref", "HEAD")
    start_time = time.time()

    # 确保目录存在
    os.makedirs(results_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)
    Path(trajectory_file).touch(exist_ok=True)

    print("=" * 60)
    print(f"  Performance Optimization Loop")
    print(f"  Base branch: {base_branch}")
    print(f"  Max rounds: {max_rounds}")
    print(f"  Max duration: {max_duration_min} min")
    print("=" * 60)

    if dry_run:
        print("\n[DRY-RUN] Would execute:")
        print(f"  1. Create branch perf/round-N")
        print(f"  2. Wait for AI to make changes")
        print(f"  3. Run collector")
        print(f"  4. Run judge.py against baseline")
        print(f"  5. Run history.py to update records")
        print(f"  6. PASS -> merge to {base_branch}")
        print(f"  7. FAIL -> discard branch, AI retries")
        print(f"  8. Repeat until exit condition met")
        return

    rounds_without_improvement = 0
    final_round = 0

    for round_num in range(1, max_rounds + 1):
        final_round = round_num
        elapsed_min = (time.time() - start_time) / 60

        print(f"\n{'─' * 60}")
        print(f"  Round {round_num} / {max_rounds}  ({elapsed_min:.0f} min elapsed)")
        print(f"{'─' * 60}")

        # --- 时间限制 ---
        if elapsed_min >= max_duration_min:
            print(f"  Time limit reached ({max_duration_min} min). Stopping.")
            break

        # --- 连续无改善 ---
        if rounds_without_improvement >= stop_after_no_improve:
            print(
                f"  No improvement for {rounds_without_improvement} rounds. Stopping."
            )
            break

        # --- 策略切换提示 ---
        if (
            rounds_without_improvement >= strategy_switch_after
            and rounds_without_improvement < stop_after_no_improve
        ):
            print(
                f"  WARNING: No improvement for {rounds_without_improvement} rounds."
            )
            print(f"  Consider switching optimization strategy.")

        # --- 1. 创建干净的特性分支 ---
        branch = f"perf/round-{round_num}"
        git("checkout", base_branch)
        git("checkout", "-b", branch)

        # --- 2. 等待 AI 完成修改 ---
        print(f"\n  Waiting for AI to complete changes...")
        print(f"  AI should:")
        print(f"    - Read {history_file} for context")
        print(f"    - Make optimizations (one commit per change)")
        print(f"    - Signal completion: touch .perf/ai_done")

        ai_done_marker = ".perf/ai_done"
        while not os.path.exists(ai_done_marker):
            time.sleep(5)

        os.remove(ai_done_marker)
        round_start = time.time()

        # --- 3. 采集性能数据 ---
        print(f"  Collecting performance data...")
        round_results = os.path.join(results_dir, f"round_{round_num}")
        os.makedirs(round_results, exist_ok=True)

        # 查找 collector
        collector_candidates = [
            script_dir / "collectors" / "web" / "collector.sh",
            script_dir / "collectors" / "unity" / "collector.sh",
            script_dir / "collector.sh",
        ]
        collector = None
        for c in collector_candidates:
            if c.exists():
                collector = c
                break

        if collector is None:
            print("  ERROR: No collector found.", file=sys.stderr)
            sys.exit(1)

        subprocess.run(
            ["bash", str(collector), config_path, round_results],
            check=True,
        )

        # --- 4. 判定 ---
        print(f"  Judging...")
        verdict_file = os.path.join(round_results, "verdict.json")
        judge_result = subprocess.run(
            [
                sys.executable,
                str(script_dir / "judge.py"),
                config_path,
                baseline_file,
                round_results,
                verdict_file,
            ],
        )

        round_duration = int(time.time() - round_start)

        # --- 5. 读取 commit 信息 ---
        description, _ = git("log", "-1", "--pretty=format:%s")
        expected, _ = git("log", "-1", "--pretty=format:%b")
        expected = expected.split("\n")[0] if expected else ""

        round_info = json.dumps(
            {
                "round": round_num,
                "description": description or f"round {round_num}",
                "expected": expected,
                "duration_sec": round_duration,
            }
        )

        # --- 6. 更新历史 ---
        subprocess.run(
            [
                sys.executable,
                str(script_dir / "history.py"),
                config_path,
                verdict_file,
                round_info,
                history_file,
                trajectory_file,
            ],
            check=True,
        )

        # --- 7. 根据判定行动 ---
        if judge_result.returncode == 0:
            print(f"  PASS -> Merging to {base_branch}")
            git("checkout", base_branch)
            git("merge", branch, "--no-ff", "-m", f"perf: merge round {round_num}")

            # 更新相对基准
            with open(baseline_file) as f:
                baseline = json.load(f)
            with open(verdict_file) as f:
                verdict = json.load(f)

            baseline["relative"]["commit"] = verdict["commit"]
            baseline["relative"]["updated_at"] = verdict["timestamp"]
            for name, detail in verdict["details"].items():
                baseline["relative"]["metrics"].setdefault(name, {})[
                    "value"
                ] = detail["measured"]

            with open(baseline_file, "w") as f:
                json.dump(baseline, f, indent=2)

            rounds_without_improvement = 0
            git("branch", "-d", branch)
        else:
            print(f"  FAIL -> Discarding branch {branch}")
            git("checkout", base_branch)
            git("branch", "-D", branch)
            rounds_without_improvement += 1

    # -----------------------------------------------------------------------
    # 最终报告
    # -----------------------------------------------------------------------
    total_min = (time.time() - start_time) / 60

    print(f"\n{'=' * 60}")
    print(f"  Loop Complete")
    print(f"  Rounds: {final_round}")
    print(f"  Duration: {total_min:.0f} min")
    print(f"  Trajectory: {trajectory_file}")
    print(f"{'=' * 60}")

    if os.path.exists(trajectory_file):
        entries = []
        with open(trajectory_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))

        passed = [e for e in entries if e["verdict"] == "PASS"]
        failed = [e for e in entries if e["verdict"] != "PASS"]

        print(f"  Passed: {len(passed)}")
        print(f"  Failed: {len(failed)}")
        if entries:
            print(f"  Pass rate: {len(passed)/len(entries)*100:.0f}%")
        if passed:
            print(f"  Merged improvements:")
            for p in passed:
                print(f"    Round {p['round']}: {p['plan']}")

    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
