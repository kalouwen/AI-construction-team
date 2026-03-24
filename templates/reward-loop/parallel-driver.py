#!/usr/bin/env python3
"""
parallel-driver.py — 多系统并行 Agent 驱动器

读取 systems.yaml，为每个独立系统启动一个 claude -p 子进程，
各自在隔离的工作目录中开发，然后按依赖顺序合并并运行集成测试。

用法:
  python parallel-driver.py <systems.yaml> --task "Implement feature X"
  python parallel-driver.py <systems.yaml> --task-file tasks.md [--dry-run]

依赖: pyyaml, git
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import yaml
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


SCRIPT_DIR = Path(__file__).parent


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def git(*args, cwd=None):
    r = subprocess.run(
        ["git"] + list(args),
        capture_output=True, text=True, cwd=cwd,
    )
    return r.stdout.strip(), r.returncode


def topo_sort(systems):
    """依赖感知的拓扑排序。无依赖的系统排前面。

    【P1 修复】确保依赖系统先合并。
    """
    name_map = {s["name"]: s for s in systems}
    visited = set()
    order = []

    def visit(name):
        if name in visited:
            return
        visited.add(name)
        sys_def = name_map.get(name)
        if sys_def:
            for dep in sys_def.get("depends_on", []):
                visit(dep)
        order.append(name)

    for s in systems:
        visit(s["name"])

    return [name_map[n] for n in order if n in name_map]


def check_cross_system_calls(systems, repo_root):
    """【P12 修复】预检：检测未声明的跨系统调用。"""
    warnings = []
    name_set = {s["name"] for s in systems}

    for sys_a in systems:
        a_name = sys_a["name"]
        a_dirs = sys_a.get("source_boundaries", [])

        for sys_b in systems:
            b_name = sys_b["name"]
            if a_name == b_name:
                continue
            if b_name in sys_a.get("depends_on", []):
                continue  # 已声明的依赖，跳过

            # 在 A 的代码中搜索 B 的包名/目录名
            for a_dir in a_dirs:
                a_path = os.path.join(repo_root, a_dir)
                if not os.path.isdir(a_path):
                    continue
                result = subprocess.run(
                    ["git", "grep", "-l", b_name, "--", a_dir],
                    capture_output=True, text=True, cwd=repo_root,
                )
                if result.returncode == 0 and result.stdout.strip():
                    files = result.stdout.strip().split("\n")
                    warnings.append({
                        "from": a_name,
                        "to": b_name,
                        "files": files[:3],
                        "message": (
                            f"System '{a_name}' references '{b_name}' "
                            f"but does not declare depends_on. "
                            f"Found in: {', '.join(files[:3])}"
                        ),
                    })

    return warnings


def create_isolation(system, base_branch, repo_root, method="clone"):
    """为 Agent 创建隔离的工作目录。

    【P11 修复】Windows 用 clone 避免 worktree 锁竞争。
    """
    branch = system["branch"]

    if method == "worktree":
        worktree_dir = os.path.join(
            repo_root, ".parallel-work", system["name"]
        )
        os.makedirs(os.path.dirname(worktree_dir), exist_ok=True)
        git("worktree", "add", worktree_dir, "-b", branch, cwd=repo_root)
        return worktree_dir
    else:
        # Full clone（Windows 默认）
        clone_dir = os.path.join(
            tempfile.gettempdir(), "parallel-build", system["name"]
        )
        if os.path.exists(clone_dir):
            shutil.rmtree(clone_dir, ignore_errors=True)
        _, rc = git("clone", "--local", "--branch", base_branch,
                     repo_root, clone_dir)
        if rc != 0:
            raise RuntimeError(f"git clone failed for {system['name']} → {clone_dir}")
        git("checkout", "-b", branch, cwd=clone_dir)
        return clone_dir


def cleanup_isolation(system, work_dir, repo_root, method="clone"):
    """清理隔离的工作目录。"""
    if method == "worktree":
        git("worktree", "remove", work_dir, "--force", cwd=repo_root)
    else:
        shutil.rmtree(work_dir, ignore_errors=True)


def build_agent_prompt(system, task_description, shared_zone):
    """为子 Agent 生成定制的 prompt。"""
    boundaries = "\n".join(f"  - {b}" for b in system.get("source_boundaries", []))
    frozen = "\n".join(f"  - {z}" for z in shared_zone)

    return f"""You are building the {system['name']} system: {system.get('description', '')}

## Task
{task_description}

## Boundaries (HARD CONSTRAINT)
You may ONLY modify files in:
{boundaries}

You may NOT touch:
{frozen}

## Verification
After EVERY change, run: {system['test_cmd']}
ALL tests must pass before you commit.

## Rules
1. NEVER ask questions — make judgment calls and document them
2. NEVER modify files outside your boundaries
3. Commit after each logical unit of work on branch: {system['branch']}
4. If stuck after 3 attempts, write diagnostic to docs/build-failures-{system['name']}.md
5. Write summary to docs/agent-report-{system['name']}.md when done
6. If you encounter a known error pattern, apply Self-Heal Protocol:
   read error → classify → check cycle → fix → verify ALL → record
"""


def run_agent(system, work_dir, prompt, timeout_min):
    """在隔离目录中启动一个 claude -p Agent。

    【P7 修复】每个 Agent 有独立超时。
    """
    start = time.time()
    log_path = os.path.join(work_dir, f"agent-output-{system['name']}.log")

    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            result = subprocess.run(
                [
                    "claude",
                    "-p", prompt,
                    "--allowedTools", "Bash,Read,Edit,Write",
                    "--max-turns", "15",
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                timeout=timeout_min * 60,
                cwd=work_dir,
            )
        status = "SUCCESS" if result.returncode == 0 else "FAILED"
    except subprocess.TimeoutExpired:
        status = "TIMEOUT"

    duration = int(time.time() - start)

    # 读取 Agent 报告（如果写了）
    report = ""
    report_path = os.path.join(work_dir, "docs", f"agent-report-{system['name']}.md")
    if os.path.exists(report_path):
        with open(report_path, encoding="utf-8") as f:
            report = f.read()

    # 统计测试结果
    test_output, test_rc = git("log", "--oneline", "-5", cwd=work_dir)

    return {
        "system": system["name"],
        "branch": system["branch"],
        "status": status,
        "duration_sec": duration,
        "work_dir": work_dir,
        "report": report,
        "commits": test_output,
    }


def merge_agent(system, result, base_branch, repo_root, coord_cfg):
    """将一个 Agent 的分支合并到 base，运行集成测试。

    【P2/P9 修复】每次合并后跑全量集成测试。
    【P3/P4 修复】合并后运行 post_merge_commands。
    """
    branch = system["branch"]
    work_dir = result["work_dir"]
    method = coord_cfg.get("isolation_method", "clone")

    # 从隔离目录 fetch 分支到主仓库
    if method == "clone":
        git("fetch", work_dir, f"{branch}:{branch}", cwd=repo_root)
    # worktree 的分支已经在主仓库中

    # 记录合并前的 SHA（用于 INTEGRATION_FAIL 时精确回滚）
    pre_merge_sha, _ = git("rev-parse", "HEAD", cwd=repo_root)

    # 合并
    merge_output, merge_rc = git(
        "merge", branch, "--no-ff",
        "-m", f"parallel: merge {system['name']} from {branch}",
        cwd=repo_root,
    )

    if merge_rc != 0:
        return {
            "system": system["name"],
            "merge_status": "CONFLICT",
            "detail": merge_output,
            "pre_merge_sha": pre_merge_sha,
        }

    # 运行 post_merge_commands（codegen 等）
    for cmd in coord_cfg.get("post_merge_commands", []):
        print(f"    Running post-merge: {cmd}")
        subprocess.run(cmd, shell=True, cwd=repo_root)

    # 【P2 修复】全量集成测试
    integration_cmd = coord_cfg.get("integration_test", "")
    if integration_cmd:
        print(f"    Integration test: {integration_cmd}")
        test_result = subprocess.run(
            integration_cmd, shell=True, capture_output=True,
            text=True, cwd=repo_root, timeout=600,
        )
        if test_result.returncode != 0:
            return {
                "system": system["name"],
                "merge_status": "INTEGRATION_FAIL",
                "detail": test_result.stdout + test_result.stderr,
                "pre_merge_sha": pre_merge_sha,
            }

    # 成功：提交 codegen 变更（如果有）
    git("add", "-A", cwd=repo_root)
    changed, _ = git("diff", "--cached", "--name-only", cwd=repo_root)
    if changed.strip():
        git("commit", "-m",
            f"parallel: post-merge fixup for {system['name']}",
            cwd=repo_root)

    return {
        "system": system["name"],
        "merge_status": "MERGED",
        "detail": "",
    }


def generate_report(results, merge_results, start_time, output_path):
    """生成并行构建报告。"""
    total_min = (time.time() - start_time) / 60

    succeeded = [r for r in results if r["status"] == "SUCCESS"]
    failed = [r for r in results if r["status"] == "FAILED"]
    timeout = [r for r in results if r["status"] == "TIMEOUT"]
    merged = [m for m in merge_results if m["merge_status"] == "MERGED"]

    lines = [
        "# Parallel Build Report",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "",
        "## Summary",
        f"- Systems: {len(results)} | Succeeded: {len(succeeded)} "
        f"| Failed: {len(failed)} | Timeout: {len(timeout)}",
        f"- Merged: {len(merged)} / {len(succeeded)}",
        f"- Duration: {total_min:.0f} min total",
        "",
        "## Per-Agent Results",
        "| System | Agent Status | Duration | Merge Status |",
        "|--------|-------------|----------|--------------|",
    ]

    merge_map = {m["system"]: m for m in merge_results}
    for r in results:
        m = merge_map.get(r["system"], {})
        ms = m.get("merge_status", "—")
        lines.append(
            f"| {r['system']} | {r['status']} "
            f"| {r['duration_sec']}s | {ms} |"
        )

    # 失败详情
    conflicts = [m for m in merge_results if m["merge_status"] != "MERGED"]
    if conflicts:
        lines.append("")
        lines.append("## Integration Issues")
        for c in conflicts:
            lines.append(f"### {c['system']}: {c['merge_status']}")
            lines.append(f"```\n{c['detail'][:500]}\n```")
            lines.append("")

    lines.append("")
    lines.append("---")
    lines.append("*Generated by parallel-driver.py*")

    report = "\n".join(lines)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    return report


def main():
    if len(sys.argv) < 2:
        print(
            "用法:\n"
            "  python parallel-driver.py <systems.yaml> --task \"...\"\n"
            "  python parallel-driver.py <systems.yaml> --task-file tasks.md\n"
            "  python parallel-driver.py <systems.yaml> --dry-run"
        )
        sys.exit(1)

    config_path = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    # 读取任务描述
    task = ""
    if "--task" in sys.argv:
        idx = sys.argv.index("--task")
        if idx + 1 < len(sys.argv):
            task = sys.argv[idx + 1]
    elif "--task-file" in sys.argv:
        idx = sys.argv.index("--task-file")
        if idx + 1 < len(sys.argv):
            with open(sys.argv[idx + 1], encoding="utf-8") as f:
                task = f.read()

    config = load_yaml(config_path)
    systems = config.get("systems", [])
    coord_cfg = config.get("coordination", {})
    preflight_cfg = config.get("preflight", {})

    repo_root = os.getcwd()
    base_branch, _ = git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo_root)

    shared_zone = coord_cfg.get("shared_zone", [])
    isolation_method = coord_cfg.get("isolation_method", "clone")
    max_concurrent = coord_cfg.get("max_concurrent", 4)
    global_timeout = coord_cfg.get("global_timeout_min", 45)
    partial_failure = coord_cfg.get("partial_failure", "merge_successes")

    # 拓扑排序
    sorted_systems = topo_sort(systems)

    print("=" * 60)
    print("  Parallel Build Driver")
    print(f"  Systems: {', '.join(s['name'] for s in sorted_systems)}")
    print(f"  Merge order: {' → '.join(s['name'] for s in sorted_systems)}")
    print(f"  Isolation: {isolation_method}")
    print(f"  Max concurrent: {max_concurrent}")
    print(f"  Base: {base_branch}")
    print("=" * 60)

    # ─── Preflight ───
    if preflight_cfg.get("check_cross_system_calls", True):
        print("\n  [Preflight] Checking cross-system calls...")
        warnings = check_cross_system_calls(systems, repo_root)
        for w in warnings:
            print(f"    ⚠ {w['message']}")
        if warnings:
            print(f"    Found {len(warnings)} undeclared cross-system dependencies.")

    if preflight_cfg.get("check_branch_exists", True):
        print("\n  [Preflight] Checking for existing branches...")
        for s in sorted_systems:
            _, rc = git("rev-parse", "--verify", s["branch"], cwd=repo_root)
            if rc == 0:
                print(f"    Branch {s['branch']} already exists. Deleting stale branch.")
                git("branch", "-D", s["branch"], cwd=repo_root)

    if preflight_cfg.get("check_baseline_compiles", True):
        integration_cmd = coord_cfg.get("integration_test", "")
        if integration_cmd:
            print(f"\n  [Preflight] Baseline check: {integration_cmd}")
            r = subprocess.run(
                integration_cmd, shell=True, capture_output=True,
                text=True, cwd=repo_root, timeout=600,
            )
            if r.returncode != 0:
                print("    FAIL — baseline doesn't compile. Fix before parallel build.")
                sys.exit(1)
            print("    PASS")

    if dry_run:
        print("\n[DRY-RUN] Would spawn agents:")
        for s in sorted_systems:
            print(f"  - {s['name']} → branch {s['branch']}, "
                  f"test: {s['test_cmd']}, timeout: {s.get('timeout_min', 30)}min")
        print(f"\n  Merge order: {' → '.join(s['name'] for s in sorted_systems)}")
        print(f"  Post-merge: {coord_cfg.get('post_merge_commands', [])}")
        print(f"  Integration: {coord_cfg.get('integration_test', 'none')}")
        return

    start_time = time.time()

    # ─── Phase 2: Spawn ───
    print(f"\n  Spawning {len(sorted_systems)} agents "
          f"(max {max_concurrent} concurrent)...")

    work_dirs = {}
    failed_isolation = []
    for s in sorted_systems:
        print(f"    Creating isolation for {s['name']}...")
        try:
            work_dir = create_isolation(s, base_branch, repo_root, isolation_method)
            work_dirs[s["name"]] = work_dir
            print(f"    → {work_dir}")
        except (RuntimeError, OSError) as e:
            print(f"    FAILED: {e}")
            failed_isolation.append(s["name"])

    # 移除隔离失败的系统
    sorted_systems = [s for s in sorted_systems if s["name"] not in failed_isolation]
    if not sorted_systems:
        print("  All isolation setup failed. Aborting.")
        sys.exit(1)

    # 并行启动 Agent
    results = []
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = {}
        for s in sorted_systems:
            prompt = build_agent_prompt(s, task, shared_zone)
            future = executor.submit(
                run_agent, s, work_dirs[s["name"]],
                prompt, s.get("timeout_min", 30),
            )
            futures[future] = s

        # 【P7 修复】全局超时
        deadline = time.time() + global_timeout * 60
        for future in as_completed(futures, timeout=global_timeout * 60):
            s = futures[future]
            try:
                result = future.result(timeout=max(0, deadline - time.time()))
                print(f"    [{result['system']}] {result['status']} "
                      f"({result['duration_sec']}s)")
                results.append(result)
            except Exception as e:
                print(f"    [{s['name']}] ERROR: {e}")
                results.append({
                    "system": s["name"],
                    "branch": s["branch"],
                    "status": "ERROR",
                    "duration_sec": 0,
                    "work_dir": work_dirs[s["name"]],
                    "report": "",
                    "commits": "",
                })

    # ─── Phase 4: Merge ───
    successful = [r for r in results if r["status"] == "SUCCESS"]
    failed_agents = [r for r in results if r["status"] != "SUCCESS"]

    print(f"\n  Agent results: {len(successful)} success, "
          f"{len(failed_agents)} failed/timeout")

    if not successful:
        print("  No successful agents. Nothing to merge.")
    else:
        if partial_failure == "abort_all" and failed_agents:
            print("  Policy: abort_all — some agents failed, aborting.")
        else:
            # 按拓扑序合并成功的 Agent
            merge_order = [s for s in sorted_systems
                           if any(r["system"] == s["name"] for r in successful)]

            print(f"\n  Merging {len(merge_order)} agents in order: "
                  f"{' → '.join(s['name'] for s in merge_order)}")

            merge_results = []
            for s in merge_order:
                result = next(r for r in successful if r["system"] == s["name"])
                print(f"\n    Merging {s['name']}...")
                m = merge_agent(s, result, base_branch, repo_root, coord_cfg)
                merge_results.append(m)
                print(f"    → {m['merge_status']}")

                if m["merge_status"] == "CONFLICT":
                    # 文本冲突：merge 未完成，abort 正确
                    print(f"    Rolling back {s['name']} merge (conflict)...")
                    git("merge", "--abort", cwd=repo_root)
                elif m["merge_status"] == "INTEGRATION_FAIL":
                    # merge 已完成但集成测试失败：回滚到合并前的精确 SHA
                    # （可能有 post_merge_commands 产生的额外 commit，HEAD~1 不够）
                    pre_sha = m.get("pre_merge_sha", "")
                    if pre_sha:
                        print(f"    Rolling back {s['name']} to {pre_sha[:7]}...")
                        git("reset", "--hard", pre_sha, cwd=repo_root)
                    else:
                        print(f"    Rolling back {s['name']} (fallback HEAD~1)...")
                        git("reset", "--hard", "HEAD~1", cwd=repo_root)
                # 继续合并下一个

            # ─── Phase 5: Retry failed ───
            retry_cfg = coord_cfg.get("retry_strategy", "abandon")
            max_retries = coord_cfg.get("max_retries", 0)

            if retry_cfg == "rebase_retry" and max_retries > 0 and failed_agents:
                print(f"\n  Retrying {len(failed_agents)} failed agents "
                      f"from new base...")
                # 【P6 修复】从新 base（包含已合并的成功分支）开始重试
                for r in failed_agents:
                    s = next(
                        sys_def for sys_def in sorted_systems
                        if sys_def["name"] == r["system"]
                    )
                    print(f"    Retrying {s['name']} from current base...")
                    # 清理旧隔离
                    cleanup_isolation(s, r["work_dir"], repo_root, isolation_method)
                    # 创建新隔离（从当前 base，包含已合并的内容）
                    new_work_dir = create_isolation(
                        s, base_branch, repo_root, isolation_method
                    )
                    prompt = build_agent_prompt(s, task, shared_zone)
                    retry_result = run_agent(
                        s, new_work_dir, prompt, s.get("timeout_min", 30)
                    )
                    print(f"    [{retry_result['system']}] Retry: "
                          f"{retry_result['status']}")
                    if retry_result["status"] == "SUCCESS":
                        m = merge_agent(
                            s, retry_result, base_branch, repo_root, coord_cfg
                        )
                        merge_results.append(m)
                    cleanup_isolation(s, new_work_dir, repo_root, isolation_method)

            # ─── Phase 6: Report ───
            report_path = os.path.join(repo_root, "docs", "merge-report.md")
            report = generate_report(results, merge_results, start_time, report_path)
            print(f"\n  Report: {report_path}")

    # 清理隔离目录
    for s in sorted_systems:
        work_dir = work_dirs.get(s["name"])
        if work_dir and os.path.exists(work_dir):
            cleanup_isolation(s, work_dir, repo_root, isolation_method)

    total_min = (time.time() - start_time) / 60
    print(f"\n{'=' * 60}")
    print(f"  Parallel Build Complete — {total_min:.0f} min")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
