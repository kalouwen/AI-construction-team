#!/usr/bin/env python3
"""
preflight.py — 摩擦感知预检验证

在任何实现开始之前运行，检查项目一致性，消除可预防的摩擦源。
从 50 次实战会话的经验教训中提炼：buggy code(45次)、方向错误(38次)、
误解需求(16次)——80% 可通过预检预防。

5 项检查：
  1. Proto/codegen 一致性
  2. 枚举同步
  3. 受保护目录确认
  4. 已有实现审计
  5. 构建基线记录

用法:
  python preflight.py <project_dir> [--config preflight.yaml]
  python preflight.py <project_dir> --scope vehicle,clothing  （并行 Agent 限定范围）
  python preflight.py <project_dir> --fix                      （自动修复可修项）

输出: docs/session-baseline.md + preflight-report.json
exit: 0=全部通过, 1=有可修项, 2=有阻塞项
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path


def load_config(config_path):
    """加载预检配置。无配置文件时使用默认值。"""
    if config_path and os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    # 默认配置：只启用通用检查
    return {
        "checks": {
            "proto_consistency": {"enabled": False},
            "enum_sync": {"enabled": False},
            "protected_dirs": {"enabled": True},
            "existing_code_audit": {"enabled": True},
            "build_baseline": {"enabled": True},
        },
        "settings": {
            "auto_fix": True,
            "max_fix_loops": 3,
            "check_timeout_sec": 300,
        },
    }


def git(*args, cwd=None):
    r = subprocess.run(
        ["git"] + list(args), capture_output=True, text=True, cwd=cwd
    )
    return r.stdout.strip(), r.returncode


# ═══════════════════════════════════════════════════════════════
# Check 1: Proto/Codegen 一致性
# ═══════════════════════════════════════════════════════════════
def check_proto_consistency(cfg, project_dir):
    """检查 proto 文件与生成代码的一致性。

    【P1 修复】用内容 hash 而非时间戳判断一致性。
    【P3 修复】跳过标记为 HAND-WRITTEN 的文件。
    """
    results = []
    proto_dirs = cfg.get("proto_dirs", [])
    targets = cfg.get("targets", {})
    marker = cfg.get("hand_written_marker", "// HAND-WRITTEN")

    for proto_dir in proto_dirs:
        full_dir = os.path.join(project_dir, proto_dir)
        if not os.path.isdir(full_dir):
            results.append({
                "name": f"Proto dir: {proto_dir}",
                "status": "SKIP",
                "detail": "Directory not found",
            })
            continue

        for proto_file in Path(full_dir).glob("*.proto"):
            # Hash proto 内容
            proto_content = proto_file.read_text(encoding="utf-8", errors="replace")
            proto_hash = hashlib.sha256(proto_content.encode()).hexdigest()[:12]

            for lang, out_dir in targets.items():
                out_path = os.path.join(project_dir, out_dir)
                if not os.path.isdir(out_path):
                    results.append({
                        "name": f"{proto_file.name} → {lang}",
                        "status": "WARN",
                        "detail": f"Output dir missing: {out_dir}",
                        "fixable": True,
                        "fix_cmd": cfg.get("codegen_cmd", ""),
                    })
                    continue

                # 查找对应的生成文件
                stem = proto_file.stem
                expected_patterns = {
                    "go": [f"{stem}.pb.go", f"{stem}_pb.go"],
                    "csharp": [f"{stem}.cs", f"{stem}Grpc.cs"],
                }
                patterns = expected_patterns.get(lang, [f"{stem}.*"])

                found = False
                found_hand_written = False
                for pattern in patterns:
                    matches = list(Path(out_path).rglob(pattern))
                    for match in matches:
                        content = match.read_text(encoding="utf-8", errors="replace")
                        # 【P3】手写文件单独标记，不算"未找到"
                        if marker in content:
                            found_hand_written = True
                            continue
                        found = True

                        if proto_hash in content:
                            results.append({
                                "name": f"{proto_file.name} → {lang}",
                                "status": "PASS",
                                "detail": f"Hash match: {proto_hash}",
                            })
                        else:
                            results.append({
                                "name": f"{proto_file.name} → {lang}",
                                "status": "WARN",
                                "detail": (
                                    f"File exists but hash not found "
                                    f"(may be stale, proto hash: {proto_hash})"
                                ),
                                "fixable": True,
                                "fix_cmd": cfg.get("codegen_cmd", ""),
                            })

                if not found and found_hand_written:
                    # 只有手写文件覆盖，不算缺失
                    results.append({
                        "name": f"{proto_file.name} → {lang}",
                        "status": "PASS",
                        "detail": "Covered by hand-written file",
                    })
                elif not found:
                    results.append({
                        "name": f"{proto_file.name} → {lang}",
                        "status": "FAIL",
                        "detail": f"No generated file found in {out_dir}",
                        "fixable": True,
                        "fix_cmd": cfg.get("codegen_cmd", ""),
                    })

    return results


# ═══════════════════════════════════════════════════════════════
# Check 2: 枚举同步
# ═══════════════════════════════════════════════════════════════
def check_enum_sync(cfg, project_dir):
    """检查跨语言枚举值一致性。

    【P4 修复】归一化命名后比较（去前缀、转小写）。
    【P5 修复】allow_subset 支持客户端是服务端子集。
    """
    results = []
    endpoints = cfg.get("endpoints", [])
    allow_subset = cfg.get("allow_subset", True)

    if len(endpoints) < 2:
        return [{"name": "Enum sync", "status": "SKIP",
                 "detail": "Need at least 2 endpoints to compare"}]

    # 收集每个端点的枚举值
    endpoint_enums = {}
    for ep in endpoints:
        name = ep["name"]
        glob_pattern = ep["glob"]
        pattern = ep.get("pattern", r"(\w+)\s*=\s*(\d+)")
        enums = {}

        for f in Path(project_dir).glob(glob_pattern):
            content = f.read_text(encoding="utf-8", errors="replace")
            matches = re.findall(pattern, content)
            for enum_name, enum_val in matches:
                # 归一化：去掉常见前缀，转小写
                normalized = re.sub(
                    r'^(k|e|E|Type_|Category_)', '', enum_name
                ).lower().replace('_', '')
                enums[normalized] = {
                    "original": enum_name,
                    "value": int(enum_val),
                    "file": str(f.relative_to(project_dir)),
                }
        endpoint_enums[name] = enums

    # 两两比较
    ep_names = list(endpoint_enums.keys())
    for i in range(len(ep_names)):
        for j in range(i + 1, len(ep_names)):
            a_name, b_name = ep_names[i], ep_names[j]
            a_enums, b_enums = endpoint_enums[a_name], endpoint_enums[b_name]

            all_keys = set(a_enums.keys()) | set(b_enums.keys())
            mismatches = []
            missing_in_a = []
            missing_in_b = []

            for key in sorted(all_keys):
                in_a = key in a_enums
                in_b = key in b_enums

                if in_a and in_b:
                    if a_enums[key]["value"] != b_enums[key]["value"]:
                        mismatches.append(
                            f"{a_enums[key]['original']}={a_enums[key]['value']} "
                            f"vs {b_enums[key]['original']}={b_enums[key]['value']}"
                        )
                elif in_a and not in_b:
                    missing_in_b.append(a_enums[key]["original"])
                elif in_b and not in_a:
                    missing_in_a.append(b_enums[key]["original"])

            if mismatches:
                results.append({
                    "name": f"Enum values: {a_name} vs {b_name}",
                    "status": "FAIL",
                    "detail": f"Value mismatch: {'; '.join(mismatches[:3])}",
                })
            elif missing_in_b and not allow_subset:
                results.append({
                    "name": f"Enum coverage: {a_name} → {b_name}",
                    "status": "WARN",
                    "detail": f"{b_name} missing: {', '.join(missing_in_b[:5])}",
                })
            else:
                results.append({
                    "name": f"Enum sync: {a_name} ↔ {b_name}",
                    "status": "PASS",
                    "detail": f"{len(all_keys)} values checked",
                })

    return results


# ═══════════════════════════════════════════════════════════════
# Check 3: 受保护目录
# ═══════════════════════════════════════════════════════════════
def check_protected_dirs(cfg, project_dir):
    """确认受保护目录被正确标记。

    【P7 修复】从 guard-patterns.conf 读取，不硬编码。
    【P8 修复】自动检测 .gitmodules。
    """
    results = []
    protected = set()

    # 从 guard-patterns.conf 读取
    conf_candidates = [
        os.path.join(project_dir, ".claude", "hooks", "guard-patterns.conf"),
        os.path.join(project_dir, "guard-patterns.conf"),
    ]
    for conf_path in conf_candidates:
        if os.path.exists(conf_path):
            content = open(conf_path, encoding="utf-8", errors="replace").read()
            in_section = False
            for line in content.splitlines():
                if line.strip() == "[protected-paths]":
                    in_section = True
                    continue
                if line.strip().startswith("[") and in_section:
                    break
                if in_section and line.strip() and not line.strip().startswith("#"):
                    protected.add(line.strip())
            break

    # 从 .gitmodules 自动检测
    gitmodules = os.path.join(project_dir, ".gitmodules")
    if os.path.exists(gitmodules):
        content = open(gitmodules, encoding="utf-8", errors="replace").read()
        for match in re.findall(r'path\s*=\s*(.+)', content):
            protected.add(match.strip() + "/")

    # 追加配置中的额外路径
    for p in cfg.get("additional", []):
        protected.add(p)

    if not protected:
        return [{"name": "Protected dirs", "status": "SKIP",
                 "detail": "No protected paths configured"}]

    for p in sorted(protected):
        full = os.path.join(project_dir, p.rstrip("/"))
        if os.path.exists(full):
            results.append({
                "name": f"Protected: {p}",
                "status": "PASS",
                "detail": "Exists and marked protected",
            })
        else:
            results.append({
                "name": f"Protected: {p}",
                "status": "SKIP",
                "detail": "Path does not exist in project",
            })

    return results


# ═══════════════════════════════════════════════════════════════
# Check 4: 已有实现审计
# ═══════════════════════════════════════════════════════════════
def check_existing_code(cfg, project_dir, task_keywords=None):
    """搜索项目中与当前任务相关的已有代码。

    【P9 修复】强制搜索步骤——在写代码前知道什么已经存在。
    【P10 修复】区分 exists/works vs exists/stub。
    【P11 修复】多命名规范搜索。
    """
    results = []
    stub_markers = cfg.get("stub_markers", [
        "TODO", "FIXME", "NotImplemented",
        "throw new NotImplementedException",
        "pass  # TODO", 'panic("not implemented")',
    ])

    if not task_keywords:
        return [{"name": "Existing code audit", "status": "SKIP",
                 "detail": "No task keywords provided (use --task)"}]

    for keyword in task_keywords:
        # 生成命名变体
        variants = _naming_variants(keyword)

        for variant in variants:
            # 用 git grep 搜索（比 grep 快，且尊重 .gitignore）
            output, rc = git("grep", "-l", "-i", variant, cwd=project_dir)
            if rc != 0 or not output.strip():
                continue

            files = output.strip().split("\n")
            for f in files[:5]:  # 最多报告 5 个文件
                # 检查是否是 stub
                try:
                    full_path = os.path.join(project_dir, f)
                    content = open(full_path, encoding="utf-8",
                                   errors="replace").read()
                    is_stub = any(m in content for m in stub_markers)

                    if is_stub:
                        results.append({
                            "name": f"Found (STUB): {f}",
                            "status": "WARN",
                            "detail": (
                                f"Contains '{variant}' but has stub markers. "
                                f"Extend, don't rewrite."
                            ),
                        })
                    else:
                        results.append({
                            "name": f"Found: {f}",
                            "status": "PASS",
                            "detail": (
                                f"Contains '{variant}'. "
                                f"Read before implementing."
                            ),
                        })
                except Exception:
                    results.append({
                        "name": f"Found: {f}",
                        "status": "PASS",
                        "detail": f"Contains '{variant}'",
                    })

    if not results:
        results.append({
            "name": f"Existing code for: {', '.join(task_keywords)}",
            "status": "WARN",
            "detail": "No existing code found. Confirm this is truly new work.",
        })

    return results


def _naming_variants(keyword):
    """生成关键词的多种命名变体。"""
    # 先分词
    words = re.split(r'[_\-\s]+', keyword)
    if len(words) == 1:
        # 尝试从 camelCase/PascalCase 分词
        words = re.sub(r'([a-z])([A-Z])', r'\1 \2', keyword).split()

    if len(words) <= 1:
        return [keyword]

    lower_words = [w.lower() for w in words]
    variants = set()
    variants.add(keyword)  # 原样
    variants.add("_".join(lower_words))  # snake_case
    variants.add("-".join(lower_words))  # kebab-case
    variants.add("".join(w.capitalize() for w in lower_words))  # PascalCase
    variants.add(
        lower_words[0] + "".join(w.capitalize() for w in lower_words[1:])
    )  # camelCase

    return list(variants)


# ═══════════════════════════════════════════════════════════════
# Check 5: 构建基线
# ═══════════════════════════════════════════════════════════════
def check_build_baseline(cfg, project_dir):
    """记录当前构建/测试状态作为基线。

    【P12 修复】编译和测试分开，编译失败时仍记录状态。
    【P13 修复】标记已知 flaky 测试。
    """
    results = []
    compile_cmds = cfg.get("compile_commands", [])
    test_cmd = cfg.get("test_cmd", "")
    known_flaky = set(cfg.get("known_flaky", []))
    output_path = cfg.get("output", "docs/session-baseline.md")

    baseline = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "compile": [],
        "test": {},
    }

    # 编译检查
    for cmd in compile_cmds:
        try:
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=project_dir, timeout=300,
            )
            status = "PASS" if r.returncode == 0 else "FAIL"
            baseline["compile"].append({
                "cmd": cmd, "status": status,
                "errors": r.stderr[:500] if r.returncode != 0 else "",
            })
            results.append({
                "name": f"Compile: {cmd[:50]}",
                "status": status,
                "detail": "OK" if status == "PASS" else r.stderr[:100],
            })
        except subprocess.TimeoutExpired:
            results.append({
                "name": f"Compile: {cmd[:50]}",
                "status": "WARN",
                "detail": "Timeout (300s)",
            })
        except Exception as e:
            # 【P18 修复】工具缺失不崩溃
            results.append({
                "name": f"Compile: {cmd[:50]}",
                "status": "SKIP",
                "detail": f"Cannot run: {e}",
            })

    # 测试检查
    if test_cmd:
        try:
            r = subprocess.run(
                test_cmd, shell=True, capture_output=True, text=True,
                cwd=project_dir, timeout=600,
            )
            # 解析测试输出（通用：统计 PASS/FAIL 行数）
            output_text = r.stdout + r.stderr
            pass_count = len(re.findall(r'(?:PASS|ok|passed)', output_text, re.I))
            fail_count = len(re.findall(r'(?:FAIL|failed|error)', output_text, re.I))

            baseline["test"] = {
                "cmd": test_cmd,
                "exit_code": r.returncode,
                "pass_estimate": pass_count,
                "fail_estimate": fail_count,
                "output_tail": output_text[-1000:],
            }

            if r.returncode == 0:
                results.append({
                    "name": "Test baseline",
                    "status": "PASS",
                    "detail": f"All tests pass (~{pass_count} pass signals)",
                })
            else:
                results.append({
                    "name": "Test baseline",
                    "status": "WARN",
                    "detail": (
                        f"Some tests fail (exit {r.returncode}). "
                        f"~{fail_count} fail signals. "
                        f"This is the starting state, not your fault."
                    ),
                })
        except subprocess.TimeoutExpired:
            results.append({
                "name": "Test baseline",
                "status": "WARN",
                "detail": "Test suite timeout (600s). Consider smoke test.",
            })
        except Exception as e:
            results.append({
                "name": "Test baseline",
                "status": "SKIP",
                "detail": f"Cannot run: {e}",
            })

    # 写基线文件
    if output_path:
        full_output = os.path.join(project_dir, output_path)
        os.makedirs(os.path.dirname(full_output) or ".", exist_ok=True)

        lines = [
            "# Session Baseline",
            f"Recorded: {baseline['timestamp']}",
            "",
            "## Compile Status",
        ]
        for c in baseline["compile"]:
            lines.append(f"- `{c['cmd']}`: **{c['status']}**")
            if c.get("errors"):
                lines.append(f"  ```\n  {c['errors'][:200]}\n  ```")

        if baseline["test"]:
            t = baseline["test"]
            lines.append("")
            lines.append("## Test Status")
            lines.append(f"- Command: `{t['cmd']}`")
            lines.append(f"- Exit code: {t['exit_code']}")
            lines.append(f"- Pass signals: ~{t.get('pass_estimate', '?')}")
            lines.append(f"- Fail signals: ~{t.get('fail_estimate', '?')}")

        if known_flaky:
            lines.append("")
            lines.append("## Known Flaky Tests (ignore these)")
            for f in sorted(known_flaky):
                lines.append(f"- {f}")

        lines.append("")
        lines.append(
            "> Compare against this baseline after your changes. "
            "New failures = your bugs. Pre-existing failures = not your fault."
        )

        with open(full_output, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        results.append({
            "name": "Baseline recorded",
            "status": "PASS",
            "detail": full_output,
        })

    return results


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════
def run_preflight(project_dir, config, scope=None, task_keywords=None):
    """运行所有启用的预检项。"""
    checks_cfg = config.get("checks", {})
    all_results = {}

    # 1. Proto consistency
    proto_cfg = checks_cfg.get("proto_consistency", {})
    if proto_cfg.get("enabled"):
        all_results["proto_consistency"] = check_proto_consistency(
            proto_cfg, project_dir
        )

    # 2. Enum sync
    enum_cfg = checks_cfg.get("enum_sync", {})
    if enum_cfg.get("enabled"):
        all_results["enum_sync"] = check_enum_sync(enum_cfg, project_dir)

    # 3. Protected dirs
    protected_cfg = checks_cfg.get("protected_dirs", {})
    if protected_cfg.get("enabled", True):
        all_results["protected_dirs"] = check_protected_dirs(
            protected_cfg, project_dir
        )

    # 4. Existing code audit
    existing_cfg = checks_cfg.get("existing_code_audit", {})
    if existing_cfg.get("enabled", True):
        all_results["existing_code_audit"] = check_existing_code(
            existing_cfg, project_dir, task_keywords
        )

    # 5. Build baseline
    baseline_cfg = checks_cfg.get("build_baseline", {})
    if baseline_cfg.get("enabled", True):
        all_results["build_baseline"] = check_build_baseline(
            baseline_cfg, project_dir
        )

    return all_results


def generate_report(all_results, project_dir):
    """生成结构化报告。"""
    report = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project": project_dir,
        "checks": {},
        "overall": "PASS",
        "fixable_count": 0,
        "blocking_count": 0,
    }

    for check_name, results in all_results.items():
        fails = [r for r in results if r["status"] == "FAIL"]
        warns = [r for r in results if r["status"] == "WARN"]
        fixable = [r for r in results if r.get("fixable")]

        report["checks"][check_name] = {
            "results": results,
            "pass": len([r for r in results if r["status"] == "PASS"]),
            "fail": len(fails),
            "warn": len(warns),
            "fixable": len(fixable),
        }
        report["fixable_count"] += len(fixable)
        report["blocking_count"] += len([f for f in fails if not f.get("fixable")])

    if report["blocking_count"] > 0:
        report["overall"] = "BLOCKED"
    elif report["fixable_count"] > 0:
        report["overall"] = "FIXABLE"

    return report


def main():
    if len(sys.argv) < 2:
        print(
            "用法:\n"
            "  python preflight.py <project_dir> [--config preflight.yaml]\n"
            "  python preflight.py <project_dir> --task \"vehicle insurance\"\n"
            "  python preflight.py <project_dir> --scope vehicle,clothing\n"
            "  python preflight.py <project_dir> --fix"
        )
        sys.exit(1)

    project_dir = sys.argv[1]
    config_path = None
    task_keywords = None
    do_fix = "--fix" in sys.argv

    if "--config" in sys.argv:
        idx = sys.argv.index("--config")
        if idx + 1 < len(sys.argv):
            config_path = sys.argv[idx + 1]
    else:
        # 自动查找配置
        for candidate in [
            os.path.join(project_dir, "preflight.yaml"),
            os.path.join(project_dir, ".reward-loop", "preflight.yaml"),
        ]:
            if os.path.exists(candidate):
                config_path = candidate
                break

    if "--task" in sys.argv:
        idx = sys.argv.index("--task")
        if idx + 1 < len(sys.argv):
            task_keywords = sys.argv[idx + 1].split(",")

    # --scope: 限定预检范围到特定系统（用于并行 Agent）
    scope = None
    if "--scope" in sys.argv:
        idx = sys.argv.index("--scope")
        if idx + 1 < len(sys.argv):
            scope = sys.argv[idx + 1].split(",")

    config = load_config(config_path)

    # 如果指定了 scope，限定 build_baseline 和 existing_code_audit 的搜索范围
    if scope:
        checks_cfg = config.get("checks", {})
        # 用 scope 关键词作为 task_keywords 的补充
        if not task_keywords:
            task_keywords = scope
    settings = config.get("settings", {})

    # 【P16 修复】修复-重检循环
    max_loops = settings.get("max_fix_loops", 3) if do_fix else 1

    for loop_num in range(max_loops):
        all_results = run_preflight(
            project_dir, config, task_keywords=task_keywords
        )
        report = generate_report(all_results, project_dir)

        # 无可修项或不需要修 → 结束循环
        if not do_fix or report["fixable_count"] == 0:
            break

        # 有可修项 → 尝试修复，然后重跑预检
        print(f"\n  [Fix loop {loop_num + 1}/{max_loops}] "
              f"Attempting {report['fixable_count']} fixes...")
        fixed_any = False
        for check_results in all_results.values():
            for r in check_results:
                if r.get("fixable") and r.get("fix_cmd"):
                    print(f"    Running: {r['fix_cmd']}")
                    fix_r = subprocess.run(
                        r["fix_cmd"], shell=True, cwd=project_dir,
                        capture_output=True, timeout=300,
                    )
                    if fix_r.returncode == 0:
                        fixed_any = True
                    else:
                        print(f"    Fix failed (exit {fix_r.returncode})")

        if not fixed_any:
            print("    No fixes succeeded. Stopping fix loop.")
            break

    # 打印报告
    print(f"\n{'=' * 60}")
    print(f"  Preflight Validation: {report['overall']}")
    print(f"{'=' * 60}")

    for check_name, check_data in report["checks"].items():
        icon = "[PASS]" if check_data["fail"] == 0 else "[FAIL]"
        print(f"\n  {icon} {check_name} "
              f"({check_data['pass']}P / {check_data['fail']}F / "
              f"{check_data['warn']}W)")
        for r in check_data["results"]:
            status_icon = {
                "PASS": "  OK", "FAIL": "  !!", "WARN": "  ??", "SKIP": "  --"
            }.get(r["status"], "  ??")
            print(f"    [{status_icon}] {r['name']}: {r['detail']}")

    # 写 JSON 报告
    report_path = os.path.join(project_dir, "preflight-report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n  Report: {report_path}")

    # exit code: 0=pass, 1=fixable, 2=blocked
    if report["overall"] == "BLOCKED":
        sys.exit(2)
    elif report["overall"] == "FIXABLE":
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
