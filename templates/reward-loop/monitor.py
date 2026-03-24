#!/usr/bin/env python3
"""
monitor.py — 实时项目健康监控面板

本地 HTTP 服务，浏览器打开即可查看：
  - 部署流水线（做了什么、特殊处理）
  - 项目 Profile（语言/框架/启用了哪些能力）
  - 风险预警（FAIL / WARN 项）
  - 实时健康状态（信号采集 + 判定）

用法:
  python monitor.py <project_dir> [--port 8420]

自动打开浏览器 http://localhost:8420
"""

import http.server
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path


# ── 数据采集 ──────────────────────────────────────────────

class ProjectMonitor:
    """持续采集项目状态，供 HTTP API 返回"""

    def __init__(self, project_dir):
        self.project_dir = os.path.abspath(project_dir)
        self.data = {
            "project_name": os.path.basename(self.project_dir),
            "project_dir": self.project_dir,
            "last_updated": "",
            "deploy": {},
            "verify": {},
            "profile": {},
            "risks": [],
            "health": {},
            "hooks_summary": {},
            "git_status": {},
        }
        self._lock = threading.Lock()

    def _p(self, *parts):
        return os.path.join(self.project_dir, *parts)

    def collect_all(self):
        """一次完整采集"""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        deploy = self._collect_deploy()
        verify = self._collect_verify()
        profile = self._collect_profile()
        risks = self._collect_risks(verify)
        health = self._collect_health()
        hooks = self._collect_hooks()
        git = self._collect_git()
        plan = self._collect_plan()
        briefs = self._generate_briefs(deploy, verify, profile, risks, health, hooks, git)

        with self._lock:
            self.data.update({
                "last_updated": now,
                "deploy": deploy,
                "verify": verify,
                "profile": profile,
                "risks": risks,
                "health": health,
                "hooks_summary": hooks,
                "git_status": git,
                "briefs": briefs,
                "plan": plan,
            })

    def get_data(self):
        with self._lock:
            return dict(self.data)

    # ── deploy log ──

    def _collect_deploy(self):
        path = self._p(".deploy", "deploy-log.jsonl")
        steps = []
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line:
                    try:
                        steps.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return {"steps": steps, "count": len(steps)}

    # ── verify result ──

    def _collect_verify(self):
        path = self._p(".deploy", "verify-result.json")
        if not os.path.exists(path):
            return {"overall": "NOT_RUN", "summary": "未运行验证", "sections": {}}
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"overall": "ERROR", "summary": "读取失败", "sections": {}}

    # ── profile / project-specific ──

    def _collect_profile(self):
        info = {"language": "unknown", "framework": "unknown", "features": {}}

        # 从 deploy log 提取
        path = self._p(".deploy", "deploy-log.jsonl")
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                try:
                    entry = json.loads(line.strip())
                except Exception:
                    continue
                step = entry.get("step", "")
                detail = entry.get("detail", "")
                if "项目检测" in step or "project" in step.lower():
                    parts = detail.split("/")
                    if len(parts) >= 1:
                        info["language"] = parts[0].strip()
                    if len(parts) >= 2:
                        info["framework"] = parts[1].strip()
                if "Profile" in step:
                    info["profile_name"] = detail.strip()

        # 检测启用的能力
        features = {}
        features["claude_hooks"] = os.path.isdir(self._p(".claude", "hooks"))
        features["rules"] = os.path.isdir(self._p(".claude", "rules"))
        features["agents"] = os.path.isdir(self._p(".claude", "agents"))
        features["reward_loop"] = os.path.isdir(self._p(".reward-loop"))
        features["security_signal"] = os.path.isdir(self._p(".security"))
        features["quality_signal"] = os.path.isdir(self._p(".quality"))
        features["test_signal"] = os.path.isdir(self._p(".test-system"))
        features["perf_signal"] = os.path.isdir(self._p(".perf-system"))
        features["github_actions"] = os.path.isdir(self._p(".github", "workflows"))

        # pre-commit 框架 or husky or raw hooks
        if os.path.exists(self._p(".pre-commit-config.yaml")):
            features["hook_framework"] = "pre-commit"
        elif os.path.isdir(self._p(".husky")):
            features["hook_framework"] = "husky"
        else:
            features["hook_framework"] = "raw (.git/hooks)"

        # 项目特殊配置
        specials = []
        pccy = self._p(".pre-commit-config.yaml")
        if os.path.exists(pccy):
            content = open(pccy, encoding="utf-8", errors="replace").read()
            if "check-file-size" in content:
                specials.append("500 行文件大小限制 (pre-commit)")
            if "commit-msg-format" in content:
                specials.append("Commit 格式校验 (pre-commit)")
            if "pre-push" in content:
                specials.append("Pre-push 测试门禁 (pre-commit)")

        gp = self._p(".claude", "hooks", "guard-patterns.conf")
        if os.path.exists(gp):
            content = open(gp, encoding="utf-8", errors="replace").read()
            if "venv" in content or "__pycache__" in content:
                specials.append("Python 保护路径 (venv/__pycache__)")

        info["features"] = features
        info["specials"] = specials
        return info

    # ── risks ──

    def _collect_risks(self, verify):
        risks = []
        sections = verify.get("sections", {})
        for sec_key, section in sections.items():
            for check in section.get("checks", []):
                status = check.get("status", "")
                if status == "FAIL":
                    risks.append({
                        "level": "error",
                        "section": section.get("label", sec_key),
                        "name": check["name"],
                        "detail": check.get("detail", ""),
                    })
                elif status == "WARN":
                    risks.append({
                        "level": "warn",
                        "section": section.get("label", sec_key),
                        "name": check["name"],
                        "detail": check.get("detail", ""),
                    })

        # 额外风险检测
        if not os.path.exists(self._p(".reward-loop", "signals.yaml")):
            risks.append({
                "level": "error",
                "section": "进化管道",
                "name": "signals.yaml 缺失",
                "detail": "全自动进化循环无法运行",
            })

        # 检查 settings.json 是否有自定义 hooks 被覆盖的风险
        sj = self._p(".claude", "settings.json")
        if os.path.exists(sj):
            try:
                settings = json.load(open(sj, encoding="utf-8"))
                hook_count = sum(
                    len(entries) for entries in settings.get("hooks", {}).values()
                )
                if hook_count < 5:
                    risks.append({
                        "level": "warn",
                        "section": "配置",
                        "name": "Hooks 数量偏少",
                        "detail": f"只有 {hook_count} 个 hook 条目，可能有遗漏",
                    })
            except Exception:
                pass

        return risks

    # ── live health (signal collectors) ──

    def _collect_health(self):
        """轻量健康检查：检查各信号目录是否完整"""
        signals = {}
        for name, sig_dir, required in [
            ("security", ".security", ["collector.sh", "judge.py"]),
            ("quality", ".quality", ["collector.sh", "judge.py"]),
            ("test", ".test-system", ["test_judge.py"]),
            ("perf", ".perf-system", ["collector.sh"]),
        ]:
            d = self._p(sig_dir)
            if not os.path.isdir(d):
                signals[name] = {"status": "not_deployed", "detail": "未部署"}
                continue
            files = os.listdir(d)
            missing = [r for r in required if not any(r in f for f in files)]
            if missing:
                signals[name] = {
                    "status": "incomplete",
                    "detail": f"缺少: {', '.join(missing)}",
                }
            else:
                signals[name] = {"status": "ready", "detail": "就绪"}

        # 检查最近的健康报告
        report_path = self._p(".signals", "health-report.md")
        last_report = None
        if os.path.exists(report_path):
            mtime = os.path.getmtime(report_path)
            last_report = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC"
            )

        return {"signals": signals, "last_report": last_report}

    # ── hooks summary ──

    def _collect_hooks(self):
        sj = self._p(".claude", "settings.json")
        if not os.path.exists(sj):
            return {"total": 0, "events": {}}
        try:
            settings = json.load(open(sj, encoding="utf-8"))
            hooks = settings.get("hooks", {})
            events = {}
            total = 0
            for event, entries in hooks.items():
                names = []
                for entry in entries:
                    for h in entry.get("hooks", []):
                        cmd = h.get("command", "")
                        # 提取脚本名
                        parts = cmd.replace("\\", "/").split("/")
                        names.append(parts[-1] if parts else cmd)
                        total += 1
                events[event] = names
            return {"total": total, "events": events}
        except Exception:
            return {"total": 0, "events": {}}

    # ── git status ──

    def _collect_git(self):
        try:
            r = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, timeout=5,
                cwd=self.project_dir,
            )
            lines = r.stdout.decode("utf-8", errors="replace").strip().split("\n")
            lines = [l for l in lines if l.strip()]
            branch = "unknown"
            try:
                br = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True, timeout=5,
                    cwd=self.project_dir,
                )
                branch = br.stdout.decode().strip()
            except Exception:
                pass
            return {
                "branch": branch,
                "dirty_files": len(lines),
                "changes": lines[:20],
            }
        except Exception:
            return {"branch": "unknown", "dirty_files": 0, "changes": []}

    # ── 部署计划 ──

    def _collect_plan(self):
        path = self._p(".deploy", "plan.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    # ── 大白话简报 ──

    def _generate_briefs(self, deploy, verify, profile, risks, health, hooks, git):
        """为每个区域生成一句大白话汇报"""
        briefs = {}

        # ── 总览 ──
        p = verify.get("pass_count", 0)
        t = verify.get("total", 1)
        skip = verify.get("skip_count", 0)
        applicable = verify.get("applicable", t)
        o = verify.get("overall", "")
        if o == "PASS" and applicable == p:
            briefs["score"] = f"适用的 {applicable} 项检查全部通过，AI 可以放心干活了。"
            if skip > 0:
                briefs["score"] += f"另有 {skip} 项因不适用而跳过（正常）。"
        elif o == "PASS":
            briefs["score"] = f"适用 {applicable} 项中 {p} 项通过，没有失败项。{skip} 项跳过。"
        else:
            fail = t - p - skip
            briefs["score"] = f"适用 {applicable} 项中有 {fail} 项未通过，需要关注。"

        # ── 部署流水线 ──
        steps = deploy.get("steps", [])
        ok = sum(1 for s in steps if s.get("status") == "success")
        fail = sum(1 for s in steps if s.get("status") == "fail")
        if not steps:
            briefs["deploy"] = "还没有部署记录。运行 deploy.sh 可以一键配置整个 AI 开发环境。"
        elif fail > 0:
            briefs["deploy"] = f"部署执行了 {len(steps)} 步，其中 {fail} 步失败了，需要排查原因。"
        else:
            briefs["deploy"] = f"部署已完成，{len(steps)} 个步骤全部成功。环境已就位，可以直接开始使用。"

        # ── 项目 Profile ──
        lang = profile.get("language", "unknown")
        fw = profile.get("framework", "unknown")
        pname = profile.get("profile_name", "")
        feats = profile.get("features", {})
        specials = profile.get("specials", [])

        on_count = sum(1 for v in feats.values() if v and v is not True or v is True)
        # 简单统计启用的 bool 特性
        on_list = [k for k, v in feats.items() if v is True]

        if fw and fw != "unknown":
            briefs["profile"] = f"检测到这是一个 {lang} + {fw} 项目，已自动加载 {pname} 配置方案。"
        else:
            briefs["profile"] = f"检测到这是一个 {lang} 项目，已自动加载 {pname} 配置方案。"

        if specials:
            briefs["profile"] += f"针对这个项目做了 {len(specials)} 项专属定制。"
        else:
            briefs["profile"] += "使用的是通用配置，没有额外的定制项。"

        hf = feats.get("hook_framework", "")
        if hf == "pre-commit":
            briefs["profile"] += "代码提交规范由 pre-commit 框架管理，新同事 clone 后一行命令就能启用。"
        elif hf == "husky":
            briefs["profile"] += "代码提交规范由 husky 管理，npm install 后自动生效。"

        # ── 风险预警 ──
        errors = [r for r in risks if r["level"] == "error"]
        warns = [r for r in risks if r["level"] == "warn"]
        if not risks:
            briefs["risks"] = "目前没有发现任何风险，环境运行正常。"
        elif errors:
            names = "、".join(r["name"] for r in errors[:3])
            briefs["risks"] = f"发现 {len(errors)} 个严重问题需要尽快处理：{names}。"
            if warns:
                briefs["risks"] += f"另外还有 {len(warns)} 个小问题值得关注。"
        else:
            names = "、".join(r["name"] for r in warns[:3])
            briefs["risks"] = f"没有严重问题，但有 {len(warns)} 个小问题值得留意：{names}。"

        # ── 信号健康 ──
        sigs = health.get("signals", {})
        ready = [n for n, s in sigs.items() if s.get("status") == "ready"]
        incomplete = [n for n, s in sigs.items() if s.get("status") == "incomplete"]
        not_dep = [n for n, s in sigs.items() if s.get("status") == "not_deployed"]
        sig_names = {"security": "安全扫描", "quality": "代码质量", "test": "测试", "perf": "性能"}

        if len(ready) == len(sigs) and sigs:
            briefs["health"] = "所有信号系统都已就绪，可以自动检测代码的安全、质量、测试和性能问题。"
        elif not sigs:
            briefs["health"] = "还没有配置任何信号系统。信号系统能自动发现代码问题，建议部署。"
        else:
            parts = []
            if ready:
                parts.append(f"{', '.join(sig_names.get(n, n) for n in ready)}已就绪")
            if incomplete:
                parts.append(f"{', '.join(sig_names.get(n, n) for n in incomplete)}配置不完整")
            if not_dep:
                parts.append(f"{', '.join(sig_names.get(n, n) for n in not_dep)}还没部署")
            briefs["health"] = "；".join(parts) + "。"

        lr = health.get("last_report")
        if lr:
            briefs["health"] += f"上次健康检查：{lr}。"

        # ── Hooks 总览 ──
        htotal = hooks.get("total", 0)
        events = hooks.get("events", {})
        event_names = {
            "PreToolUse": "代码编辑前",
            "PostToolUse": "代码编辑后",
            "SessionStart": "会话启动时",
            "PreCompact": "上下文压缩前",
            "Stop": "会话结束时",
        }
        if htotal == 0:
            briefs["hooks"] = "还没有配置自动化钩子。钩子能在 AI 写代码的各个环节自动把关。"
        else:
            ev_list = [event_names.get(e, e) for e in events.keys()]
            briefs["hooks"] = (
                f"共有 {htotal} 个自动化钩子在守护代码，"
                f"覆盖了{' / '.join(ev_list[:4])}等关键环节。"
                "AI 每次动手之前和之后都有自动检查，不用担心改坏东西。"
            )

        # ── 验证详情 ──
        sections = verify.get("sections", {})
        sec_briefs = []
        sec_names = {
            "git_hooks": ("Git 提交门禁", "每次提交代码前自动跑检查，提交格式不对或测试没过就不让提交"),
            "claude_hooks": ("Claude 守卫", "AI 写代码时的实时防护，防止改错文件、跑危险命令、偷懒跳过检查"),
            "assets": ("规则与智能体", "给 AI 配备的行为准则和专业分工，让它知道什么该做什么不该做"),
            "configs": ("项目配置", "编辑器统一配置、Git 属性、AI 上下文文件，让环境保持一致"),
            "atomization": ("原子化链路", "确保每次改动都是小而精的——文件不超 500 行、提交格式规范、不能跳过检查"),
            "evolution": ("进化管道", "全自动循环：AI 自己发现问题→修复→验证→合并，不需要人盯着"),
            "compatibility": ("兼容性检查", "检查部署的东西是否真的适合这个项目——语言对不对、配置会不会冲突、依赖装了没"),
        }
        for key, sec in sections.items():
            name, explain = sec_names.get(key, (sec.get("label", key), ""))
            pc = sec.get("pass_count", 0)
            tc = sec.get("total", 0)
            st = sec.get("status", "")
            if st == "PASS":
                sec_briefs.append(f"【{name}】全部通过 — {explain}")
            else:
                fc = tc - pc
                sec_briefs.append(f"【{name}】{fc} 项未通过 — {explain}")

        briefs["verify"] = "逐项检查结果：" + "。".join(sec_briefs[:3])
        if len(sec_briefs) > 3:
            briefs["verify"] += f"。以及另外 {len(sec_briefs) - 3} 个维度的检查。"
        briefs["verify"] += "点击每一行可以看到具体是哪个检查项通过或失败。"

        return briefs


# ── HTTP Server ──────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__PROJECT__ — 实时监控</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&display=swap');
:root {
  --bg:#050509;--bg2:#0a0a12;--bg3:#10101a;--bg4:#181824;--bg5:#1e1e2e;
  --border:rgba(255,255,255,.06);--border2:rgba(255,255,255,.1);
  --t1:#eeeef6;--t2:#8888a0;--t3:#555568;
  --green:#34d399;--green-dim:rgba(52,211,153,.12);
  --red:#f87171;--red-dim:rgba(248,113,113,.12);
  --blue:#60a5fa;--blue-dim:rgba(96,165,250,.1);
  --amber:#fbbf24;--amber-dim:rgba(251,191,36,.1);
  --purple:#a78bfa;--purple-dim:rgba(167,139,250,.1);
  --cyan:#22d3ee;--cyan-dim:rgba(34,211,238,.08);
  --glow-green:0 0 20px rgba(52,211,153,.15);
  --glow-red:0 0 20px rgba(248,113,113,.15);
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--t1);min-height:100vh;padding:24px;-webkit-font-smoothing:antialiased}
.container{max-width:1280px;margin:0 auto}

/* ── header ── */
.hdr{display:flex;justify-content:space-between;align-items:center;padding:24px 32px;
  background:linear-gradient(160deg,var(--bg3) 0%,var(--bg2) 100%);
  border:1px solid var(--border);border-radius:20px;margin-bottom:20px;position:relative;overflow:hidden}
.hdr::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.08),transparent)}
.hdr-left h1{font-size:24px;font-weight:800;letter-spacing:-0.5px;
  background:linear-gradient(135deg,var(--t1),var(--t2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hdr-left .path{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--t3);margin-top:6px}
.hdr-right{text-align:right}
.live-badge{display:inline-flex;align-items:center;gap:7px;padding:5px 14px;
  background:var(--green-dim);border:1px solid rgba(52,211,153,.2);border-radius:20px;
  font-size:11px;font-weight:700;color:var(--green);letter-spacing:1px}
.live-dot{width:7px;height:7px;border-radius:50%;background:var(--green);
  box-shadow:var(--glow-green);animation:pulse 2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.8)}}
.hdr-right .ts{font-size:10px;color:var(--t3);margin-top:6px;font-family:'JetBrains Mono',monospace}

/* ── score hero ── */
.score-hero{display:flex;align-items:center;gap:32px;padding:28px 36px;
  background:var(--bg3);border:1px solid var(--border);border-radius:18px;margin-bottom:20px;
  position:relative;overflow:hidden}
.score-hero::after{content:'';position:absolute;top:-40%;right:-10%;width:300px;height:300px;
  border-radius:50%;background:radial-gradient(circle,rgba(52,211,153,.04),transparent 70%);pointer-events:none}
.score-ring{position:relative;width:100px;height:100px;flex-shrink:0}
.score-ring svg{transform:rotate(-90deg);filter:drop-shadow(0 0 8px rgba(52,211,153,.2))}
.score-ring .num{position:absolute;top:50%;left:50%;transform:translate(-50%,-55%);font-size:32px;font-weight:900;letter-spacing:-1px}
.score-ring .lbl{position:absolute;top:50%;left:50%;transform:translate(-50%,14px);font-size:9px;color:var(--t3);text-transform:uppercase;letter-spacing:2px;font-weight:600}
.score-detail{flex:1}
.score-detail .status-text{font-size:18px;font-weight:800;margin-bottom:4px}
.score-detail .status-sub{font-size:12px;color:var(--t2)}
.score-counters{display:flex;gap:28px;margin-top:14px}
.score-counters .ct{text-align:center}
.score-counters .ct b{font-size:24px;font-weight:800;display:block;letter-spacing:-0.5px}
.score-counters .ct span{font-size:10px;color:var(--t3);font-weight:500}
.score-git{text-align:right;min-width:140px}
.score-git .branch{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--purple);
  background:var(--purple-dim);padding:4px 12px;border-radius:6px;display:inline-block}
.score-git .dirty{font-size:11px;color:var(--t3);margin-top:6px}

/* ── grid ── */
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
.full{grid-column:1/-1}

/* ── card ── */
.card{background:var(--bg3);border:1px solid var(--border);border-radius:16px;padding:22px;position:relative;overflow:hidden;
  transition:border-color .3s}
.card:hover{border-color:var(--border2)}
.card-title{font-size:11px;font-weight:700;color:var(--t3);text-transform:uppercase;letter-spacing:1.5px;
  margin-bottom:16px;display:flex;align-items:center;gap:8px}
.card-title .ct-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}

/* ── items ── */
.row{display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:10px;font-size:13px;
  transition:all .15s}
.row:hover{background:var(--bg4)}
.row-icon{width:22px;height:22px;border-radius:6px;display:flex;align-items:center;justify-content:center;
  font-size:11px;color:#fff;flex-shrink:0;font-weight:700}
.row-name{font-weight:600;flex:1}
.row-detail{color:var(--t2);font-size:11px;max-width:280px;text-align:right;font-family:'JetBrains Mono',monospace}

.bg-pass{background:var(--green)}.bg-fail{background:var(--red)}.bg-warn{background:var(--amber)}
.bg-skip{background:var(--t3)}.bg-info{background:var(--blue)}.bg-ready{background:var(--green)}
.bg-incomplete{background:var(--amber)}.bg-not_deployed{background:var(--t3)}

/* ── tags ── */
.tags{display:flex;flex-wrap:wrap;gap:6px}
.tag{font-size:10px;padding:5px 12px;border-radius:8px;font-weight:600;letter-spacing:0.3px;
  transition:all .2s}
.tag-on{background:var(--green-dim);color:var(--green);border:1px solid rgba(52,211,153,.2)}
.tag-off{background:rgba(255,255,255,.02);color:var(--t3);border:1px solid var(--border)}

/* ── risks ── */
.risk{padding:12px 16px;border-radius:10px;margin-bottom:8px;position:relative;overflow:hidden}
.risk::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;border-radius:3px}
.risk-error{background:var(--red-dim)}.risk-error::before{background:var(--red)}
.risk-warn{background:var(--amber-dim)}.risk-warn::before{background:var(--amber)}
.risk-badge{font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:4px}
.risk-error .risk-badge{color:var(--red)}.risk-warn .risk-badge{color:var(--amber)}
.risk-name{font-size:13px;font-weight:700}
.risk-detail{font-size:11px;color:var(--t2);margin-top:2px}
.risk-zero{display:flex;align-items:center;justify-content:center;gap:8px;padding:24px;
  color:var(--green);font-weight:600;font-size:13px;
  background:var(--green-dim);border-radius:10px}

/* ── pipeline ── */
.pipe-step{display:flex;align-items:flex-start;gap:14px;position:relative;padding:6px 0}
.pipe-track{display:flex;flex-direction:column;align-items:center;width:28px;flex-shrink:0}
.pipe-dot{width:28px;height:28px;border-radius:8px;display:flex;align-items:center;justify-content:center;
  color:#fff;font-size:12px;font-weight:700;position:relative;z-index:1}
.pipe-line{width:2px;flex:1;min-height:8px;background:var(--border);margin:2px 0}
.pipe-content{flex:1;padding-bottom:4px}
.pipe-content .step-name{font-size:13px;font-weight:600}
.pipe-content .step-detail{font-size:11px;color:var(--t2);margin-top:1px}
.pipe-content .step-time{font-size:10px;color:var(--t3);font-family:'JetBrains Mono',monospace;margin-top:2px}

/* ── specials ── */
.special-item{display:flex;align-items:center;gap:8px;padding:8px 0;
  border-bottom:1px solid var(--border);font-size:12px}
.special-item:last-child{border-bottom:none}
.special-dot{width:5px;height:5px;border-radius:50%;background:var(--cyan);flex-shrink:0;
  box-shadow:0 0 6px rgba(34,211,238,.4)}

/* ── hooks grid ── */
.hooks-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px}
.hook-group{background:var(--bg2);padding:14px 16px;border-radius:10px;border:1px solid var(--border)}
.hook-group-title{font-size:10px;font-weight:700;color:var(--cyan);text-transform:uppercase;
  letter-spacing:1px;margin-bottom:8px;display:flex;align-items:center;gap:6px}
.hook-group-title::before{content:'';width:4px;height:4px;border-radius:50%;background:var(--cyan)}
.hook-item{font-size:11px;color:var(--t2);padding:3px 0;font-family:'JetBrains Mono',monospace}

/* ── section header in verify ── */
.sec-hdr{display:flex;align-items:center;gap:10px;padding:10px 0 8px;margin-top:6px}
.sec-hdr .sec-dot{width:10px;height:10px;border-radius:50%}
.sec-hdr .sec-name{font-size:14px;font-weight:700}
.sec-hdr .sec-stat{font-size:11px;color:var(--t3);font-family:'JetBrains Mono',monospace}

footer{text-align:center;color:var(--t3);font-size:10px;margin-top:28px;padding:16px;
  border-top:1px solid var(--border);letter-spacing:0.5px}
footer a{color:var(--purple);text-decoration:none}

/* ── brief 大白话简报 ── */
.brief{font-size:12px;line-height:1.7;color:var(--t2);padding:12px 16px;margin-bottom:14px;
  background:linear-gradient(135deg,rgba(255,255,255,.02),rgba(255,255,255,.01));
  border:1px solid rgba(255,255,255,.04);border-radius:10px;border-left:3px solid var(--purple)}
.brief-score{font-size:13px;line-height:1.7;color:var(--t2);padding:10px 20px;margin-top:16px;
  background:rgba(255,255,255,.02);border-radius:10px;text-align:center}
</style>
</head>
<body>
<div class="container">

<div class="hdr">
  <div class="hdr-left">
    <h1 id="project-name">Loading...</h1>
    <div class="path" id="project-dir"></div>
  </div>
  <div class="hdr-right">
    <div class="live-badge" id="live-indicator"><span class="live-dot"></span>LIVE</div>
    <div class="ts" id="last-updated"></div>
  </div>
</div>

<div class="score-hero" id="score-hero"></div>
<div class="brief-score" id="brief-score"></div>

<!-- 项目画像 + 部署决策 -->
<div id="plan-section" style="display:none">
  <div class="card" style="margin-bottom:16px">
    <div class="card-title"><span class="ct-dot" style="background:var(--purple)"></span>项目画像</div>
    <div id="plan-portrait"></div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">
    <div class="card">
      <div class="card-title"><span class="ct-dot" style="background:var(--green)"></span>已部署（为什么装）</div>
      <div id="plan-deployed"></div>
    </div>
    <div class="card">
      <div class="card-title"><span class="ct-dot" style="background:var(--amber)"></span>已跳过（为什么不装）</div>
      <div id="plan-skipped"></div>
    </div>
  </div>
  <div id="plan-recs-card" class="card" style="margin-bottom:16px;display:none">
    <div class="card-title"><span class="ct-dot" style="background:var(--red)"></span>建议（需要人工处理）</div>
    <div id="plan-recs"></div>
  </div>
</div>

<div class="grid">
  <div class="card">
    <div class="card-title"><span class="ct-dot" style="background:var(--blue)"></span>部署流水线</div>
    <div class="brief" id="brief-deploy"></div>
    <div id="pipeline"></div>
  </div>
  <div class="card">
    <div class="card-title"><span class="ct-dot" style="background:var(--purple)"></span>项目 Profile</div>
    <div class="brief" id="brief-profile"></div>
    <div id="profile-info"></div>
    <div id="feature-tags" class="tags" style="margin-top:14px"></div>
    <div style="margin-top:14px"><div style="font-size:10px;color:var(--t3);font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">项目特殊处理</div><div id="specials"></div></div>
  </div>
  <div class="card">
    <div class="card-title"><span class="ct-dot" style="background:var(--red)"></span>风险预警</div>
    <div class="brief" id="brief-risks"></div>
    <div id="risks"></div>
  </div>
  <div class="card">
    <div class="card-title"><span class="ct-dot" style="background:var(--green)"></span>信号健康</div>
    <div class="brief" id="brief-health"></div>
    <div id="health"></div>
  </div>
  <div class="card full">
    <div class="card-title"><span class="ct-dot" style="background:var(--cyan)"></span>Hooks 总览 <span id="hook-count" style="color:var(--t3)"></span></div>
    <div class="brief" id="brief-hooks"></div>
    <div id="hooks"></div>
  </div>
  <div class="card full">
    <div class="card-title"><span class="ct-dot" style="background:var(--amber)"></span>验证详情</div>
    <div class="brief" id="brief-verify"></div>
    <div id="verify-detail"></div>
  </div>
</div>

<footer>AI for better &middot; 实时监控面板 &middot; 每 10 秒自动刷新</footer>
</div>

<script>
const API='/api/status';
function ic(s){return{PASS:'\u2713',FAIL:'\u2717',WARN:'\u26A0',SKIP:'\u2013',success:'\u2713',fail:'\u2717',skip:'\u2013'}[s]||'\u2022'}
function bg(s){return{PASS:'pass',FAIL:'fail',WARN:'warn',SKIP:'skip',success:'pass',fail:'fail',skip:'skip',ready:'ready',incomplete:'incomplete',not_deployed:'not_deployed'}[s]||'info'}

function render(d){
  document.getElementById('project-name').textContent=d.project_name;
  document.getElementById('project-dir').textContent=d.project_dir;
  document.getElementById('last-updated').textContent=d.last_updated;

  // ── Score Hero ──
  const v=d.verify,pass=v.pass_count||0,total=v.total||1,pct=Math.round(pass/total*100),fail=total-pass;
  const color=pct===100?'var(--green)':pct>=80?'var(--amber)':'var(--red)';
  const circ=2*Math.PI*42,dash=pct/100*circ;
  const g=d.git_status||{};
  document.getElementById('score-hero').innerHTML=`
    <div class="score-ring">
      <svg width="100" height="100" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(255,255,255,.04)" stroke-width="6"/>
        <circle cx="50" cy="50" r="42" fill="none" stroke="${color}" stroke-width="6"
          stroke-dasharray="${dash} ${circ-dash}" stroke-linecap="round"
          style="transition:stroke-dasharray .8s ease"/>
      </svg>
      <span class="num" style="color:${color}">${pct}</span>
      <span class="lbl">SCORE</span>
    </div>
    <div class="score-detail">
      <div class="status-text" style="color:${color}">${v.overall==='PASS'?'ALL SYSTEMS GO':v.overall==='FAIL'?'ISSUES DETECTED':'PENDING'}</div>
      <div class="status-sub">${v.summary||''}</div>
      <div class="score-counters">
        <div class="ct"><b style="color:var(--green)">${pass}</b><span>通过</span></div>
        <div class="ct"><b style="color:var(--red)">${fail}</b><span>未通过</span></div>
        <div class="ct"><b style="color:var(--blue)">${total}</b><span>总计</span></div>
      </div>
    </div>
    <div class="score-git">
      <div class="branch">${g.branch||'?'}</div>
      <div class="dirty">${g.dirty_files||0} 个未提交文件</div>
    </div>`;

  // ── Pipeline ──
  const steps=d.deploy.steps||[];
  let ph='';
  steps.forEach((s,i)=>{
    const dc=s.status==='success'?'var(--green)':s.status==='fail'?'var(--red)':'var(--t3)';
    ph+=`<div class="pipe-step">
      <div class="pipe-track"><div class="pipe-dot" style="background:${dc}">${ic(s.status)}</div>${i<steps.length-1?'<div class="pipe-line"></div>':''}</div>
      <div class="pipe-content"><div class="step-name">${s.step||''}</div><div class="step-detail">${s.detail||''}</div>${s.ts?`<div class="step-time">${s.ts}</div>`:''}</div>
    </div>`;
  });
  document.getElementById('pipeline').innerHTML=ph||'<div style="color:var(--t3);font-size:12px;padding:12px">暂无部署记录</div>';

  // ── Profile ──
  const p=d.profile;
  document.getElementById('profile-info').innerHTML=`
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
      <div style="background:var(--bg2);padding:10px 14px;border-radius:8px"><div style="font-size:9px;color:var(--t3);font-weight:700;text-transform:uppercase;letter-spacing:1px">语言</div><div style="font-size:15px;font-weight:700;margin-top:4px">${p.language||'?'}</div></div>
      <div style="background:var(--bg2);padding:10px 14px;border-radius:8px"><div style="font-size:9px;color:var(--t3);font-weight:700;text-transform:uppercase;letter-spacing:1px">框架</div><div style="font-size:15px;font-weight:700;margin-top:4px">${p.framework||'?'}</div></div>
      <div style="background:var(--bg2);padding:10px 14px;border-radius:8px"><div style="font-size:9px;color:var(--t3);font-weight:700;text-transform:uppercase;letter-spacing:1px">Profile</div><div style="font-size:15px;font-weight:700;margin-top:4px">${p.profile_name||'?'}</div></div>
      <div style="background:var(--bg2);padding:10px 14px;border-radius:8px"><div style="font-size:9px;color:var(--t3);font-weight:700;text-transform:uppercase;letter-spacing:1px">Hook 框架</div><div style="font-size:15px;font-weight:700;margin-top:4px">${(p.features||{}).hook_framework||'?'}</div></div>
    </div>`;

  const feats=p.features||{};
  const tn={claude_hooks:'Claude Hooks',rules:'Rules',agents:'Agents',reward_loop:'Reward Loop',security_signal:'Security',quality_signal:'Quality',test_signal:'Test',perf_signal:'Perf',github_actions:'CI/CD'};
  let th='';
  for(const[k,l]of Object.entries(tn)){const on=feats[k];th+=`<span class="tag ${on?'tag-on':'tag-off'}">${on?'\u2713':'\u25CB'} ${l}</span>`}
  document.getElementById('feature-tags').innerHTML=th;

  const sp=p.specials||[];
  document.getElementById('specials').innerHTML=sp.length?sp.map(s=>`<div class="special-item"><span class="special-dot"></span>${s}</div>`).join(''):'<div style="color:var(--t3);font-size:12px">无特殊处理</div>';

  // ── Risks ──
  const risks=d.risks||[];
  document.getElementById('risks').innerHTML=risks.length===0
    ?'<div class="risk-zero">\u2713 无风险项 — 环境健康</div>'
    :risks.map(r=>`<div class="risk risk-${r.level}"><div class="risk-badge">${r.level==='error'?'ERROR':'WARNING'} \u00B7 ${r.section}</div><div class="risk-name">${r.name}</div><div class="risk-detail">${r.detail}</div></div>`).join('');

  // ── Health ──
  const sigs=(d.health||{}).signals||{};
  let hh='';
  const sigLabels={security:'Security',quality:'Quality',test:'Test',perf:'Perf'};
  for(const[n,info]of Object.entries(sigs)){
    const si=info.status==='ready'?'\u2713':info.status==='incomplete'?'\u26A0':'\u2013';
    hh+=`<div class="row"><div class="row-icon bg-${bg(info.status)}">${si}</div><div class="row-name">${sigLabels[n]||n}</div><div class="row-detail">${info.detail}</div></div>`;
  }
  const lr=(d.health||{}).last_report;
  if(lr)hh+=`<div style="font-size:10px;color:var(--t3);margin-top:10px;font-family:'JetBrains Mono',monospace">Last report: ${lr}</div>`;
  document.getElementById('health').innerHTML=hh||'<div style="color:var(--t3);font-size:12px;padding:12px">无信号数据</div>';

  // ── Hooks ──
  const hooks=d.hooks_summary||{};
  const events=hooks.events||{};
  document.getElementById('hook-count').textContent=`(${hooks.total||0})`;
  let hkh='<div class="hooks-grid">';
  for(const[ev,names]of Object.entries(events)){
    hkh+=`<div class="hook-group"><div class="hook-group-title">${ev}</div>${names.map(n=>`<div class="hook-item">${n}</div>`).join('')}</div>`;
  }
  hkh+='</div>';
  document.getElementById('hooks').innerHTML=hkh;

  // ── Verify ──
  const secs=v.sections||{};
  let vh='';
  for(const[k,sec]of Object.entries(secs)){
    const sc=sec.status==='PASS'?'var(--green)':'var(--red)';
    vh+=`<div class="sec-hdr"><span class="sec-dot" style="background:${sc}"></span><span class="sec-name">${sec.label}</span><span class="sec-stat">${sec.summary}</span></div>`;
    for(const c of(sec.checks||[])){
      vh+=`<div class="row"><div class="row-icon bg-${bg(c.status)}">${ic(c.status)}</div><div class="row-name">${c.name}</div><div class="row-detail">${c.detail}</div></div>`;
    }
  }
  document.getElementById('verify-detail').innerHTML=vh;

  // ── 大白话简报 ──
  const b=d.briefs||{};
  const briefIds=['score','deploy','profile','risks','health','hooks','verify'];
  briefIds.forEach(k=>{
    const el=document.getElementById('brief-'+k);
    if(el&&b[k])el.textContent=b[k];
  });

  // ── 部署计划 ──
  const plan=d.plan;
  const planSec=document.getElementById('plan-section');
  if(plan&&planSec){
    planSec.style.display='block';
    const p=plan.project||{};
    const typeLabels={docs:'\u{1F4DA} 文档项目','code-active':'\u{1F4BB} 活跃代码项目','code-basic':'\u{1F4BB} 基础代码项目','ai-system':'\u{1F916} AI 系统',game:'\u{1F3AE} 游戏项目',unknown:'\u{2753} 未知类型'};
    document.getElementById('plan-portrait').innerHTML=`
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:14px">
        <div style="background:var(--bg2);padding:12px 16px;border-radius:10px"><div style="font-size:9px;color:var(--t3);font-weight:700;text-transform:uppercase;letter-spacing:1px">项目类型</div><div style="font-size:15px;font-weight:700;margin-top:6px">${typeLabels[p.type]||p.type}</div><div style="font-size:11px;color:var(--t2);margin-top:2px">${p.type_reason||''}</div></div>
        <div style="background:var(--bg2);padding:12px 16px;border-radius:10px"><div style="font-size:9px;color:var(--t3);font-weight:700;text-transform:uppercase;letter-spacing:1px">主语言</div><div style="font-size:15px;font-weight:700;margin-top:6px">${p.language||'?'}</div><div style="font-size:11px;color:var(--t2);margin-top:2px">${p.language_reason||''}</div></div>
        <div style="background:var(--bg2);padding:12px 16px;border-radius:10px"><div style="font-size:9px;color:var(--t3);font-weight:700;text-transform:uppercase;letter-spacing:1px">项目规模</div><div style="font-size:15px;font-weight:700;margin-top:6px">${p.total_files||0} 文件</div><div style="font-size:11px;color:var(--t2);margin-top:2px">代码 ${p.code_files||0} / 文档 ${p.doc_files||0}</div></div>
      </div>
      <div style="font-size:12px;color:var(--t2);padding:8px 12px;background:var(--bg2);border-radius:8px;line-height:1.6">${p.description||'无项目描述'}</div>
      <div style="display:flex;gap:12px;margin-top:10px">
        <span class="tag ${p.has_git?'tag-on':'tag-off'}">${p.has_git?'\u2713':'\u2717'} Git</span>
        <span class="tag ${p.has_tests?'tag-on':'tag-off'}">${p.has_tests?'\u2713':'\u2717'} Tests</span>
        <span class="tag ${p.has_ci?'tag-on':'tag-off'}">${p.has_ci?'\u2713':'\u2717'} CI</span>
      </div>`;

    // 已部署
    const decs=plan.decisions||[];
    const deployed=decs.filter(x=>x.action==='deploy');
    const skipped=decs.filter(x=>x.action==='skip');
    document.getElementById('plan-deployed').innerHTML=deployed.map(x=>`
      <div style="padding:8px 12px;border-radius:8px;margin-bottom:6px;background:var(--green-dim);border-left:3px solid var(--green)">
        <div style="font-size:13px;font-weight:700">${x.component}</div>
        <div style="font-size:11px;color:var(--t2);margin-top:2px">${x.reason}</div>
      </div>`).join('')||'<div style="color:var(--t3)">无</div>';

    document.getElementById('plan-skipped').innerHTML=skipped.map(x=>`
      <div style="padding:8px 12px;border-radius:8px;margin-bottom:6px;background:rgba(255,255,255,.02);border-left:3px solid var(--t3)">
        <div style="font-size:13px;font-weight:700;color:var(--t2)">${x.component}</div>
        <div style="font-size:11px;color:var(--t3);margin-top:2px">${x.reason}</div>
      </div>`).join('')||'<div style="color:var(--t3)">无</div>';

    // 建议
    const recs=plan.recommendations||[];
    const recsCard=document.getElementById('plan-recs-card');
    if(recs.length>0){
      recsCard.style.display='block';
      const priColor={high:'var(--red)',medium:'var(--amber)',low:'var(--t3)'};
      document.getElementById('plan-recs').innerHTML=recs.map(r=>`
        <div style="padding:10px 14px;border-radius:8px;margin-bottom:6px;background:${r.priority==='high'?'var(--red-dim)':'var(--amber-dim)'};border-left:3px solid ${priColor[r.priority]||'var(--t3)'}">
          <div style="font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:1px;color:${priColor[r.priority]}">${r.priority}</div>
          <div style="font-size:13px;font-weight:700;margin-top:2px">${r.item}</div>
          <div style="font-size:11px;color:var(--t2);margin-top:2px">${r.reason}</div>
          ${r.command?`<div style="font-size:11px;color:var(--cyan);font-family:'JetBrains Mono',monospace;margin-top:4px;padding:4px 8px;background:rgba(0,0,0,.3);border-radius:4px">${r.command}</div>`:''}
        </div>`).join('');
    }else{recsCard.style.display='none'}
  }
}

async function tick(){
  try{
    const r=await fetch(API);const d=await r.json();render(d);
    const el=document.getElementById('live-indicator');el.innerHTML='<span class="live-dot"></span>LIVE';el.style.borderColor='rgba(52,211,153,.2)';
  }catch(e){
    const el=document.getElementById('live-indicator');el.innerHTML='OFFLINE';el.style.borderColor='rgba(248,113,113,.2)';el.querySelector('.live-dot')&&(el.querySelector('.live-dot').style.background='var(--red)');
  }
}
tick();setInterval(tick,10000);
</script>
</body>
</html>"""


class MonitorHandler(http.server.BaseHTTPRequestHandler):
    monitor = None  # 由外部注入

    def do_GET(self):
        if self.path == "/api/status":
            data = self.monitor.get_data()
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif self.path == "/" or self.path == "/index.html":
            html = DASHBOARD_HTML.replace(
                "__PROJECT__", self.monitor.get_data()["project_name"]
            )
            payload = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        # 静默日志，不刷屏
        pass


def background_collector(monitor, interval=30):
    """后台线程：定期采集数据"""
    while True:
        try:
            monitor.collect_all()
        except Exception as e:
            print(f"[monitor] collect error: {e}", file=sys.stderr)
        time.sleep(interval)


def main():
    if len(sys.argv) < 2:
        print("用法: python monitor.py <project_dir> [--port 8420]")
        sys.exit(1)

    project_dir = sys.argv[1]
    port = 8420
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    if not os.path.isdir(project_dir):
        print(f"错误: 目录不存在 {project_dir}")
        sys.exit(1)

    monitor = ProjectMonitor(project_dir)

    # 首次采集
    print(f"正在采集 {project_dir} 的项目数据...")
    monitor.collect_all()

    # 后台定期采集
    collector_thread = threading.Thread(
        target=background_collector, args=(monitor, 30), daemon=True
    )
    collector_thread.start()

    # 启动 HTTP 服务
    MonitorHandler.monitor = monitor
    server = http.server.HTTPServer(("127.0.0.1", port), MonitorHandler)

    url = f"http://localhost:{port}"
    print(f"\n{'=' * 50}")
    print(f"  实时监控面板已启动")
    print(f"  地址: {url}")
    print(f"  Ctrl+C 停止")
    print(f"{'=' * 50}\n")

    # 自动打开浏览器
    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n监控已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
