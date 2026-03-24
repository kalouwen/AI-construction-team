#!/usr/bin/env python3
"""
dashboard.py — 部署仪表盘

两种模式：
  1. 部署模式：deploy.sh 运行时实时显示部署进度
  2. 健康检查模式：部署完成后验证环境完整性

用法:
  python dashboard.py <project_dir> [--open]         # 从 verify.py 结果生成
  python dashboard.py <project_dir> --deploy-log <log> [--open]  # 含部署日志
"""

import json
import os
import sys
import webbrowser
from datetime import datetime, timezone


def read_json(p, d=None):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else (d or {})

def read_jsonl(p):
    if not os.path.exists(p): return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def generate_html(project_dir, deploy_log_path=None):
    # 读取验证结果
    verify_path = os.path.join(project_dir, ".deploy", "verify-result.json")
    vr = read_json(verify_path)
    sections = vr.get("sections", {})
    overall = vr.get("overall", "UNKNOWN")
    summary = vr.get("summary", "未运行验证")
    total_pass = vr.get("pass_count", 0)
    total_all = vr.get("total", 0)
    score = round(total_pass / total_all * 100) if total_all > 0 else 0

    # 读取部署日志
    deploy_log = []
    dl_path = deploy_log_path or os.path.join(project_dir, ".deploy", "deploy-log.jsonl")
    if os.path.exists(dl_path):
        deploy_log = read_jsonl(dl_path)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    project_name = os.path.basename(os.path.abspath(project_dir))

    # 状态
    if overall == "PASS":
        st, sc, st_desc = "部署完成", "#10b981", "所有检查项全部通过"
    elif overall == "FAIL":
        st, sc, st_desc = "存在问题", "#ef4444", "部分检查未通过，请查看详情"
    else:
        st, sc, st_desc = "等待验证", "#6b7280", "运行 verify.py 进行环境检查"

    # 四个维度的数据
    dims = [
        ("environment", "环境健康", "组件是否就位", ["git_hooks", "claude_hooks", "configs", "assets"]),
        ("atomization", "原子化链路", "每个约束是否生效", ["atomization"]),
        ("evolution", "进化管道", "自动化链路是否完整", ["evolution"]),
    ]

    # 部署流水线 HTML
    pipeline_html = ""
    if deploy_log:
        steps_html = ""
        for entry in deploy_log:
            s = entry.get("status", "")
            label = entry.get("step", "")
            detail = entry.get("detail", "")
            if s == "success":
                color, icon = "#10b981", "&#10003;"
            elif s == "skip":
                color, icon = "#6b7280", "&#8722;"
            elif s == "fail":
                color, icon = "#ef4444", "&#10007;"
            else:
                color, icon = "#3b82f6", "&#8226;"
            steps_html += f"""
            <div class="pipe-step">
              <div class="pipe-icon" style="background:{color}">{icon}</div>
              <div class="pipe-info">
                <div class="pipe-label">{label}</div>
                <div class="pipe-detail">{detail}</div>
              </div>
            </div>"""
        pipeline_html = f"""
        <div class="section">
          <h2><span class="dot" style="background:var(--blue)"></span>部署流水线</h2>
          <div class="pipeline">{steps_html}</div>
        </div>"""

    # 验证结果卡片
    verify_html = ""
    for dim_key, dim_label, dim_desc, section_keys in dims:
        cards_html = ""
        dim_pass = 0
        dim_total = 0
        for sk in section_keys:
            sec = sections.get(sk, {})
            for check in sec.get("checks", []):
                dim_total += 1
                s = check["status"]
                name = check["name"]
                detail = check["detail"]
                if s == "PASS":
                    dim_pass += 1
                    row_class = "check-pass"
                    icon = "&#10003;"
                elif s == "FAIL":
                    row_class = "check-fail"
                    icon = "&#10007;"
                elif s == "WARN":
                    row_class = "check-warn"
                    icon = "&#9888;"
                else:
                    row_class = "check-skip"
                    icon = "&#8722;"
                cards_html += f"""
                <div class="check-row {row_class}">
                  <span class="check-icon">{icon}</span>
                  <span class="check-name">{name}</span>
                  <span class="check-detail">{detail}</span>
                </div>"""

        dim_pct = round(dim_pass / dim_total * 100) if dim_total > 0 else 0
        dim_color = "#10b981" if dim_pct == 100 else "#f59e0b" if dim_pct >= 60 else "#ef4444"
        verify_html += f"""
        <div class="section">
          <div class="section-header">
            <div>
              <h2>{dim_label}</h2>
              <p class="section-desc">{dim_desc}</p>
            </div>
            <div class="section-score">
              <div class="ring-small">
                <svg width="56" height="56" viewBox="0 0 56 56">
                  <circle cx="28" cy="28" r="24" fill="none" stroke="#1f1f30" stroke-width="4"/>
                  <circle cx="28" cy="28" r="24" fill="none" stroke="{dim_color}" stroke-width="4"
                    stroke-dasharray="{dim_pct * 1.508} {150.8 - dim_pct * 1.508}" stroke-linecap="round"
                    style="transform:rotate(-90deg);transform-origin:center"/>
                </svg>
                <span class="ring-val" style="color:{dim_color}">{dim_pct}%</span>
              </div>
              <span class="ring-label">{dim_pass}/{dim_total}</span>
            </div>
          </div>
          <div class="checks">{cards_html}</div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{project_name} — 环境仪表盘</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
:root {{
  --bg: #06060b; --bg2: #0d0d14; --bg3: #12121c; --bg4: #1a1a28;
  --border: #1c1c2e; --border2: #2a2a40;
  --t1: #f0f0f8; --t2: #9090a8; --t3: #606078;
  --green: #10b981; --red: #ef4444; --blue: #3b82f6; --amber: #f59e0b; --purple: #8b5cf6; --cyan: #06b6d4;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Inter',system-ui,sans-serif; background:var(--bg); color:var(--t1); min-height:100vh; padding:24px; }}
.container {{ max-width:960px; margin:0 auto; }}

/* ── 头部 ── */
.hdr {{
  padding:32px;
  background:linear-gradient(145deg,var(--bg3),var(--bg2));
  border:1px solid var(--border);
  border-radius:20px;
  margin-bottom:20px;
  position:relative;
  overflow:hidden;
  text-align:center;
}}
.hdr::before {{ content:''; position:absolute; top:0; left:0; right:0; height:3px; background:linear-gradient(90deg,{sc},{sc}60,transparent); }}
.hdr h1 {{ font-size:14px; color:var(--t3); font-weight:600; text-transform:uppercase; letter-spacing:2px; }}
.hdr .project {{ font-size:28px; font-weight:900; margin:8px 0; letter-spacing:-0.5px; }}
.hdr .time {{ font-size:11px; color:var(--t3); }}

/* ── 总分 ── */
.score-bar {{
  display:flex;
  align-items:center;
  justify-content:center;
  gap:24px;
  padding:28px;
  background:var(--bg3);
  border:1px solid var(--border);
  border-radius:16px;
  margin-bottom:20px;
}}
.score-ring {{
  position:relative;
  width:120px;
  height:120px;
  flex-shrink:0;
}}
.score-ring svg {{ transform:rotate(-90deg); }}
.score-ring .sv {{ position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); }}
.score-ring .sv .num {{ font-size:36px; font-weight:900; display:block; text-align:center; }}
.score-ring .sv .unit {{ font-size:11px; color:var(--t3); display:block; text-align:center; }}
.score-info {{ text-align:left; }}
.score-info .status {{ font-size:20px; font-weight:800; margin-bottom:4px; }}
.score-info .desc {{ font-size:13px; color:var(--t2); }}
.score-info .counts {{ display:flex; gap:16px; margin-top:12px; }}
.score-info .count {{ font-size:12px; color:var(--t3); }}
.score-info .count b {{ font-size:18px; font-weight:800; display:block; }}

/* ── 通用 section ── */
.section {{
  background:var(--bg3);
  border:1px solid var(--border);
  border-radius:16px;
  padding:24px;
  margin-bottom:16px;
}}
.section h2 {{ font-size:16px; font-weight:700; display:flex; align-items:center; gap:8px; }}
.section-desc {{ font-size:12px; color:var(--t3); margin-top:2px; }}
.section-header {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:16px; }}
.dot {{ width:8px; height:8px; border-radius:50%; flex-shrink:0; }}

/* ── 环形分数 ── */
.ring-small {{ position:relative; width:56px; height:56px; }}
.ring-small svg {{ transform:rotate(-90deg); }}
.ring-val {{ position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); font-size:13px; font-weight:800; }}
.ring-label {{ font-size:10px; color:var(--t3); text-align:center; display:block; margin-top:2px; }}

/* ── 检查行 ── */
.checks {{ display:flex; flex-direction:column; gap:2px; }}
.check-row {{
  display:flex;
  align-items:center;
  gap:10px;
  padding:10px 14px;
  border-radius:8px;
  font-size:13px;
  transition:background 0.15s;
}}
.check-row:hover {{ background:var(--bg4); }}
.check-icon {{ width:22px; height:22px; border-radius:6px; display:flex; align-items:center; justify-content:center; font-size:12px; flex-shrink:0; color:#fff; }}
.check-pass .check-icon {{ background:var(--green); }}
.check-fail .check-icon {{ background:var(--red); }}
.check-warn .check-icon {{ background:var(--amber); }}
.check-skip .check-icon {{ background:var(--t3); }}
.check-name {{ font-weight:600; flex:1; }}
.check-detail {{ color:var(--t2); font-size:12px; text-align:right; max-width:300px; }}

/* ── 部署流水线 ── */
.pipeline {{ display:flex; flex-direction:column; gap:4px; margin-top:16px; }}
.pipe-step {{
  display:flex;
  align-items:center;
  gap:12px;
  padding:10px 14px;
  border-radius:8px;
  transition:background 0.15s;
}}
.pipe-step:hover {{ background:var(--bg4); }}
.pipe-icon {{
  width:28px; height:28px; border-radius:8px;
  display:flex; align-items:center; justify-content:center;
  color:#fff; font-size:14px; flex-shrink:0;
}}
.pipe-info {{ flex:1; }}
.pipe-label {{ font-weight:600; font-size:13px; }}
.pipe-detail {{ font-size:11px; color:var(--t2); margin-top:1px; }}

footer {{ text-align:center; color:var(--t3); font-size:11px; margin-top:32px; padding:16px; border-top:1px solid var(--border); }}
</style>
</head>
<body>
<div class="container">

<div class="hdr">
  <h1>环境仪表盘</h1>
  <div class="project">{project_name}</div>
  <div class="time">{now}</div>
</div>

<div class="score-bar">
  <div class="score-ring">
    <svg width="120" height="120" viewBox="0 0 120 120">
      <circle cx="60" cy="60" r="52" fill="none" stroke="#1f1f30" stroke-width="7"/>
      <circle cx="60" cy="60" r="52" fill="none" stroke="{sc}" stroke-width="7"
        stroke-dasharray="{score * 3.267} {326.7 - score * 3.267}" stroke-linecap="round"/>
    </svg>
    <div class="sv">
      <span class="num" style="color:{sc}">{score}</span>
      <span class="unit">环境分</span>
    </div>
  </div>
  <div class="score-info">
    <div class="status" style="color:{sc}">{st}</div>
    <div class="desc">{st_desc}</div>
    <div class="counts">
      <div class="count"><b style="color:var(--green)">{total_pass}</b>通过</div>
      <div class="count"><b style="color:var(--red)">{total_all - total_pass}</b>未通过</div>
      <div class="count"><b style="color:var(--blue)">{total_all}</b>总计</div>
    </div>
  </div>
</div>

{pipeline_html}

{verify_html}

</div>
<footer>由 AI for better 生成 · 环境仪表盘</footer>
</body>
</html>"""
    return html


def main():
    if len(sys.argv) < 2:
        print("用法: python dashboard.py <project_dir> [--open]")
        sys.exit(1)
    project_dir = sys.argv[1]
    deploy_log = None
    if "--deploy-log" in sys.argv:
        idx = sys.argv.index("--deploy-log")
        if idx + 1 < len(sys.argv):
            deploy_log = sys.argv[idx + 1]

    html = generate_html(project_dir, deploy_log)
    output_dir = os.path.join(project_dir, ".deploy")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "dashboard.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"仪表盘已生成: {output_path}")
    if "--open" in sys.argv:
        webbrowser.open(f"file://{os.path.abspath(output_path)}")


if __name__ == "__main__":
    main()
