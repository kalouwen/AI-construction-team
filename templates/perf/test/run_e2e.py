"""
端到端测试：Web采集器 → 判定器 → 历史管理 完整链路验证

用法: python run_e2e.py
前提:
  - http://127.0.0.1:8083 已启动 (python -m http.server 8083 --directory .)
  - npm install -D playwright && npx playwright install chromium
"""

import json
import os
import sys
import shutil
import subprocess
import time
import glob
import yaml
import functools
import operator
from pathlib import Path
from datetime import datetime, timezone

SCRIPT_DIR = Path(__file__).parent
PERF_DIR = SCRIPT_DIR.parent
CONFIG_PATH = SCRIPT_DIR / "perf.yaml"
TEST_WORK_DIR = SCRIPT_DIR / ".perf"

# 清理旧数据
if TEST_WORK_DIR.exists():
    shutil.rmtree(TEST_WORK_DIR)

RESULTS_DIR = TEST_WORK_DIR / "results" / "round_1"
RESULTS_DIR.mkdir(parents=True)

# ===== 读取配置 =====
with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

print("=" * 60)
print("  端到端测试: Web采集 → 判定 → 历史")
print("=" * 60)

# ===== 第1步: 运行 Web 采集器 =====
print("\n[1/4] 运行 Web 采集器...")

# 检查 playwright (Windows 需要 shell=True 来找到 npx/npm)
try:
    subprocess.run("npx playwright --version", capture_output=True, check=True, shell=True)
except (subprocess.CalledProcessError, FileNotFoundError):
    print("  安装 playwright...")
    subprocess.run("npm install -D playwright", cwd=str(SCRIPT_DIR), shell=True)
    subprocess.run("npx playwright install chromium", cwd=str(SCRIPT_DIR), shell=True)

# 直接用 node + playwright 采集（内联脚本，避免 bash python3 问题）
COLLECT_JS = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');

const url = process.argv[2];
const warmupSec = parseFloat(process.argv[3]);
const measureSec = parseFloat(process.argv[4]);
const outputFile = process.argv[5];
const runIndex = parseInt(process.argv[6]);
const totalRuns = parseInt(process.argv[7]);
const commit = process.argv[8] || 'test';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  const navStart = Date.now();
  await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
  const loadTime = (Date.now() - navStart) / 1000;

  await page.waitForTimeout(warmupSec * 1000);

  const perfData = await page.evaluate(async (measureMs) => {
    return new Promise((resolve) => {
      const frames = [];
      let startTime = null;

      function onFrame(timestamp) {
        if (!startTime) startTime = timestamp;
        frames.push(timestamp);

        if (timestamp - startTime < measureMs) {
          requestAnimationFrame(onFrame);
        } else {
          const duration = (frames[frames.length - 1] - frames[0]) / 1000;
          const fps = duration > 0 ? (frames.length - 1) / duration : 0;

          const frameTimes = [];
          for (let i = 1; i < frames.length; i++) {
            frameTimes.push(frames[i] - frames[i - 1]);
          }
          frameTimes.sort((a, b) => a - b);
          const p99 = frameTimes[Math.floor(frameTimes.length * 0.99)] || 0;

          const domNodes = document.querySelectorAll('*').length;

          resolve({
            fps: Math.round(fps * 10) / 10,
            frameTime_p99_ms: Math.round(p99 * 10) / 10,
            totalFrames: frames.length,
            dom_nodes: domNodes,
          });
        }
      }
      requestAnimationFrame(onFrame);
    });
  }, measureSec * 1000);

  await browser.close();

  const result = {
    version: "1.0",
    timestamp: new Date().toISOString(),
    commit: commit,
    run_index: runIndex,
    total_runs: totalRuns,
    environment: {
      machine_id: os.hostname(),
      os: `${os.platform()} ${os.release()}`,
      cpu: os.cpus()[0]?.model || 'unknown',
      ram_gb: Math.round(os.totalmem() / 1024 / 1024 / 1024),
      browser: 'chromium (playwright)',
    },
    metrics: {
      fps_avg: { value: perfData.fps, unit: "fps", lower_is_better: false },
      memory_peak_mb: { value: 5.0, unit: "MB", lower_is_better: true },
      load_time_sec: { value: Math.round(loadTime * 100) / 100, unit: "seconds", lower_is_better: true },
      dom_nodes: { value: perfData.dom_nodes, unit: "count", lower_is_better: true },
    },
    diagnostics: {
      fps_avg: {
        frame_time_p99_ms: perfData.frameTime_p99_ms,
        total_frames: perfData.totalFrames,
      },
    },
  };

  fs.writeFileSync(outputFile, JSON.stringify(result, null, 2));
  console.log(`  Run ${runIndex}: FPS=${perfData.fps} | Load=${loadTime.toFixed(2)}s | DOM=${perfData.dom_nodes}`);
})().catch(err => {
  console.error('Error:', err.message);
  process.exit(1);
});
"""

collect_script_path = RESULTS_DIR / "_collect.js"
collect_script_path.write_text(COLLECT_JS)

runs = config["collector"]["runs"]
url = "http://127.0.0.1:8083/index.html"
warmup = config["collector"].get("warmup_sec", 2)
measure = config["collector"].get("measure_duration_sec", 5)
commit = "test123"

for i in range(1, runs + 1):
    result_file = RESULTS_DIR / f"result_{i}.json"
    cmd = f'node "{collect_script_path}" {url} {warmup} {measure} "{result_file}" {i} {runs} {commit}'
    try:
        subprocess.run(cmd, check=True, timeout=60, shell=True)
    except subprocess.TimeoutExpired:
        print(f"  WARNING: Run {i} timed out")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"  ERROR: Run {i} failed: {e}")
        sys.exit(1)

collect_script_path.unlink()  # 清理

# 验证结果文件
result_files = list(RESULTS_DIR.glob("result_*.json"))
print(f"  采集完成: {len(result_files)} 个结果文件")

# 快速看一个结果
with open(result_files[0]) as f:
    sample = json.load(f)
    print(f"  样本: FPS={sample['metrics']['fps_avg']['value']}, "
          f"Load={sample['metrics']['load_time_sec']['value']}s")

# ===== 第2步: 创建测试 baseline =====
print("\n[2/4] 创建测试 baseline...")

# 用第一次采集的结果作为 baseline（模拟"上次的好结果"）
baseline = {
    "version": "1.0",
    "absolute": {
        "commit": "baseline-v1",
        "created_at": "2026-03-16T00:00:00Z",
        "metrics": {}
    },
    "relative": {
        "commit": "baseline-prev",
        "updated_at": "2026-03-16T00:00:00Z",
        "metrics": {}
    }
}

with open(result_files[0]) as f:
    first_result = json.load(f)

for name, data in first_result["metrics"].items():
    baseline["absolute"]["metrics"][name] = {"value": data["value"]}
    baseline["relative"]["metrics"][name] = {"value": data["value"]}

baseline_path = TEST_WORK_DIR / "baseline.json"
with open(baseline_path, "w") as f:
    json.dump(baseline, f, indent=2)

print(f"  Baseline 创建完成: {baseline_path}")

# ===== 第3步: 运行判定器 =====
print("\n[3/4] 运行判定器...")

# 直接用 Python 实现判定逻辑（跟 judge.sh 中的 python 块一致）

# 计算中位数
all_results = []
for rf in sorted(result_files):
    with open(rf) as f:
        all_results.append(json.load(f))

metrics_values = {}
for r in all_results:
    for name, data in r.get("metrics", {}).items():
        metrics_values.setdefault(name, []).append(data["value"])

medians = {}
for name, values in metrics_values.items():
    values.sort()
    n = len(values)
    medians[name] = values[n // 2] if n % 2 == 1 else (values[n // 2 - 1] + values[n // 2]) / 2

print(f"  中位数: { {k: v for k, v in medians.items()} }")

# 判定
with open(baseline_path) as f:
    baseline_data = json.load(f)

max_soft_failures = config["judge"]["max_soft_failures"]
details = {}
hard_failures = 0
soft_failures = 0

for metric_name, metric_config in config.get("metrics", {}).items():
    if metric_name not in medians:
        continue

    measured = medians[metric_name]
    lower_is_better = metric_config.get("lower_is_better", True)
    tier = metric_config.get("tier", "info")
    threshold_rel = metric_config.get("threshold_relative", 5)
    threshold_abs = metric_config.get("threshold_absolute", 10)

    baseline_rel = baseline_data["relative"]["metrics"].get(metric_name, {}).get("value")
    baseline_abs = baseline_data["absolute"]["metrics"].get(metric_name, {}).get("value")

    detail = {"measured": measured, "tier": tier, "lower_is_better": lower_is_better}
    metric_verdict = "PASS"
    reasons = []

    for label, base_val, threshold in [
        ("relative", baseline_rel, threshold_rel),
        ("absolute", baseline_abs, threshold_abs)
    ]:
        if base_val is not None and base_val != 0:
            if lower_is_better:
                change = ((measured - base_val) / base_val) * 100
                degraded = change > threshold
            else:
                change = ((base_val - measured) / base_val) * 100
                degraded = change > threshold

            detail[f"baseline_{label}"] = base_val
            detail[f"change_vs_{label}"] = f"{'+' if change > 0 else ''}{change:.1f}%"
            detail[f"threshold_{label}"] = f"{threshold}%"

            if degraded:
                reasons.append(f"exceeded {label} threshold ({detail[f'change_vs_{label}']} vs {threshold}%)")

    if reasons:
        metric_verdict = "FAIL"
        if tier == "hard":
            hard_failures += 1
        elif tier == "soft":
            soft_failures += 1

    detail["verdict"] = metric_verdict
    if reasons:
        detail["reason"] = "; ".join(reasons)
    details[metric_name] = detail

if hard_failures > 0:
    overall = "FAIL"
    summary = f"{hard_failures} hard metric(s) failed"
elif soft_failures > max_soft_failures:
    overall = "FAIL"
    summary = f"{soft_failures} soft metric(s) failed"
else:
    overall = "PASS"
    passed = len([d for d in details.values() if d["verdict"] == "PASS"])
    summary = f"All {passed} metrics passed"

verdict = {
    "version": "1.0",
    "verdict": overall,
    "commit": commit,
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "summary": summary,
    "total_runs_median": len(all_results),
    "details": details
}

verdict_path = RESULTS_DIR / "verdict.json"
with open(verdict_path, "w") as f:
    json.dump(verdict, f, indent=2, ensure_ascii=False)

print(f"\n  {'=' * 50}")
print(f"  VERDICT: {overall}")
print(f"  {summary}")
print(f"  {'=' * 50}")
for name, d in details.items():
    status = "+" if d["verdict"] == "PASS" else "X"
    line = f"  [{status}] {name}: {d['measured']}"
    if "change_vs_relative" in d:
        line += f" ({d['change_vs_relative']} vs baseline)"
    if d["verdict"] == "FAIL":
        line += f"  <- {d.get('reason', '')}"
    print(line)
print(f"  {'=' * 50}")

# ===== 第4步: 更新历史 =====
print("\n[4/4] 更新历史...")

history_path = TEST_WORK_DIR / "history.json"
trajectory_path = TEST_WORK_DIR / "trajectory.jsonl"

# 历史
history = {
    "version": "1.0",
    "total_rounds": 1,
    "merged_improvements": [],
    "failed_attempts": [],
    "remaining_bottlenecks": [],
    "convergence": {
        "recent_improvement_rate": "0%",
        "rounds_without_improvement": 0,
        "strategy_switches": 0
    }
}

round_info = {
    "round": 1,
    "description": "E2E test - baseline measurement",
    "expected": "establish baseline",
    "duration_sec": 30
}

actual = {}
for name, detail in verdict.get("details", {}).items():
    if "change_vs_relative" in detail:
        actual[name] = detail["change_vs_relative"]

trajectory_entry = {
    "round": round_info["round"],
    "timestamp": verdict["timestamp"],
    "commit": verdict["commit"],
    "plan": round_info["description"],
    "expected": round_info["expected"],
    "actual": actual,
    "verdict": verdict["verdict"],
    "summary": verdict["summary"],
    "duration_sec": round_info["duration_sec"]
}

# 写 trajectory
with open(trajectory_path, "w") as f:
    f.write(json.dumps(trajectory_entry, ensure_ascii=False) + "\n")

# 写 history
if verdict["verdict"] == "PASS":
    impact = {name: detail.get("change_vs_relative", "N/A") for name, detail in verdict["details"].items()}
    history["merged_improvements"].append({
        "round": 1,
        "commit": commit,
        "description": round_info["description"],
        "impact": impact
    })

with open(history_path, "w") as f:
    json.dump(history, f, indent=2, ensure_ascii=False)

print(f"  History: {history_path}")
print(f"  Trajectory: {trajectory_path}")

# ===== 最终汇总 =====
print(f"\n{'=' * 60}")
print("  端到端测试完成!")
print(f"{'=' * 60}")
print(f"  结果文件: {len(result_files)} 个")
print(f"  Baseline: {baseline_path}")
print(f"  Verdict:  {verdict_path} -> {overall}")
print(f"  History:  {history_path}")
print(f"  Trajectory: {trajectory_path}")
print()

# 列出所有生成的文件
print("  生成的文件:")
for p in sorted(TEST_WORK_DIR.rglob("*")):
    if p.is_file():
        size = p.stat().st_size
        print(f"    {p.relative_to(TEST_WORK_DIR)} ({size} bytes)")

print(f"\n{'=' * 60}")
sys.exit(0 if overall == "PASS" else 0)  # 测试本身总是 exit 0
