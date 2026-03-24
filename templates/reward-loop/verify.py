#!/usr/bin/env python3
"""
verify.py — 部署后环境完整性验证

检查三个维度：
  1. 环境健康：所有组件是否就位
  2. 原子化链路：每个约束是否生效
  3. 进化管道：从目标输入到结果输出的链路是否完整

用法: python verify.py <project_dir> [--output verify-result.json]
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def check_file(path, label):
    exists = os.path.exists(path)
    executable = os.access(path, os.X_OK) if exists else False
    return {
        "name": label,
        "status": "PASS" if exists else "FAIL",
        "detail": f"已就位{' (可执行)' if executable else ''}" if exists else "缺失",
        "path": path,
    }


def check_content(path, pattern, label):
    """检查文件中是否包含指定内容"""
    if not os.path.exists(path):
        return {"name": label, "status": "FAIL", "detail": f"文件不存在: {path}"}
    content = open(path, encoding="utf-8", errors="replace").read()
    found = pattern in content
    return {
        "name": label,
        "status": "PASS" if found else "FAIL",
        "detail": "已配置" if found else f"未找到: {pattern}",
    }


def check_command(cmd, label):
    """检查命令是否可用"""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=5)
        return {"name": label, "status": "PASS", "detail": "可用"}
    except FileNotFoundError:
        return {"name": label, "status": "FAIL", "detail": "命令不存在"}
    except subprocess.TimeoutExpired:
        return {"name": label, "status": "PASS", "detail": "可用（超时但存在）"}
    except Exception as e:
        return {"name": label, "status": "WARN", "detail": str(e)[:80]}


def verify(project_dir):
    result = {"sections": {}}
    has_git = os.path.exists(os.path.join(project_dir, ".git"))  # .git 可以是目录或文件（worktree）

    # 读取部署计划（如果有），确定验证范围
    plan_path = os.path.join(project_dir, ".deploy", "plan.json")
    plan = None
    verify_scope = None  # None = 检查所有（向后兼容）
    if os.path.exists(plan_path):
        try:
            with open(plan_path, encoding="utf-8") as f:
                plan = json.load(f)
            verify_scope = set(plan.get("verify_scope", []))
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    # 第一维度：环境健康（组件是否就位）
    # ═══════════════════════════════════════════════════════════

    # Git Hooks
    git_hooks = []
    if not has_git:
        git_hooks.append({"name": "Git", "status": "SKIP", "detail": "非 Git 项目，跳过 git hooks 检查"})
    else:
        for hook in ["pre-commit", "commit-msg", "pre-push"]:
            gh = os.path.join(project_dir, ".git", "hooks", hook)
            hh = os.path.join(project_dir, ".husky", hook)
            if os.path.exists(hh):
                git_hooks.append({"name": hook, "status": "PASS", "detail": f"husky ({hh})"})
            elif os.path.exists(gh):
                git_hooks.append({"name": hook, "status": "PASS", "detail": f"raw hook ({gh})"})
            else:
                git_hooks.append({"name": hook, "status": "FAIL", "detail": "未安装"})
    result["sections"]["git_hooks"] = {
        "label": "Git 提交门禁",
        "icon": "gate",
        "checks": git_hooks,
    }

    # Claude Code Hooks
    claude_hooks = []
    hooks_dir = os.path.join(project_dir, ".claude", "hooks")
    for hook_file, desc in [
        ("session-start.sh", "会话启动注入"),
        ("pre-bash-guard.sh", "命令安全守卫"),
        ("pre-edit-guard.sh", "编辑路径守卫"),
        ("post-edit-verify.sh", "编辑后自检"),
        ("guard-patterns.conf", "守卫规则配置"),
        ("anti-rationalization.sh", "偷懒检测"),
        ("evolution-score.sh", "进化信号采集"),
        ("instinct-extract.sh", "经验提取"),
    ]:
        claude_hooks.append(check_file(os.path.join(hooks_dir, hook_file), desc))
    result["sections"]["claude_hooks"] = {
        "label": "Claude Code 守卫",
        "icon": "shield",
        "checks": claude_hooks,
    }

    # Rules / Agents / Skills
    assets = []
    rules_dir = os.path.join(project_dir, ".claude", "rules")
    for rule in ["code-style.md", "git-workflow.md", "security.md"]:
        assets.append(check_file(os.path.join(rules_dir, rule), f"规则: {rule}"))
    agents_dir = os.path.join(project_dir, ".claude", "agents")
    agent_count = len([f for f in os.listdir(agents_dir) if f.endswith(".md")]) if os.path.isdir(agents_dir) else 0
    assets.append({
        "name": "Agents",
        "status": "PASS" if agent_count >= 3 else "WARN",
        "detail": f"{agent_count} 个 Agent 已部署",
    })
    result["sections"]["assets"] = {
        "label": "规则与智能体",
        "icon": "brain",
        "checks": assets,
    }

    # 项目配置文件
    configs = []
    for cfg, desc in [
        (".editorconfig", "编辑器统一配置"),
        (".gitattributes", "Git 文件属性"),
        ("CLAUDE.md", "AI 上下文文件"),
    ]:
        configs.append(check_file(os.path.join(project_dir, cfg), desc))
    result["sections"]["configs"] = {
        "label": "项目配置",
        "icon": "config",
        "checks": configs,
    }

    # ═══════════════════════════════════════════════════════════
    # 第二维度：原子化链路（每个约束是否生效）
    # ═══════════════════════════════════════════════════════════
    atomic = []

    # 文件 < 500 行限制（检查 husky / raw hooks / pre-commit-config.yaml）
    size_check_found = False
    for candidate in [
        os.path.join(project_dir, ".husky", "pre-commit"),
        os.path.join(project_dir, ".git", "hooks", "pre-commit"),
    ]:
        if os.path.exists(candidate):
            content = open(candidate, encoding="utf-8", errors="replace").read()
            if "500" in content:
                size_check_found = True
                break
    # 也检查 .pre-commit-config.yaml
    pccy = os.path.join(project_dir, ".pre-commit-config.yaml")
    if not size_check_found and os.path.exists(pccy):
        content = open(pccy, encoding="utf-8", errors="replace").read()
        if "check-file-size" in content or "500" in content:
            size_check_found = True
    atomic.append({
        "name": "文件 < 500 行限制",
        "status": "PASS" if size_check_found else "FAIL",
        "detail": "已配置" if size_check_found else "未找到 500 行检查",
    })

    # Commit 格式校验（commitlint 或 pre-commit 框架的 commit-msg）
    cl_path = os.path.join(project_dir, "commitlint.config.js")
    commit_fmt_found = False
    commit_fmt_detail = "缺失"
    if os.path.exists(cl_path):
        commit_fmt_found = True
        commit_fmt_detail = "commitlint"
    elif os.path.exists(pccy):
        content = open(pccy, encoding="utf-8", errors="replace").read()
        if "commit-msg" in content:
            commit_fmt_found = True
            commit_fmt_detail = "pre-commit 框架 commit-msg"
    atomic.append({
        "name": "Commit 格式校验",
        "status": "PASS" if commit_fmt_found else "FAIL",
        "detail": commit_fmt_detail,
    })

    # 多话题检测
    if os.path.exists(cl_path):
        atomic.append(check_content(cl_path, "multitopic", "多话题检测 (warn)"))
    else:
        atomic.append({"name": "多话题检测", "status": "SKIP", "detail": "commitlint 未配置（Python 项目可选）"})

    # --no-verify 拦截
    guard_path = os.path.join(hooks_dir, "pre-bash-guard.sh")
    if os.path.exists(guard_path):
        atomic.append(check_content(guard_path, "no-verify", "--no-verify 拦截"))
    else:
        atomic.append({"name": "--no-verify 拦截", "status": "FAIL", "detail": "pre-bash-guard.sh 不存在"})

    # Allowlist 模式可用
    gp_path = os.path.join(hooks_dir, "guard-patterns.conf")
    if os.path.exists(gp_path):
        atomic.append(check_content(gp_path, "edit-mode", "Allowlist 模式可用"))
    else:
        atomic.append({"name": "Allowlist 模式", "status": "FAIL", "detail": "guard-patterns.conf 不存在"})

    # Guardrail 文件白名单
    gr_path = os.path.join(project_dir, ".reward-loop", "guardrail.py")
    if os.path.exists(gr_path):
        atomic.append(check_content(gr_path, "target_files", "Target files 白名单 (guardrail)"))
    else:
        atomic.append({"name": "Target files 白名单", "status": "SKIP", "detail": "reward-loop 未部署"})

    # Squash merge
    dr_path = os.path.join(project_dir, ".reward-loop", "driver.py")
    if os.path.exists(dr_path):
        atomic.append(check_content(dr_path, "squash", "Squash merge (一轮一个SHA)"))
    else:
        atomic.append({"name": "Squash merge", "status": "SKIP", "detail": "reward-loop 未部署"})

    # Guardrail 限制值合理性（max_files ≤ 10, max_insertions ≤ 200）
    sig_yaml_atom = os.path.join(project_dir, ".reward-loop", "signals.yaml")
    if os.path.exists(sig_yaml_atom):
        try:
            import yaml as _yaml_atom
            with open(sig_yaml_atom, encoding="utf-8") as f:
                sig_data_atom = _yaml_atom.safe_load(f)
            gl = sig_data_atom.get("guardrail", {}).get("limits", {})
            mf = gl.get("max_files_changed", 999)
            mi = gl.get("max_insertions", 999)
            if mf <= 10 and mi <= 200:
                atomic.append({"name": "Guardrail 限制值", "status": "PASS",
                               "detail": f"max_files={mf}, max_insertions={mi}"})
            else:
                atomic.append({"name": "Guardrail 限制值", "status": "WARN",
                               "detail": f"max_files={mf}, max_insertions={mi} — 过于宽松"})
        except Exception:
            atomic.append({"name": "Guardrail 限制值", "status": "SKIP", "detail": "解析失败"})
    else:
        atomic.append({"name": "Guardrail 限制值", "status": "SKIP", "detail": "signals.yaml 不存在"})

    # Git hooks 随仓库传递（husky .husky/ 或 .pre-commit-config.yaml）
    hooks_travel = False
    hooks_travel_detail = "hooks 不随仓库传递"
    if os.path.isdir(os.path.join(project_dir, ".husky")):
        hooks_travel = True
        hooks_travel_detail = "husky (.husky/ 在版本控制中)"
    elif os.path.exists(os.path.join(project_dir, ".pre-commit-config.yaml")):
        hooks_travel = True
        hooks_travel_detail = "pre-commit 框架 (.pre-commit-config.yaml)"
    atomic.append({
        "name": "Git hooks 随仓库传递",
        "status": "PASS" if hooks_travel else "WARN",
        "detail": hooks_travel_detail,
    })

    # CI: fail-fast 顺序（test needs lint）
    ci_path_atom = os.path.join(project_dir, ".github", "workflows", "ci.yml")
    if os.path.exists(ci_path_atom):
        ci_c = open(ci_path_atom, encoding="utf-8", errors="replace").read()
        ci_checks = []
        if "needs:" in ci_c and "lint" in ci_c:
            ci_checks.append(("CI fail-fast", True, "test needs lint"))
        else:
            ci_checks.append(("CI fail-fast", False, "test 不依赖 lint"))
        if "size-check" in ci_c or "PR size" in ci_c.lower():
            ci_checks.append(("PR 大小检查", True, "CI 中有 size-check"))
        else:
            ci_checks.append(("PR 大小检查", False, "CI 中无 PR 大小检查"))
        if "paths-filter" in ci_c or "check-scope" in ci_c:
            ci_checks.append(("Smart scoping", True, "文档变更跳过测试"))
        else:
            ci_checks.append(("Smart scoping", False, "所有变更都跑完整测试"))
        for name, ok, detail in ci_checks:
            atomic.append({"name": name, "status": "PASS" if ok else "WARN", "detail": detail})
    else:
        for name in ("CI fail-fast", "PR 大小检查", "Smart scoping"):
            atomic.append({"name": name, "status": "SKIP", "detail": "无 CI 配置"})

    # 质量棘轮（weekly-quality.yml 有 exit 1）
    wq_path = os.path.join(project_dir, ".github", "workflows", "weekly-quality.yml")
    if os.path.exists(wq_path):
        wq_c = open(wq_path, encoding="utf-8", errors="replace").read()
        has_exit = "exit 1" in wq_c
        has_baseline = "baseline" in wq_c.lower()
        if has_exit and has_baseline:
            atomic.append({"name": "质量棘轮", "status": "PASS", "detail": "exit 1 + baseline 对比"})
        elif has_baseline:
            atomic.append({"name": "质量棘轮", "status": "WARN", "detail": "有 baseline 但无 exit 1（只报告不阻断）"})
        else:
            atomic.append({"name": "质量棘轮", "status": "FAIL", "detail": "无棘轮逻辑"})
    else:
        atomic.append({"name": "质量棘轮", "status": "SKIP", "detail": "无 weekly-quality workflow"})

    result["sections"]["atomization"] = {
        "label": "原子化链路",
        "icon": "atom",
        "checks": atomic,
    }

    # ═══════════════════════════════════════════════════════════
    # 第三维度：进化管道（从输入到输出的完整链路）
    # ═══════════════════════════════════════════════════════════
    evo = []
    rl_dir = os.path.join(project_dir, ".reward-loop")

    # 驱动器
    evo.append(check_file(os.path.join(rl_dir, "driver.py"), "驱动器 (driver.py)"))

    # 观测
    evo.append(check_file(os.path.join(rl_dir, "observe.py"), "观测器 (observe.py)"))

    # 假设生成
    pr_path = os.path.join(rl_dir, "prompt.py")
    evo.append(check_file(pr_path, "假设生成 (prompt.py)"))
    if os.path.exists(pr_path):
        evo.append(check_content(pr_path, "target_files", "假设包含 target_files"))
        evo.append(check_content(pr_path, "prompt_meta", "Prompt 版本追踪"))

    # 护栏
    evo.append(check_file(os.path.join(rl_dir, "guardrail.py"), "护栏 (guardrail.py)"))

    # 信号系统
    for sig, desc in [
        (".security", "安全信号"),
        (".quality", "质量信号"),
        (".test-system", "测试信号"),
        (".perf-system", "性能信号"),
    ]:
        sig_dir = os.path.join(project_dir, sig)
        if os.path.isdir(sig_dir):
            # 检查 collector + judge 都存在
            has_collector = any(f.endswith(".sh") for f in os.listdir(sig_dir))
            has_judge = any(f.endswith(".py") and "judge" in f for f in os.listdir(sig_dir))
            if has_collector and has_judge:
                evo.append({"name": desc, "status": "PASS", "detail": "采集器 + 判定器就位"})
            else:
                missing = []
                if not has_collector: missing.append("采集器")
                if not has_judge: missing.append("判定器")
                evo.append({"name": desc, "status": "WARN", "detail": f"缺少: {', '.join(missing)}"})
        else:
            evo.append({"name": desc, "status": "SKIP", "detail": "未部署"})

    # 熔断器
    evo.append(check_file(os.path.join(rl_dir, "circuit_breaker.py"), "熔断器 (circuit_breaker.py)"))

    # 仪表盘
    evo.append(check_file(os.path.join(rl_dir, "dashboard.py"), "仪表盘 (dashboard.py)"))

    # 健康检查
    evo.append(check_file(os.path.join(rl_dir, "health-check.py"), "健康检查 (health-check.py)"))

    # 信号配置
    evo.append(check_file(os.path.join(rl_dir, "signals.yaml"), "信号配置 (signals.yaml)"))

    result["sections"]["evolution"] = {
        "label": "进化管道",
        "icon": "loop",
        "checks": evo,
    }

    # ═══════════════════════════════════════════════════════════
    # 第四维度：兼容性检查（装的东西适不适合这个项目）
    # ═══════════════════════════════════════════════════════════
    compat = []

    # 检测项目语言
    lang = "unknown"
    if os.path.exists(os.path.join(project_dir, "requirements.txt")) or \
       os.path.exists(os.path.join(project_dir, "pyproject.toml")) or \
       os.path.exists(os.path.join(project_dir, "setup.py")):
        lang = "python"
    elif os.path.exists(os.path.join(project_dir, "package.json")):
        lang = "node"
    elif os.path.exists(os.path.join(project_dir, "go.mod")):
        lang = "go"
    elif os.path.exists(os.path.join(project_dir, "Cargo.toml")):
        lang = "rust"
    # Unity: has Assets/ or *.unity files
    elif os.path.isdir(os.path.join(project_dir, "Assets")):
        lang = "unity"

    # C1: .nvmrc 只应该出现在 Node 项目
    nvmrc = os.path.join(project_dir, ".nvmrc")
    if os.path.exists(nvmrc) and lang != "node":
        compat.append({
            "name": ".nvmrc 不属于此项目",
            "status": "FAIL",
            "detail": f"这是 {lang} 项目，.nvmrc 是 Node.js 的版本文件，不该出现",
        })
    else:
        compat.append({
            "name": ".nvmrc 语言匹配",
            "status": "PASS" if not os.path.exists(nvmrc) or lang == "node" else "FAIL",
            "detail": "正确" if lang == "node" and os.path.exists(nvmrc) else "未使用 .nvmrc" if not os.path.exists(nvmrc) else "不匹配",
        })

    # C2: CI 配置的语言应该和项目一致
    ci_path = os.path.join(project_dir, ".github", "workflows", "ci.yml")
    if os.path.exists(ci_path):
        ci_content = open(ci_path, encoding="utf-8", errors="replace").read()
        ci_ok = True
        ci_detail = "CI 配置与项目语言匹配"
        if lang == "python":
            if "setup-node" in ci_content and "setup-python" not in ci_content:
                ci_ok = False
                ci_detail = "Python 项目但 CI 配置了 Node.js setup，会导致 CI 失败"
            elif "npm ci" in ci_content or "npm install" in ci_content:
                ci_ok = False
                ci_detail = "Python 项目但 CI 里有 npm 命令"
        elif lang == "node":
            if "setup-python" in ci_content and "setup-node" not in ci_content:
                ci_ok = False
                ci_detail = "Node 项目但 CI 配置了 Python setup"
        compat.append({"name": "CI 语言匹配", "status": "PASS" if ci_ok else "FAIL", "detail": ci_detail})
    else:
        compat.append({"name": "CI 语言匹配", "status": "SKIP", "detail": "无 CI 配置"})

    # C3: 500 行限制 vs 现有大文件冲突检测
    large_files = []
    for root, dirs, files in os.walk(project_dir):
        # 跳过隐藏目录和常见生成目录
        # 排除：隐藏目录、生成目录、子项目（projects/下的独立项目）
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                   ('node_modules', '__pycache__', 'venv', '.venv', 'dist', 'build',
                    'Library', 'out', 'Temp', 'obj', 'bin', 'target', 'vendor',
                    'projects', 'packages', 'third_party', 'external')]
        for f in files:
            if f.endswith(('.py', '.ts', '.tsx', '.js', '.jsx', '.cs', '.go', '.rs')):
                fp = os.path.join(root, f)
                try:
                    with open(fp, encoding="utf-8", errors="replace") as fh:
                        lines = sum(1 for _ in fh)
                    if lines > 500:
                        rel = os.path.relpath(fp, project_dir)
                        large_files.append((rel, lines))
                except Exception:
                    pass

    # 检查这些大文件是否在 pre-commit exclude 里
    pccy = os.path.join(project_dir, ".pre-commit-config.yaml")
    exclude_pattern = ""
    if os.path.exists(pccy):
        pc_content = open(pccy, encoding="utf-8", errors="replace").read()
        # 简单提取 check-file-size 的 exclude
        import re
        m = re.search(r'id:\s*check-file-size.*?exclude:\s*[\'"](.+?)[\'"]', pc_content, re.DOTALL)
        if m:
            exclude_pattern = m.group(1)

    if large_files:
        unprotected = []
        for fname, lines in large_files:
            if exclude_pattern:
                try:
                    if re.search(exclude_pattern, fname):
                        continue  # 已在白名单
                except Exception:
                    pass
            unprotected.append((fname, lines))

        if unprotected:
            names = ", ".join(f"{f}({l}行)" for f, l in unprotected[:3])
            compat.append({
                "name": "500 行限制 vs 现有大文件",
                "status": "FAIL",
                "detail": f"{len(unprotected)} 个文件超 500 行但不在白名单：{names}",
            })
        else:
            compat.append({
                "name": "500 行限制 vs 现有大文件",
                "status": "PASS",
                "detail": f"{len(large_files)} 个大文件均已在白名单中",
            })
    else:
        compat.append({
            "name": "500 行限制 vs 现有大文件",
            "status": "PASS",
            "detail": "无超过 500 行的代码文件",
        })

    # C4: signals.yaml 引用的路径是否都存在
    sig_yaml = os.path.join(project_dir, ".reward-loop", "signals.yaml")
    if os.path.exists(sig_yaml):
        try:
            import re as _re
            sig_content = open(sig_yaml, encoding="utf-8").read()
            # 只检查 enabled 的信号的路径引用
            # 先解析 YAML 找 enabled 的信号
            try:
                import yaml as _yaml
                sig_data = _yaml.safe_load(sig_content)
                referenced_paths = []
                for sig in sig_data.get("signals", []):
                    if not sig.get("enabled", True):
                        continue  # 跳过已禁用的信号
                    for key in ("collector", "judge", "config"):
                        if key in sig:
                            referenced_paths.append(sig[key])
            except Exception:
                # fallback: 用正则
                referenced_paths = _re.findall(r'(?:collector|judge|config):\s*["\']?([^\s"\'#]+)', sig_content)
            missing_refs = []
            for rp in referenced_paths:
                # 相对于 .reward-loop/ 目录
                full = os.path.join(project_dir, ".reward-loop", rp)
                if not os.path.exists(full):
                    missing_refs.append(rp)
            if missing_refs:
                compat.append({
                    "name": "signals.yaml 路径引用",
                    "status": "WARN",
                    "detail": f"{len(missing_refs)} 个引用路径不存在：{', '.join(missing_refs[:3])}",
                })
            else:
                compat.append({
                    "name": "signals.yaml 路径引用",
                    "status": "PASS",
                    "detail": "所有引用路径均存在",
                })
        except Exception as e:
            compat.append({"name": "signals.yaml 路径引用", "status": "WARN", "detail": str(e)[:80]})
    else:
        compat.append({"name": "signals.yaml 路径引用", "status": "SKIP", "detail": "无信号配置"})

    # C5: settings.json 的 allow 列表是否包含正确的语言工具
    sj_path = os.path.join(project_dir, ".claude", "settings.json")
    if os.path.exists(sj_path):
        try:
            sj = json.load(open(sj_path, encoding="utf-8"))
            allows = sj.get("permissions", {}).get("allow", [])
            allow_str = " ".join(allows)
            tool_ok = True
            tool_detail = "权限列表与项目语言匹配"
            if lang == "python":
                if "npm" in allow_str and "pip" not in allow_str and "python" not in allow_str:
                    tool_ok = False
                    tool_detail = "Python 项目但只允许了 npm 命令，缺少 pip/python"
            elif lang == "node":
                if "pip" in allow_str and "npm" not in allow_str:
                    tool_ok = False
                    tool_detail = "Node 项目但只允许了 pip 命令，缺少 npm"
            compat.append({"name": "权限列表语言匹配", "status": "PASS" if tool_ok else "WARN", "detail": tool_detail})
        except Exception:
            compat.append({"name": "权限列表语言匹配", "status": "SKIP", "detail": "读取失败"})
    else:
        compat.append({"name": "权限列表语言匹配", "status": "SKIP", "detail": "无 settings.json"})

    # C6: reward-loop 的 PyYAML 依赖
    rl_dir_check = os.path.join(project_dir, ".reward-loop")
    if os.path.isdir(rl_dir_check):
        try:
            import yaml as _yaml_check
            compat.append({"name": "PyYAML 依赖", "status": "PASS", "detail": "已安装"})
        except ImportError:
            compat.append({
                "name": "PyYAML 依赖",
                "status": "FAIL",
                "detail": "reward-loop 需要 PyYAML 但未安装（pip install pyyaml）",
            })
    else:
        compat.append({"name": "PyYAML 依赖", "status": "SKIP", "detail": "reward-loop 未部署"})

    result["sections"]["compatibility"] = {
        "label": "兼容性检查",
        "icon": "puzzle",
        "checks": compat,
    }

    # ═══════════════════════════════════════════════════════════
    # 后处理：根据部署计划调整检查结果
    # ═══════════════════════════════════════════════════════════

    # 如果有 plan.json，不在验证范围内的 section 的 FAIL → SKIP
    if verify_scope is not None:
        for sec_key, sec in result["sections"].items():
            if sec_key not in verify_scope:
                for check in sec.get("checks", []):
                    if check["status"] == "FAIL":
                        check["status"] = "SKIP"
                        check["detail"] = "不在部署计划内，不适用"

    # 兜底：即使没有 plan.json，也做基本的合理性降级
    if not has_git:
        for sec_key in ("git_hooks", "atomization"):
            sec = result["sections"].get(sec_key, {})
            for check in sec.get("checks", []):
                if check["status"] == "FAIL":
                    check["status"] = "SKIP"
                    check["detail"] = "非 Git 项目，不适用"

    if not os.path.isdir(os.path.join(project_dir, ".reward-loop")):
        sec = result["sections"].get("evolution", {})
        for check in sec.get("checks", []):
            if check["status"] == "FAIL":
                check["status"] = "SKIP"
                check["detail"] = "reward-loop 未部署，不适用"

    # ═══════════════════════════════════════════════════════════
    # 汇总
    # ═══════════════════════════════════════════════════════════
    for section in result["sections"].values():
        checks = section["checks"]
        pass_count = sum(1 for c in checks if c["status"] == "PASS")
        total = len(checks)
        fail_count = sum(1 for c in checks if c["status"] == "FAIL")
        section["summary"] = f"{pass_count}/{total} 通过"
        section["status"] = "FAIL" if fail_count > 0 else "PASS"
        section["pass_count"] = pass_count
        section["total"] = total

    all_checks = [c for s in result["sections"].values() for c in s["checks"]]
    total_pass = sum(1 for c in all_checks if c["status"] == "PASS")
    total_skip = sum(1 for c in all_checks if c["status"] == "SKIP")
    total_all = len(all_checks)
    total_fail = sum(1 for c in all_checks if c["status"] == "FAIL")
    applicable = total_all - total_skip  # 实际适用的检查项数
    result["overall"] = "PASS" if total_fail == 0 else "FAIL"
    result["summary"] = f"{total_pass}/{total_all} 项检查通过"
    result["pass_count"] = total_pass
    result["total"] = total_all
    result["skip_count"] = total_skip
    result["applicable"] = applicable
    result["applicable_summary"] = f"适用 {applicable} 项中 {total_pass} 项通过" if applicable != total_all else f"{total_pass}/{total_all} 项全部通过"

    return result


def main():
    if len(sys.argv) < 2:
        print("用法: python verify.py <project_dir> [--output result.json]")
        sys.exit(1)

    project_dir = sys.argv[1]
    output_path = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]

    result = verify(project_dir)

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"验证结果: {output_path}")

    # 打印摘要
    print(f"\n{'=' * 50}")
    print(f"  环境验证: {result['overall']}")
    print(f"  {result['summary']}")
    print(f"{'=' * 50}")
    for key, section in result["sections"].items():
        icon = "[PASS]" if section["status"] == "PASS" else "[FAIL]"
        print(f"  {icon} {section['label']}: {section['summary']}")
        for c in section["checks"]:
            ci = "[OK]" if c["status"] == "PASS" else "[!!]" if c["status"] == "FAIL" else "[--]"
            print(f"    {ci} {c['name']} — {c['detail']}")
    print()

    sys.exit(0 if result["overall"] == "PASS" else 1)


if __name__ == "__main__":
    main()
