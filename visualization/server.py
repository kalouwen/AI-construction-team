#!/usr/bin/env python3
"""AI for Better - Mode Pipeline 可视化服务器

启动方式:
    python visualization/server.py --project "C:/目标工程路径"
    python visualization/server.py --project "C:/a daily difference"

支持运行时切换目标工程（前端下拉框）。
"""

import argparse
import json
import os
import re
import sys
import time
import webbrowser
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# 本框架根目录
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
PORT = 8430

# 项目注册表路径
PROJECTS_REGISTRY = FRAMEWORK_ROOT / "visualization" / "projects.json"


def load_projects_registry() -> list:
    """加载已注册的项目列表"""
    if PROJECTS_REGISTRY.exists():
        try:
            return json.loads(PROJECTS_REGISTRY.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_projects_registry(projects: list):
    """保存项目注册表"""
    PROJECTS_REGISTRY.write_text(
        json.dumps(projects, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def register_project(path_str: str) -> list:
    """注册一个项目路径，返回更新后的列表"""
    path = Path(path_str).resolve()
    if not path.exists():
        return load_projects_registry()

    projects = load_projects_registry()
    normalized = str(path)

    # 去重
    existing_paths = [p["path"] for p in projects]
    if normalized not in existing_paths:
        projects.append({
            "path": normalized,
            "name": path.name,
            "added": datetime.now().isoformat(),
        })
        save_projects_registry(projects)

    return projects


def read_active_mode(claude_dir: Path) -> dict | None:
    """读取 .claude/active-mode.json 标记文件"""
    marker = claude_dir / "active-mode.json"
    if not marker.exists():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        # 检查是否过期（超过 2 小时自动失效）
        started = data.get("started_at", "")
        if started:
            try:
                dt = datetime.fromisoformat(started)
                now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
                if (now - dt).total_seconds() > 7200:
                    return None
            except (ValueError, TypeError):
                pass
        return data
    except (json.JSONDecodeError, OSError):
        return None


def write_active_mode(claude_dir: Path, mode: str, step: str = ""):
    """写入活跃模式标记"""
    claude_dir.mkdir(parents=True, exist_ok=True)
    marker = claude_dir / "active-mode.json"
    data = {
        "mode": mode,
        "started_at": datetime.now().isoformat(),
        "step": step,
    }
    marker.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_active_mode(claude_dir: Path):
    """清除活跃模式标记"""
    marker = claude_dir / "active-mode.json"
    if marker.exists():
        marker.unlink()


def scan_project_status(project_path: Path) -> dict:
    """扫描目标工程的 mode pipeline 状态"""
    claude_dir = project_path / ".claude"
    knowledge_dir = claude_dir / "knowledge"

    active_data = read_active_mode(claude_dir)

    status = {
        "project_path": str(project_path),
        "project_name": project_path.name,
        "timestamp": datetime.now().isoformat(),
        "active_mode": active_data.get("mode") if active_data else None,
        "active_step": active_data.get("step", "") if active_data else "",
        "survey": scan_survey(knowledge_dir),
        "plan": scan_plan(claude_dir),
        "deploy": scan_deploy(project_path, claude_dir),
        "skills": scan_skills(claude_dir),
        "learn": scan_learn(),
        "signals": scan_signals(),
        "rules": scan_rules(),
    }
    return status


def scan_survey(knowledge_dir: Path) -> dict:
    """检查 /survey 产出"""
    result = {
        "status": "not_started",
        "profile": None,
        "readiness": None,
        "modules": [],
        "pain_points": None,
    }

    profile_path = knowledge_dir / "profile.json"
    if profile_path.exists():
        try:
            result["profile"] = json.loads(profile_path.read_text(encoding="utf-8"))
            result["status"] = "completed"
        except (json.JSONDecodeError, OSError):
            result["status"] = "error"

    readiness_path = knowledge_dir / "ai-readiness.json"
    if readiness_path.exists():
        try:
            result["readiness"] = json.loads(readiness_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    modules_dir = knowledge_dir / "modules"
    if modules_dir.exists():
        for f in sorted(modules_dir.glob("*.md")):
            content = f.read_text(encoding="utf-8", errors="replace")
            # 提取 frontmatter name
            name_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
            name = name_match.group(1) if name_match else f.stem
            result["modules"].append({"file": f.name, "name": name})

    pain_path = knowledge_dir / "pain-points.md"
    if pain_path.exists():
        content = pain_path.read_text(encoding="utf-8", errors="replace")
        # 统计 P0/P1/P2 数量
        p0 = len(re.findall(r"\bP0\b", content))
        p1 = len(re.findall(r"\bP1\b", content))
        p2 = len(re.findall(r"\bP2\b", content))
        result["pain_points"] = {"P0": p0, "P1": p1, "P2": p2, "total": p0 + p1 + p2}

    # 如果有 modules 但没 profile，说明调研进行中
    if result["status"] == "not_started" and result["modules"]:
        result["status"] = "in_progress"
    if result["status"] == "not_started" and knowledge_dir.exists():
        # knowledge 目录存在但没 profile
        items = list(knowledge_dir.iterdir()) if knowledge_dir.exists() else []
        if items:
            result["status"] = "in_progress"

    return result


def scan_plan(claude_dir: Path) -> dict:
    """检查 /mode-plan 产出"""
    result = {
        "status": "not_started",
        "phases": [],
        "total_tasks": 0,
        "completed_tasks": 0,
    }

    plan_path = claude_dir / "plan.md"
    if not plan_path.exists():
        return result

    content = plan_path.read_text(encoding="utf-8", errors="replace")
    result["status"] = "completed"

    # 解析阶段和任务
    current_phase = None
    for line in content.splitlines():
        # 阶段标题: ## 阶段 1: xxx 或 ### Phase 1: xxx
        phase_match = re.match(r"^#{2,3}\s+(?:阶段|Phase)\s*(\d+)[：:]\s*(.+)", line)
        if phase_match:
            current_phase = {
                "id": int(phase_match.group(1)),
                "name": phase_match.group(2).strip(),
                "tasks": [],
            }
            result["phases"].append(current_phase)
            continue

        # 任务: - [x] 或 - [ ]
        task_match = re.match(r"^\s*-\s+\[([ xX])\]\s+(.+)", line)
        if task_match and current_phase is not None:
            done = task_match.group(1).lower() == "x"
            task_text = task_match.group(2).strip()
            # 提取 mode 标签
            mode_match = re.search(r"\b(deploy|skills|code|manual)\b", task_text, re.IGNORECASE)
            mode = mode_match.group(1).lower() if mode_match else "code"
            current_phase["tasks"].append({
                "text": task_text,
                "done": done,
                "mode": mode,
            })
            result["total_tasks"] += 1
            if done:
                result["completed_tasks"] += 1

    if result["total_tasks"] > 0 and result["completed_tasks"] < result["total_tasks"]:
        result["status"] = "in_progress"

    return result


## Hook 用途描述映射（从 guard-patterns / 脚本注释提取）
HOOK_PURPOSES = {
    "pre-bash-guard": "拦截危险命令(rm -rf/mkfs)、敏感文件检测(.env/credentials)、密钥泄露扫描",
    "pre-edit-guard": "保护路径守卫，阻止修改 node_modules/.git/vendor 等受保护路径",
    "post-edit-verify": "编辑后自检：检测新增的 console.log/Debug.Log/TODO 调试语句",
    "anti-rationalization": "偷懒检测：识别 AI 回复中的推脱、跳过、未完成模式",
    "instinct-extract": "经验提取：从对话中自动提炼可复用的经验模式",
    "session-start": "会话启动：注入上次 session 摘要 + 最近经验 + 环境检查",
    "session-save": "会话结束：保存 session 摘要，供下次启动注入",
    "pre-compact-inject": "compact 前注入关键上下文，防止压缩丢失重要信息",
    "stop-format": "输出格式守卫：确保 AI 输出符合格式规范",
    "evolution-score": "进化评分：记录每次交互的正/负信号到 scores.jsonl",
    "pre-commit": "提交前检查：lint、测试、格式化",
    "commit-msg": "提交消息格式检查：enforcing conventional commits",
    "pre-push": "推送门禁：确保通过 review 才能 push",
}


def extract_hook_detail(hook_path: Path, name: str) -> dict:
    """提取单个 hook 的详细信息"""
    purpose = HOOK_PURPOSES.get(name, "")
    info = {"name": name, "purpose": purpose, "exists": hook_path.exists()}

    if hook_path.exists():
        try:
            content = hook_path.read_text(encoding="utf-8", errors="replace")
            # 尝试从脚本头部注释提取描述
            if not purpose:
                for line in content.splitlines()[:10]:
                    if line.startswith("#") and len(line) > 3 and not line.startswith("#!"):
                        purpose = line.lstrip("# ").strip()
                        if len(purpose) > 5:
                            info["purpose"] = purpose
                            break
            info["lines"] = len(content.splitlines())
        except OSError:
            pass

    return info


def extract_settings_summary(claude_dir: Path) -> dict:
    """从 settings.json 提取关键配置摘要"""
    summary = {"hooks_count": 0, "permissions": [], "env_vars": [], "key_configs": []}

    for fname in ["settings.json", "settings.local.json"]:
        spath = claude_dir / fname
        if not spath.exists():
            continue
        try:
            data = json.loads(spath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        # hooks
        hooks = data.get("hooks", {})
        for event_hooks in hooks.values():
            if isinstance(event_hooks, list):
                summary["hooks_count"] += len(event_hooks)

        # permissions
        perms = data.get("permissions", {})
        for ptype, rules in perms.items():
            if isinstance(rules, list):
                for r in rules[:5]:
                    if isinstance(r, str):
                        summary["permissions"].append(r)

        # env
        env = data.get("env", {})
        summary["env_vars"] = list(env.keys())[:5]

    return summary


def extract_claude_md_summary(project_path: Path) -> list:
    """从 CLAUDE.md 提取 h2 级别的章节标题作为关键要点"""
    claude_md = project_path / "CLAUDE.md"
    if not claude_md.exists():
        return []
    try:
        content = claude_md.read_text(encoding="utf-8", errors="replace")
        headings = []
        for line in content.splitlines():
            m = re.match(r"^##\s+(.+)", line)
            if m:
                headings.append(m.group(1).strip())
        return headings[:10]
    except OSError:
        return []


def scan_deploy(project_path: Path, claude_dir: Path) -> dict:
    """检查 /mode-deploy 产出，含各层关键要点摘要"""
    result = {
        "status": "not_started",
        "layers": [],  # 改为结构化的层列表
    }

    # Layer 1: Git Hooks — 本地守卫
    hooks_dir = project_path / ".git" / "hooks"
    claude_hooks_dir = claude_dir / "hooks"
    hook_details = []
    # 标准 git hooks
    for h in ["pre-commit", "commit-msg", "pre-push"]:
        hook_details.append(extract_hook_detail(hooks_dir / h, h))
    # Claude hooks (settings.json 配置的)
    if claude_hooks_dir.exists():
        for f in sorted(claude_hooks_dir.glob("*.sh")):
            name = f.stem
            if name not in [d["name"] for d in hook_details]:
                hook_details.append(extract_hook_detail(f, name))

    installed_hooks = [h for h in hook_details if h["exists"]]
    missing_hooks = [h for h in hook_details if not h["exists"] and h["name"] in ["pre-commit", "commit-msg", "pre-push"]]

    result["layers"].append({
        "name": "本地守卫 (Hooks)",
        "summary": "拦截危险操作、格式检查、敏感信息扫描 —— 错误在本地就被挡住",
        "items": hook_details,
        "ok_count": len(installed_hooks),
        "total_count": len(hook_details),
        "missing": [h["name"] for h in missing_hooks],
    })

    # Layer 2: CI Pipeline — 远程验证
    ci_items = []
    ci_dir = project_path / ".github" / "workflows"
    if ci_dir.exists():
        for f in sorted(ci_dir.glob("*.yml")):
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                # 提取 name 字段
                nm = re.search(r"^name:\s*(.+)$", content, re.MULTILINE)
                name = nm.group(1).strip().strip("'\"") if nm else f.stem
                ci_items.append({"file": f.name, "name": name})
            except OSError:
                ci_items.append({"file": f.name, "name": f.stem})

    result["layers"].append({
        "name": "CI Pipeline",
        "summary": "PR 合并前自动跑测试、lint、构建 —— 坏代码进不了主分支",
        "items": ci_items,
        "ok_count": len(ci_items),
    })

    # Layer 3: Settings 配置 — AI 行为约束
    settings_summary = extract_settings_summary(claude_dir)
    settings_exists = (claude_dir / "settings.json").exists() or (claude_dir / "settings.local.json").exists()

    result["layers"].append({
        "name": "AI 行为配置 (settings.json)",
        "summary": "定义 hooks 触发时机、权限边界、环境变量 —— AI 的行为框架",
        "exists": settings_exists,
        "detail": settings_summary,
    })

    # Layer 4: CLAUDE.md — 项目规则
    claude_md_exists = (project_path / "CLAUDE.md").exists()
    claude_md_headings = extract_claude_md_summary(project_path)

    result["layers"].append({
        "name": "项目规则 (CLAUDE.md)",
        "summary": "项目结构、编码规范、验证命令、编辑规则 —— AI 的行动手册",
        "exists": claude_md_exists,
        "headings": claude_md_headings,
    })

    # 整体状态
    hooks_ok = len(missing_hooks) == 0 and len(installed_hooks) > 0
    has_anything = installed_hooks or ci_items or settings_exists or claude_md_exists
    if hooks_ok and settings_exists and claude_md_exists:
        result["status"] = "completed"
    elif has_anything:
        result["status"] = "in_progress"

    return result


def parse_skill_content(content: str) -> dict:
    """解析 SKILL.md 的结构，提取关键段落"""
    sections = []
    current_heading = None
    current_body = []

    for line in content.splitlines():
        heading_match = re.match(r"^(#{1,3})\s+(.+)", line)
        if heading_match:
            if current_heading:
                sections.append({
                    "heading": current_heading,
                    "body_preview": "\n".join(current_body[:5]).strip(),
                    "line_count": len(current_body),
                })
            current_heading = heading_match.group(2).strip()
            current_body = []
        elif current_heading and line.strip():
            current_body.append(line.strip())

    if current_heading:
        sections.append({
            "heading": current_heading,
            "body_preview": "\n".join(current_body[:5]).strip(),
            "line_count": len(current_body),
        })

    return sections


def scan_skills(claude_dir: Path) -> dict:
    """检查 /mode-skills 产出，含当前正在创建的 skill 详情"""
    result = {
        "status": "not_started",
        "skills": [],
        "current_skill": None,  # 最近修改的 skill 详情
    }

    skills_dir = claude_dir / "skills"
    if not skills_dir.exists():
        return result

    latest_mtime = 0
    latest_skill = None

    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        content = skill_md.read_text(encoding="utf-8", errors="replace")

        # 基础信息
        name = skill_dir.name
        desc = ""
        name_match = re.search(r"^name:\s*(.+)$", content, re.MULTILINE)
        if name_match:
            name = name_match.group(1).strip().strip('"')
        desc_match = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)
        if desc_match:
            desc = desc_match.group(1).strip().strip('"')

        scripts = list(skill_dir.glob("scripts/*.sh")) + list(skill_dir.glob("*.sh"))

        result["skills"].append({
            "name": name,
            "dir": skill_dir.name,
            "description": desc,
            "has_scripts": len(scripts) > 0,
            "script_count": len(scripts),
        })

        # 找最近修改的 skill
        mtime = skill_md.stat().st_mtime
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest_skill = {
                "name": name,
                "dir": skill_dir.name,
                "description": desc,
                "script_count": len(scripts),
                "sections": parse_skill_content(content),
                "total_lines": len(content.splitlines()),
                "modified_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
            }

    if result["skills"]:
        result["status"] = "completed"

    # 只在 mode-skills 活跃时或有最近修改时，附上详情
    result["current_skill"] = latest_skill

    return result


def scan_learn() -> dict:
    """读取 learning-backlog.jsonl"""
    result = {
        "status": "not_started",
        "entries": [],
        "summary": {"total": 0, "digested": 0, "deferred": 0, "pending": 0},
    }

    backlog_path = FRAMEWORK_ROOT / "learning-backlog.jsonl"
    if not backlog_path.exists():
        return result

    for line in backlog_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            result["entries"].append(entry)
            st = entry.get("status", "pending")
            result["summary"]["total"] += 1
            if st == "digested":
                result["summary"]["digested"] += 1
            elif st == "deferred":
                result["summary"]["deferred"] += 1
            else:
                result["summary"]["pending"] += 1
        except json.JSONDecodeError:
            continue

    if result["summary"]["total"] > 0:
        if result["summary"]["pending"] > 0:
            result["status"] = "in_progress"
        else:
            result["status"] = "completed"

    return result


def scan_signals() -> dict:
    """读取 scores.jsonl 最近信号"""
    result = {"entries": [], "summary": {"total": 0, "pos": 0, "neg": 0}}

    scores_path = FRAMEWORK_ROOT / ".claude" / "evolution" / "scores.jsonl"
    if not scores_path.exists():
        return result

    lines = scores_path.read_text(encoding="utf-8", errors="replace").splitlines()
    # 只取最近 50 条
    recent = lines[-50:] if len(lines) > 50 else lines
    for line in recent:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            result["entries"].append(entry)
            result["summary"]["total"] += 1
            result["summary"]["pos"] += entry.get("pos", 0)
            result["summary"]["neg"] += entry.get("neg", 0)
        except json.JSONDecodeError:
            continue

    return result


def scan_rules() -> dict:
    """读取 rules-catalog.json"""
    rules_path = FRAMEWORK_ROOT / "templates" / "evolution" / "rules-catalog.json"
    if not rules_path.exists():
        return {"rules": []}
    try:
        data = json.loads(rules_path.read_text(encoding="utf-8"))
        return {"rules": data.get("rules", [])}
    except (json.JSONDecodeError, OSError):
        return {"rules": []}


class DashboardHandler(SimpleHTTPRequestHandler):
    """处理静态文件和 API 请求"""

    project_path = None

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/api/status":
            # 支持 ?project=<path> 查看指定项目
            target = self.project_path
            if "project" in params:
                candidate = Path(params["project"][0])
                if candidate.exists():
                    target = candidate
            self.send_json(scan_project_status(target))
        elif path == "/api/status-all":
            # 返回所有已注册项目的状态
            projects = load_projects_registry()
            all_status = []
            for p in projects:
                pp = Path(p["path"])
                if pp.exists():
                    all_status.append(scan_project_status(pp))
            self.send_json({"projects": all_status, "timestamp": datetime.now().isoformat()})
        elif path == "/api/ping":
            self.send_json({"ok": True, "ts": time.time()})
        elif path == "/api/projects":
            projects = load_projects_registry()
            current = str(self.project_path)
            self.send_json({
                "current": current,
                "current_name": self.project_path.name,
                "projects": projects,
            })
        elif path == "/api/switch":
            # 切换当前项目: /api/switch?project=<path>
            if "project" in params:
                new_path = Path(params["project"][0]).resolve()
                if new_path.exists():
                    DashboardHandler.project_path = new_path
                    register_project(str(new_path))
                    print(f"  >> 切换到: {new_path.name} ({new_path})")
                    self.send_json({"ok": True, "project": str(new_path), "name": new_path.name})
                else:
                    self.send_json({"ok": False, "error": f"路径不存在: {new_path}"})
            else:
                self.send_json({"ok": False, "error": "缺少 project 参数"})
        elif path == "/api/set-mode":
            # /api/set-mode?project=<path>&mode=survey&step=xxx
            mode_val = params.get("mode", [""])[0]
            step_val = params.get("step", [""])[0]
            target = self.project_path
            if "project" in params:
                candidate = Path(params["project"][0])
                if candidate.exists():
                    target = candidate
            if mode_val:
                write_active_mode(target / ".claude", mode_val, step_val)
                self.send_json({"ok": True, "mode": mode_val, "project": str(target)})
            else:
                self.send_json({"ok": False, "error": "缺少 mode 参数"})
        elif path == "/api/clear-mode":
            target = self.project_path
            if "project" in params:
                candidate = Path(params["project"][0])
                if candidate.exists():
                    target = candidate
            clear_active_mode(target / ".claude")
            self.send_json({"ok": True})
        elif path == "/api/register":
            # 注册新项目: /api/register?project=<path>
            if "project" in params:
                new_path = Path(params["project"][0]).resolve()
                if new_path.exists():
                    projects = register_project(str(new_path))
                    self.send_json({"ok": True, "projects": projects})
                else:
                    self.send_json({"ok": False, "error": f"路径不存在: {new_path}"})
            else:
                self.send_json({"ok": False, "error": "缺少 project 参数"})
        elif path == "/":
            self.path = "/index.html"
            return self.serve_no_cache()
        else:
            return self.serve_no_cache()

    def serve_no_cache(self):
        """服务静态文件并禁止缓存"""
        SimpleHTTPRequestHandler.do_GET(self)

    def end_headers(self):
        # 所有响应都加 no-cache
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        SimpleHTTPRequestHandler.end_headers(self)

    def send_json(self, data):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        if args and "404" in str(args[0]):
            super().log_message(format, *args)


def main():
    parser = argparse.ArgumentParser(description="AI for Better 可视化面板")
    parser.add_argument("--project", "-p", required=True, help="目标工程路径")
    parser.add_argument("--port", type=int, default=PORT, help=f"端口号 (默认 {PORT})")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    project_path = Path(args.project).resolve()
    if not project_path.exists():
        print(f"错误: 目标工程路径不存在: {project_path}")
        sys.exit(1)

    DashboardHandler.project_path = project_path

    # 注册启动时指定的项目
    register_project(str(project_path))

    # 切换到 visualization 目录以便服务静态文件
    os.chdir(Path(__file__).parent)

    server = HTTPServer(("127.0.0.1", args.port), DashboardHandler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"╔══════════════════════════════════════════╗")
    print(f"║  AI for Better - Mode Pipeline Dashboard ║")
    print(f"╠══════════════════════════════════════════╣")
    print(f"║  目标工程: {project_path.name:<29s}║")
    print(f"║  地址:     {url:<29s}║")
    print(f"║  Ctrl+C 退出                             ║")
    print(f"╚══════════════════════════════════════════╝")

    if not args.no_open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
        server.server_close()


if __name__ == "__main__":
    main()
