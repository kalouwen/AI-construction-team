#!/usr/bin/env python3
"""
analyze-project.py — 读懂项目，生成部署计划

不猜，不假设。读项目文档、看目录结构、分析代码，
输出一份有理有据的部署计划。

用法: python analyze-project.py <project_dir>
输出: <project_dir>/.deploy/plan.json

plan.json 结构：
  project:    项目画像（是什么、干什么、有什么）
  decisions:  每个组件装/不装 + 原因
  recommendations: 建议做但自动做不了的事
  verify_scope: 验证时应该检查哪些维度
"""

import json
import os
import re
import sys
from pathlib import Path


def read_file(path, max_lines=200):
    """安全读文件，最多读 max_lines 行"""
    if not os.path.exists(path):
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                lines.append(line)
            return "".join(lines)
    except Exception:
        return ""


def scan_directory(project_dir):
    """扫描目录结构，返回统计信息"""
    stats = {
        "total_files": 0,
        "code_files": {},   # extension → count
        "doc_files": 0,
        "has_git": os.path.exists(os.path.join(project_dir, ".git")),  # .git 可以是目录（正常）或文件（worktree）
        "has_tests": False,
        "has_ci": os.path.isdir(os.path.join(project_dir, ".github", "workflows")),
        "has_claude": os.path.isdir(os.path.join(project_dir, ".claude")),
        "has_package_json": os.path.exists(os.path.join(project_dir, "package.json")),
        "has_requirements": os.path.exists(os.path.join(project_dir, "requirements.txt")),
        "has_pyproject": os.path.exists(os.path.join(project_dir, "pyproject.toml")),
        "has_go_mod": os.path.exists(os.path.join(project_dir, "go.mod")),
        "has_cargo": os.path.exists(os.path.join(project_dir, "Cargo.toml")),
        "has_unity": os.path.isdir(os.path.join(project_dir, "Assets")) and
                     os.path.isdir(os.path.join(project_dir, "ProjectSettings")),
        "has_dotnet": bool(
            list(Path(project_dir).glob("*.sln")) or
            list(Path(project_dir).glob("*.csproj"))
        ),
        "top_dirs": [],
        "max_code_lines": 0,
        "large_files": [],
    }

    skip_dirs = {
        "node_modules", "__pycache__", "venv", ".venv", "dist", "build",
        "Library", "out", "Temp", "obj", "bin", "target", "vendor",
        ".git", ".claude", ".deploy", ".github",
    }

    code_exts = {".py", ".js", ".ts", ".tsx", ".jsx", ".cs", ".go", ".rs", ".java", ".kt", ".rb", ".php"}
    doc_exts = {".md", ".txt", ".rst", ".html", ".pdf"}
    test_patterns = {"test", "tests", "spec", "__tests__", "test_", "_test"}

    # 顶级目录
    try:
        for item in sorted(os.listdir(project_dir)):
            full = os.path.join(project_dir, item)
            if os.path.isdir(full) and not item.startswith("."):
                stats["top_dirs"].append(item)
                if item.lower() in test_patterns:
                    stats["has_tests"] = True
    except Exception:
        pass

    # 递归扫描
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        # 不深入子项目
        depth = root.replace(project_dir, "").count(os.sep)
        if depth > 5:
            dirs.clear()
            continue

        for f in files:
            stats["total_files"] += 1
            ext = os.path.splitext(f)[1].lower()

            if ext in code_exts:
                stats["code_files"][ext] = stats["code_files"].get(ext, 0) + 1
                # 检查大文件
                fp = os.path.join(root, f)
                try:
                    lines = sum(1 for _ in open(fp, encoding="utf-8", errors="replace"))
                    if lines > 500:
                        rel = os.path.relpath(fp, project_dir)
                        stats["large_files"].append({"file": rel, "lines": lines})
                    if lines > stats["max_code_lines"]:
                        stats["max_code_lines"] = lines
                except Exception:
                    pass

                # 检查是否有测试
                if any(p in f.lower() for p in ("test_", "_test.", ".test.", ".spec.")):
                    stats["has_tests"] = True

            elif ext in doc_exts:
                stats["doc_files"] += 1

    return stats


def determine_project_type(docs, stats):
    """根据文档内容和目录结构判断项目类型"""
    total_code = sum(stats["code_files"].values())
    total_docs = stats["doc_files"]

    # 从文档中提取关键词
    all_text = " ".join(docs.values()).lower()

    if total_code == 0 and total_docs > 5:
        return "docs", "纯文档项目，没有代码文件"
    elif total_code < 5 and total_docs > total_code * 3:
        return "docs", "以文档为主的项目，少量代码"
    elif stats["has_unity"]:
        return "game", "Unity 游戏项目"
    elif "game" in all_text and ("agent" in all_text or "ai" in all_text):
        return "ai-system", "AI 驱动的系统（可能是游戏生产/自动化）"
    elif stats["has_tests"] and total_code > 20:
        return "code-active", "活跃的代码项目，有测试体系"
    elif total_code > 5:
        return "code-basic", "代码项目，基础阶段"
    else:
        return "unknown", "无法确定项目类型"


def determine_language(stats, project_dir):
    """根据代码文件统计确定主语言，优先看项目根目录和 src/ 目录"""
    # 先看项目标志文件（最准确）
    if stats["has_unity"]:
        return "csharp", "Unity 项目 (Assets/ + ProjectSettings/)"
    if stats["has_dotnet"]:
        return "csharp", ".NET 项目 (*.sln / *.csproj)"
    if stats["has_go_mod"]:
        return "go", "Go 项目 (go.mod)"
    if stats["has_cargo"]:
        return "rust", "Rust 项目 (Cargo.toml)"

    # 再看 src/ 目录的代码（项目主代码，排除子项目/生成物）
    src_files = {}
    ext_to_lang = {
        ".py": "python", ".js": "node", ".ts": "node", ".tsx": "node",
        ".jsx": "node", ".cs": "csharp", ".go": "go", ".rs": "rust",
        ".java": "java", ".kt": "kotlin", ".rb": "ruby", ".php": "php",
    }
    code_exts = set(ext_to_lang.keys())

    # 优先扫描 src/, lib/, app/ 等主代码目录
    primary_dirs = ["src", "lib", "app", "pkg", "cmd", "internal"]
    for pd in primary_dirs:
        pd_path = os.path.join(project_dir, pd)
        if os.path.isdir(pd_path):
            for root, dirs, files in os.walk(pd_path):
                dirs[:] = [d for d in dirs if d not in {"node_modules", "__pycache__", "venv", ".venv"}]
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in code_exts:
                        src_files[ext] = src_files.get(ext, 0) + 1

    # 如果 src/ 等目录有代码，以那里的语言为准
    if src_files:
        sorted_exts = sorted(src_files.items(), key=lambda x: -x[1])
        top_ext, top_count = sorted_exts[0]
        lang = ext_to_lang.get(top_ext, "unknown")
        return lang, f"src/ 目录主代码: {top_count} 个 {top_ext} 文件"

    # 再看项目配置文件推断
    if stats["has_requirements"] or stats["has_pyproject"]:
        return "python", "有 requirements.txt / pyproject.toml"
    if stats["has_package_json"]:
        return "node", "有 package.json"

    # 最后看全局统计（不准，但总比 unknown 好）
    if not stats["code_files"]:
        return "none", "无代码文件"

    sorted_exts = sorted(stats["code_files"].items(), key=lambda x: -x[1])
    top_ext, top_count = sorted_exts[0]
    lang = ext_to_lang.get(top_ext, "unknown")
    return lang, f"全局统计: {top_count} 个 {top_ext} 文件（可能含子项目）"


def make_decisions(project_type, language, stats, docs):
    """为每个组件做装/不装的决策，附带原因"""
    decisions = []
    all_text = " ".join(docs.values()).lower()
    has_git = stats["has_git"]

    # ── Claude Hooks（核心守卫） ──
    decisions.append({
        "component": "claude_hooks",
        "action": "deploy",
        "reason": "只要用 Claude Code 就需要守卫——防止改错文件、跑危险命令。所有项目都需要。",
    })

    # ── Rules / Agents / Skills ──
    decisions.append({
        "component": "rules",
        "action": "deploy",
        "reason": "行为准则让 AI 知道项目的编码规范和安全要求。所有项目都受益。",
    })
    decisions.append({
        "component": "agents",
        "action": "deploy",
        "reason": "专业分工（code-reviewer, planner 等）提高 AI 工作质量。",
    })

    # ── Git Hooks ──
    if has_git:
        if stats["has_tests"]:
            decisions.append({
                "component": "git_hooks",
                "action": "deploy",
                "reason": f"项目有 git 且有测试，提交门禁确保每次 commit 都跑测试、格式正确。",
            })
        else:
            decisions.append({
                "component": "git_hooks",
                "action": "deploy",
                "reason": "项目有 git，部署 commit 格式校验。没有测试，跳过 pre-commit 测试。",
            })
    else:
        decisions.append({
            "component": "git_hooks",
            "action": "skip",
            "reason": "项目没有 git，git hooks 无处安装。",
        })

    # ── GitHub Actions ──
    if has_git and project_type in ("code-active", "code-basic", "ai-system"):
        decisions.append({
            "component": "github_actions",
            "action": "deploy",
            "reason": "代码项目 + 有 git，CI 自动化能在 PR 时自动跑测试和安全扫描。",
        })
    else:
        reason = "没有 git" if not has_git else "文档项目不需要 CI 流水线"
        decisions.append({
            "component": "github_actions",
            "action": "skip",
            "reason": reason,
        })

    # ── 安全信号 ──
    decisions.append({
        "component": "security_signal",
        "action": "deploy",
        "reason": "密钥扫描对所有项目都有必要——防止意外提交 API key 或密码。",
    })

    # ── 质量信号 ──
    if sum(stats["code_files"].values()) > 0:
        decisions.append({
            "component": "quality_signal",
            "action": "deploy",
            "reason": f"项目有 {sum(stats['code_files'].values())} 个代码文件，质量棘轮能防止 TODO/FIXME 越积越多。",
        })
    else:
        decisions.append({
            "component": "quality_signal",
            "action": "skip",
            "reason": "没有代码文件，质量信号无检查对象。",
        })

    # ── 测试信号 ──
    if stats["has_tests"]:
        decisions.append({
            "component": "test_signal",
            "action": "deploy",
            "reason": "项目已有测试，测试信号能自动检测覆盖率退化。",
        })
    elif sum(stats["code_files"].values()) > 10:
        decisions.append({
            "component": "test_signal",
            "action": "deploy",
            "reason": "项目有大量代码但还没有测试，部署测试信号为将来写测试做准备。",
        })
    else:
        decisions.append({
            "component": "test_signal",
            "action": "skip",
            "reason": "项目代码量少或没有代码，测试信号暂时不需要。",
        })

    # ── 性能信号 ──
    perf_keywords = ["performance", "perf", "benchmark", "fps", "latency", "性能"]
    if any(k in all_text for k in perf_keywords) or stats["has_unity"]:
        decisions.append({
            "component": "perf_signal",
            "action": "deploy",
            "reason": "项目文档提到性能相关需求，部署性能信号自动监控。",
        })
    else:
        decisions.append({
            "component": "perf_signal",
            "action": "skip",
            "reason": "项目文档未提到性能需求，跳过性能信号。",
        })

    # ── Reward Loop ──
    if project_type in ("code-active", "ai-system") and has_git:
        decisions.append({
            "component": "reward_loop",
            "action": "deploy",
            "reason": "活跃的代码项目 + 有 git，全自动进化循环能让 AI 自己发现问题→修复→验证→合并。",
        })
    elif project_type == "code-basic" and has_git:
        decisions.append({
            "component": "reward_loop",
            "action": "deploy",
            "reason": "代码项目有 git，部署 reward loop 为自动化迭代做准备。",
        })
    else:
        reason = []
        if not has_git:
            reason.append("没有 git（reward loop 需要 git 来管理变更）")
        if project_type == "docs":
            reason.append("文档项目没有代码迭代需求")
        decisions.append({
            "component": "reward_loop",
            "action": "skip",
            "reason": "；".join(reason) if reason else "当前项目类型不适合自动进化循环",
        })

    # ── 配置文件 ──
    decisions.append({
        "component": "config_files",
        "action": "deploy",
        "reason": ".editorconfig 统一编辑器配置，所有项目都受益。",
    })

    # ── 社区文件 ──
    if has_git and project_type in ("code-active", "ai-system"):
        decisions.append({
            "component": "community_files",
            "action": "deploy",
            "reason": "有 git 的代码项目，PR 模板和贡献指南能规范协作流程。",
        })
    else:
        decisions.append({
            "component": "community_files",
            "action": "skip",
            "reason": "没有 git" if not has_git else "文档/小型项目暂不需要社区文件",
        })

    return decisions


def make_recommendations(project_type, language, stats, docs):
    """生成"建议做但我自动做不了"的清单"""
    recs = []

    if not stats["has_git"]:
        recs.append({
            "item": "建议初始化 git",
            "reason": "没有版本控制的项目改错了无法回退，多人协作无法追踪变更。",
            "command": "git init && git add -A && git commit -m 'chore: initial commit'",
            "priority": "high",
        })

    if not stats["has_tests"] and sum(stats["code_files"].values()) > 10:
        recs.append({
            "item": "建议添加测试",
            "reason": f"项目有 {sum(stats['code_files'].values())} 个代码文件但没有测试，重构时容易引入 bug。",
            "command": "使用 /test-writer agent 自动生成测试",
            "priority": "medium",
        })

    if stats["large_files"]:
        names = ", ".join(f["file"] for f in stats["large_files"][:3])
        recs.append({
            "item": f"有 {len(stats['large_files'])} 个文件超过 500 行",
            "reason": f"大文件难以理解和维护。超标文件：{names}",
            "command": "考虑拆分大文件，或在 pre-commit 白名单中排除",
            "priority": "low",
        })

    if stats["has_git"] and not stats["has_ci"]:
        recs.append({
            "item": "建议配置 CI",
            "reason": "有 git 但没有 CI，push 到远程后没有自动检查。",
            "command": "deploy.sh 可以自动生成 GitHub Actions 配置",
            "priority": "medium",
        })

    return recs


def determine_verify_scope(decisions):
    """根据部署决策确定验证范围"""
    scope = []
    component_to_section = {
        "claude_hooks": "claude_hooks",
        "rules": "assets",
        "agents": "assets",
        "git_hooks": "git_hooks",
        "config_files": "configs",
        "github_actions": None,  # 验证由 CI 自己负责
        "security_signal": "evolution",
        "quality_signal": "evolution",
        "test_signal": "evolution",
        "perf_signal": "evolution",
        "reward_loop": "evolution",
    }

    deployed = set()
    for d in decisions:
        if d["action"] == "deploy":
            sec = component_to_section.get(d["component"])
            if sec:
                deployed.add(sec)

    # 兼容性检查始终做
    deployed.add("compatibility")

    return sorted(deployed)


def analyze(project_dir):
    """主分析函数"""
    project_dir = os.path.abspath(project_dir)

    # 1. 读项目文档
    docs = {}
    for doc_name in ["CLAUDE.md", "README.md", "ARCHITECTURE.md", "docs/FRAMEWORK.md",
                     "docs/README.md", "docs/ROADMAP.md"]:
        content = read_file(os.path.join(project_dir, doc_name))
        if content:
            docs[doc_name] = content

    # 也读 package.json 的 description
    pkg = os.path.join(project_dir, "package.json")
    if os.path.exists(pkg):
        try:
            pkg_data = json.load(open(pkg, encoding="utf-8"))
            if pkg_data.get("description"):
                docs["package.json:description"] = pkg_data["description"]
        except Exception:
            pass

    # 2. 扫描目录结构
    stats = scan_directory(project_dir)

    # 3. 判断项目类型
    project_type, type_reason = determine_project_type(docs, stats)

    # 4. 判断语言
    language, lang_reason = determine_language(stats, project_dir)

    # 5. 从文档中提取项目描述
    description = ""
    for doc_name in ["CLAUDE.md", "README.md"]:
        content = docs.get(doc_name, "")
        if content:
            # 取第一个非空、非标题行
            for line in content.split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("---") and len(line) > 10:
                    description = line[:200]
                    break
            if description:
                break

    # 6. 生成部署决策
    decisions = make_decisions(project_type, language, stats, docs)

    # 7. 生成建议
    recommendations = make_recommendations(project_type, language, stats, docs)

    # 8. 确定验证范围
    verify_scope = determine_verify_scope(decisions)

    # 组装结果
    plan = {
        "project": {
            "name": os.path.basename(project_dir),
            "dir": project_dir,
            "type": project_type,
            "type_reason": type_reason,
            "language": language,
            "language_reason": lang_reason,
            "description": description,
            "has_git": stats["has_git"],
            "has_tests": stats["has_tests"],
            "has_ci": stats["has_ci"],
            "total_files": stats["total_files"],
            "code_files": sum(stats["code_files"].values()),
            "doc_files": stats["doc_files"],
            "code_breakdown": stats["code_files"],
            "top_dirs": stats["top_dirs"],
            "large_files_count": len(stats["large_files"]),
            "large_files": stats["large_files"][:10],
        },
        "decisions": decisions,
        "recommendations": recommendations,
        "verify_scope": verify_scope,
    }

    return plan


def main():
    # Windows 下强制 UTF-8 输出
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) < 2:
        print("用法: python analyze-project.py <project_dir>")
        sys.exit(1)

    project_dir = sys.argv[1]
    if not os.path.isdir(project_dir):
        print(f"错误: 目录不存在 {project_dir}")
        sys.exit(1)

    plan = analyze(project_dir)

    # 输出到 .deploy/plan.json
    deploy_dir = os.path.join(project_dir, ".deploy")
    os.makedirs(deploy_dir, exist_ok=True)
    output_path = os.path.join(deploy_dir, "plan.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

    # 打印摘要
    p = plan["project"]
    print(f"\n{'=' * 56}")
    print(f"  项目分析: {p['name']}")
    print(f"{'=' * 56}")
    print(f"  类型: {p['type']} ({p['type_reason']})")
    print(f"  语言: {p['language']} ({p['language_reason']})")
    print(f"  描述: {p['description'][:80]}")
    print(f"  Git: {'有' if p['has_git'] else '无'}  测试: {'有' if p['has_tests'] else '无'}  CI: {'有' if p['has_ci'] else '无'}")
    print(f"  文件: {p['total_files']} 个 (代码 {p['code_files']}, 文档 {p['doc_files']})")
    if p["large_files_count"]:
        print(f"  大文件: {p['large_files_count']} 个超 500 行")
    print()

    print("  部署决策:")
    for d in plan["decisions"]:
        icon = "[装]" if d["action"] == "deploy" else "[跳]"
        print(f"    {icon} {d['component']}")
        print(f"        {d['reason']}")
    print()

    if plan["recommendations"]:
        print("  建议（需人工处理）:")
        for r in plan["recommendations"]:
            print(f"    [{r['priority'].upper()}] {r['item']}")
            print(f"         {r['reason']}")
        print()

    print(f"  验证范围: {', '.join(plan['verify_scope'])}")
    print(f"\n  计划已保存: {output_path}")


if __name__ == "__main__":
    main()
