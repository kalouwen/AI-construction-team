#!/usr/bin/env python3
"""
guardrail.py — 变更护栏

在 AI 改完代码、判定之前运行。检查三件事：
  1. 冻结边界：AI 是否碰了不该碰的文件
  2. 变更审计：diff 大小/范围是否合理
  3. Reward hacking 检测：是否有作弊模式（删测试、关功能等）

用法: python guardrail.py <config> [--base-ref HEAD~1]
  config   — guardrail.yaml 或 signals.yaml 路径
  base-ref — 对比基准（默认 HEAD~1）

exit code: 0=通过, 1=违规
"""

import json
import os
import re
import subprocess
import sys
import yaml
from pathlib import Path


def git(*args):
    r = subprocess.run(["git"] + list(args), capture_output=True, text=True)
    return r.stdout.strip(), r.returncode


def load_config(path):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("guardrail", data)


def _get_task_type(signals_dir):
    """从 prompt_meta.json 读取 task_type（如 rename/refactor/feature/bugfix）。"""
    meta_path = os.path.join(signals_dir, "prompt_meta.json")
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        return meta.get("task_type")
    except (json.JSONDecodeError, OSError):
        return None


# =========================================================================
# 0. 文件级白名单检查（从 prompt_meta.json 的 target_files 读取）
#    这是原子化的结构性保证：每轮只允许改指定文件，等同 autoresearch 的 immutable
# =========================================================================
def check_target_files_allowlist(changed_files, signals_dir):
    """
    如果 prompt_meta.json 里有 target_files，则执行白名单检查。
    changed_files 里出现 target_files 以外的文件 → BLOCK。
    target_files 为空列表时跳过（不限制）。
    """
    meta_path = os.path.join(signals_dir, "prompt_meta.json")
    if not os.path.exists(meta_path):
        return []

    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    target_files = meta.get("target_files", [])
    if not target_files:
        return []  # 没有指定目标文件，不做白名单限制

    violations = []
    for changed in changed_files:
        # 检查是否在白名单里（支持部分路径匹配）
        allowed = any(
            changed == tf or changed.endswith(tf) or tf.endswith(changed)
            for tf in target_files
        )
        if not allowed:
            violations.append({
                "file": changed,
                "rule": f"not in target_files allowlist: {target_files}",
                "hypothesis": meta.get("hypothesis", ""),
            })

    return violations


# =========================================================================
# 1. 冻结边界检查
# =========================================================================
def check_frozen_boundaries(changed_files, frozen_patterns):
    """检查是否修改了冻结区的文件（大小写不敏感，兼容 Unity/Windows）。"""
    violations = []

    for f in changed_files:
        f_lower = f.lower()
        for pattern in frozen_patterns:
            p_lower = pattern.lower()
            # 支持 glob 风格匹配
            if pattern.endswith("/"):
                # 目录前缀匹配
                if f_lower.startswith(p_lower) or f_lower.startswith(p_lower.rstrip("/")):
                    violations.append({"file": f, "rule": f"frozen directory: {pattern}"})
            elif "*" in pattern:
                # 简单 glob
                regex = pattern.replace(".", r"\.").replace("*", ".*")
                if re.match(regex, f, re.IGNORECASE):
                    violations.append({"file": f, "rule": f"frozen pattern: {pattern}"})
            else:
                # 精确匹配
                if f_lower == p_lower or f_lower.endswith("/" + p_lower):
                    violations.append({"file": f, "rule": f"frozen file: {pattern}"})

    return violations


# =========================================================================
# 2. 变更审计
# =========================================================================
def audit_changes(diff_stat, limits):
    """检查变更规模是否在合理范围内。"""
    warnings = []

    max_files = limits.get("max_files_changed", 5)
    max_insertions = limits.get("max_insertions", 100)
    max_deletions = limits.get("max_deletions", 80)
    warn_files = limits.get("warn_files", 3)
    warn_insertions = limits.get("warn_insertions", 60)

    files_changed = diff_stat.get("files_changed", 0)
    insertions = diff_stat.get("insertions", 0)
    deletions = diff_stat.get("deletions", 0)

    # 警告档（超过 warn 阈值但未超过 max）
    if warn_files <= files_changed <= max_files:
        warnings.append({
            "type": "many_files_warn",
            "message": f"Changed {files_changed} files (warn threshold: {warn_files}). Consider splitting.",
            "severity": "low",
        })

    if warn_insertions <= insertions <= max_insertions:
        warnings.append({
            "type": "many_insertions_warn",
            "message": f"{insertions} lines added (warn threshold: {warn_insertions}). Consider splitting.",
            "severity": "low",
        })

    # 阻断档（超过 max 阈值）
    if files_changed > max_files:
        warnings.append({
            "type": "too_many_files",
            "message": f"Changed {files_changed} files (limit: {max_files}). This is not atomic.",
            "severity": "high",
        })

    if insertions > max_insertions:
        warnings.append({
            "type": "too_many_insertions",
            "message": f"{insertions} lines added (limit: {max_insertions}). This is not atomic.",
            "severity": "medium",
        })

    if deletions > max_deletions:
        warnings.append({
            "type": "too_many_deletions",
            "message": f"{deletions} lines deleted (limit: {max_deletions}). This is not atomic.",
            "severity": "medium",
        })

    # 删除远大于新增 = 可疑（可能在删功能/测试）
    if deletions > 0 and insertions > 0:
        ratio = deletions / insertions
        if ratio > 3:
            warnings.append({
                "type": "suspicious_deletion_ratio",
                "message": f"Deletion/insertion ratio: {ratio:.1f}x (deleting much more than adding)",
                "severity": "high",
            })

    return warnings


def get_diff_stat(base_ref):
    """获取 diff 统计。"""
    stat_output, code = git("diff", "--stat", base_ref)
    if code != 0:
        return {"files_changed": 0, "insertions": 0, "deletions": 0}

    # 解析最后一行: "3 files changed, 10 insertions(+), 5 deletions(-)"
    numstat_output, _ = git("diff", "--numstat", base_ref)
    files_changed = 0
    insertions = 0
    deletions = 0

    for line in numstat_output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            files_changed += 1
            try:
                insertions += int(parts[0]) if parts[0] != "-" else 0
                deletions += int(parts[1]) if parts[1] != "-" else 0
            except ValueError:
                pass

    return {
        "files_changed": files_changed,
        "insertions": insertions,
        "deletions": deletions,
    }


# =========================================================================
# 3. Reward hacking 检测
# =========================================================================
def detect_reward_hacking(diff_content, patterns):
    """扫描 diff 内容，检测作弊模式。"""
    detections = []

    for pattern_cfg in patterns:
        name = pattern_cfg["name"]
        regex = pattern_cfg["pattern"]
        severity = pattern_cfg.get("severity", "high")
        description = pattern_cfg.get("description", "")

        matches = re.findall(regex, diff_content, re.MULTILINE | re.IGNORECASE)
        if matches:
            detections.append({
                "name": name,
                "severity": severity,
                "description": description,
                "matches": len(matches),
                "sample": matches[0][:200] if matches else "",
            })

    return detections


DEFAULT_HACKING_PATTERNS = [
    {
        "name": "test_deletion",
        "pattern": r"^-\s*(def test_|it\(|describe\(|test\(|\.test\.)",
        "severity": "critical",
        "description": "Deleting test definitions instead of fixing code",
    },
    {
        "name": "test_skip",
        "pattern": r"^\+.*(@pytest\.mark\.skip|\.skip\(|xit\(|xdescribe\(|pending\()",
        "severity": "high",
        "description": "Skipping tests instead of fixing them",
    },
    {
        "name": "assertion_weakening",
        "pattern": r"^\+.*(assert True|expect\(true\)|\.toBeTruthy\(\))\s*$",
        "severity": "high",
        "description": "Replacing real assertions with always-true",
    },
    {
        "name": "console_disable",
        "pattern": r"^\+.*(console\.(log|warn|error)\s*=|jest\.spyOn.*console)",
        "severity": "medium",
        "description": "Suppressing console output (hiding errors)",
    },
    {
        "name": "render_disable",
        "pattern": r"^\+.*(visible\s*[:=]\s*false|display\s*[:=]\s*['\"]?none|opacity\s*[:=]\s*0[^.])",
        "severity": "high",
        "description": "Hiding visual elements (FPS gaming by not rendering)",
    },
    {
        "name": "timeout_increase",
        "pattern": r"^\+.*(timeout|TIMEOUT|waitFor).*[5-9]\d{4,}",
        "severity": "medium",
        "description": "Large timeout increase (hiding performance issues)",
    },
    {
        "name": "eval_modification",
        "pattern": r"^\+.*(scorecard|evaluation|criterion|pass_threshold|score\s*[:=])",
        "severity": "critical",
        "description": "Modifying scoring/evaluation logic",
    },
    {
        "name": "baseline_modification",
        "pattern": r"^\+.*(baseline|benchmark|threshold).*[:=]",
        "severity": "high",
        "description": "Modifying baselines or thresholds",
    },
]


# =========================================================================
# 主流程
# =========================================================================
def main():
    if len(sys.argv) < 2:
        print("用法: python guardrail.py <config> [--base-ref HEAD~1]")
        sys.exit(1)

    config_path = sys.argv[1]
    base_ref = "HEAD~1"
    if "--base-ref" in sys.argv:
        idx = sys.argv.index("--base-ref")
        if idx + 1 < len(sys.argv):
            base_ref = sys.argv[idx + 1]

    config = load_config(config_path)

    # 默认配置
    frozen_patterns = config.get("frozen", [
        "scripts/reward/",
        ".signals/",
        "*.test.*",
        "*.spec.*",
        "**/test/**",
        "**/tests/**",
        "baseline.json",
        "signals.yaml",
        "perf.yaml",
        "test.yaml",
    ])

    limits = config.get("limits", {
        "max_files_changed": 3,
        "max_insertions": 100,
        "max_deletions": 80,
        "warn_files": 2,
        "warn_insertions": 60,
    })

    # task_type 分层：从 prompt_meta.json 读取任务类型，覆盖默认限制
    signals_dir = os.path.dirname(config_path)
    task_type = _get_task_type(signals_dir)
    if task_type:
        overrides = config.get("task_type_overrides", {}).get(task_type, {})
        if overrides:
            limits = {**limits, **overrides}
            print(f"  Task type: {task_type} — limits overridden: {overrides}")

    hacking_patterns = config.get("hacking_patterns", DEFAULT_HACKING_PATTERNS)

    # --- 获取变更信息 ---
    changed_output, _ = git("diff", "--name-only", base_ref)
    changed_files = [f for f in changed_output.splitlines() if f.strip()]

    if not changed_files:
        print("  No changes detected. Guardrail: PASS")
        sys.exit(0)

    diff_stat = get_diff_stat(base_ref)
    diff_content, _ = git("diff", base_ref)

    # --- 运行检查 ---
    print(f"{'=' * 60}")
    print(f"  Guardrail Check")
    print(f"  Files changed: {diff_stat['files_changed']}")
    print(f"  +{diff_stat['insertions']} / -{diff_stat['deletions']} lines")
    print(f"{'=' * 60}")

    all_issues = []

    # 0. 文件级白名单（target_files allowlist — 原子化的结构性保证）
    signals_dir = os.path.dirname(config_path)
    allowlist_violations = check_target_files_allowlist(changed_files, signals_dir)
    if allowlist_violations:
        print(f"\n  TARGET FILES ALLOWLIST VIOLATIONS ({len(allowlist_violations)}):")
        for v in allowlist_violations:
            print(f"    [BLOCK] {v['file']} — {v['rule']}")
            if v.get("hypothesis"):
                print(f"           Hypothesis was: {v['hypothesis']}")
        all_issues.extend([{"severity": "critical", **v} for v in allowlist_violations])

    # 1. 冻结边界
    frozen_violations = check_frozen_boundaries(changed_files, frozen_patterns)
    if frozen_violations:
        print(f"\n  FROZEN BOUNDARY VIOLATIONS ({len(frozen_violations)}):")
        for v in frozen_violations:
            print(f"    [BLOCK] {v['file']} — {v['rule']}")
        all_issues.extend([{"severity": "critical", **v} for v in frozen_violations])

    # 2. 变更审计
    audit_warnings = audit_changes(diff_stat, limits)
    if audit_warnings:
        print(f"\n  CHANGE AUDIT WARNINGS ({len(audit_warnings)}):")
        for w in audit_warnings:
            print(f"    [{w['severity'].upper()}] {w['message']}")
        all_issues.extend(audit_warnings)

    # 3. Reward hacking
    hacking_detections = detect_reward_hacking(diff_content, hacking_patterns)
    if hacking_detections:
        print(f"\n  REWARD HACKING DETECTIONS ({len(hacking_detections)}):")
        for d in hacking_detections:
            print(f"    [{d['severity'].upper()}] {d['name']}: {d['description']}")
            if d.get("sample"):
                print(f"      sample: {d['sample'][:100]}")
        all_issues.extend(hacking_detections)

    # --- 判定 ---
    critical = [i for i in all_issues if i.get("severity") == "critical"]
    high = [i for i in all_issues if i.get("severity") == "high"]

    if critical:
        verdict = "BLOCK"
        summary = f"{len(critical)} critical issue(s) — changes must be rejected"
    elif high:
        verdict = "WARN"
        summary = f"{len(high)} high-severity warning(s) — review recommended"
    elif all_issues:
        verdict = "INFO"
        summary = f"{len(all_issues)} minor issue(s)"
    else:
        verdict = "PASS"
        summary = "All checks passed"

    print(f"\n{'=' * 60}")
    print(f"  GUARDRAIL: {verdict}")
    print(f"  {summary}")
    print(f"{'=' * 60}")

    # 输出 JSON（供编排器读取）
    result = {
        "verdict": verdict,
        "summary": summary,
        "diff_stat": diff_stat,
        "frozen_violations": frozen_violations,
        "audit_warnings": audit_warnings,
        "hacking_detections": hacking_detections,
    }

    # 写到 stdout 的下一行（编排器可以解析）
    print(f"\n__GUARDRAIL_JSON__:{json.dumps(result)}")

    # BLOCK = exit 1, WARN = exit 0（但编排器可以选择拒绝）
    sys.exit(1 if verdict == "BLOCK" else 0)


if __name__ == "__main__":
    main()
