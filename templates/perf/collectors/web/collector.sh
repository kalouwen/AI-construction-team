#!/usr/bin/env bash
# =============================================================================
# Web 前端性能采集器
#
# 用 Playwright 无头浏览器打开目标页面，通过 Performance API 采集指标，
# 输出标准 result.json 格式
#
# 用法: bash collector.sh <perf.yaml> <output_dir>
#
# 前提:
#   - node / npm 已安装
#   - 项目有 dev server 可启动（或指定一个 URL）
#   - 首次运行会自动安装 playwright
#
# 配置 (在 perf.yaml 中添加):
#   collector:
#     web:
#       url: "http://localhost:3000"       # 测试 URL
#       startup_cmd: "npm run dev"         # dev server 启动命令（可选）
#       startup_wait_sec: 5                # 等待 server 就绪
#       measure_duration_sec: 10           # 测量持续时间
# =============================================================================

set -euo pipefail

CONFIG="${1:?用法: collector.sh <perf.yaml> <output_dir>}"
OUTPUT_DIR="${2:?缺少输出目录}"

mkdir -p "$OUTPUT_DIR"

# ---------------------------------------------------------------------------
# 读取配置
# ---------------------------------------------------------------------------
read_config() {
  python3 -c "
import yaml, functools, operator
with open('$CONFIG') as f:
    data = yaml.safe_load(f)
keys = '$1'.split('.')
try:
    val = functools.reduce(operator.getitem, keys, data)
    print(val if val is not None else '')
except (KeyError, TypeError):
    print('$2')
" 2>/dev/null
}

RUNS=$(read_config "collector.runs" "3")
URL=$(read_config "collector.web.url" "http://localhost:3000")
STARTUP_CMD=$(read_config "collector.web.startup_cmd" "")
STARTUP_WAIT=$(read_config "collector.web.startup_wait_sec" "5")
MEASURE_DURATION=$(read_config "collector.web.measure_duration_sec" "10")
WARMUP_SEC=$(read_config "collector.web.warmup_sec" "3")
TIMEOUT_SEC=$(read_config "collector.timeout_sec" "300")

# ---------------------------------------------------------------------------
# 确保 playwright 可用
# ---------------------------------------------------------------------------
if ! npx playwright --version >/dev/null 2>&1; then
  echo "📦 安装 playwright..."
  npm install -D playwright 2>/dev/null
  npx playwright install chromium 2>/dev/null
fi

# ---------------------------------------------------------------------------
# 启动 dev server（如果配置了）
# ---------------------------------------------------------------------------
SERVER_PID=""
if [[ -n "$STARTUP_CMD" ]]; then
  echo "🚀 启动 dev server: $STARTUP_CMD"
  $STARTUP_CMD &
  SERVER_PID=$!
  sleep "$STARTUP_WAIT"
fi

# 确保退出时清理 server
cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# 获取构建体积（如果有 dist 目录）
# ---------------------------------------------------------------------------
BUILD_SIZE_KB=0
for dir in dist build out .next/static; do
  if [[ -d "$dir" ]]; then
    BUILD_SIZE_KB=$(du -sk "$dir" 2>/dev/null | cut -f1)
    break
  fi
done
BUILD_SIZE_MB=$(python3 -c "print(round($BUILD_SIZE_KB / 1024, 2))")

# ---------------------------------------------------------------------------
# 获取 git commit
# ---------------------------------------------------------------------------
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

# ---------------------------------------------------------------------------
# Playwright 采集脚本
# ---------------------------------------------------------------------------
COLLECT_SCRIPT=$(cat << 'JSEOF'
const { chromium } = require('playwright');

const args = process.argv.slice(2);
const url = args[0];
const warmupSec = parseFloat(args[1]);
const measureSec = parseFloat(args[2]);
const outputFile = args[3];
const runIndex = parseInt(args[4]);
const totalRuns = parseInt(args[5]);
const commit = args[6];
const buildSizeMB = parseFloat(args[7]);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  // 收集 console 错误
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));

  // 导航并等待加载
  const navStart = Date.now();
  await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
  const loadTime = (Date.now() - navStart) / 1000;

  // 预热
  await page.waitForTimeout(warmupSec * 1000);

  // 测量阶段：用 requestAnimationFrame 计算真实 FPS
  const perfData = await page.evaluate(async (measureMs) => {
    return new Promise((resolve) => {
      const frames = [];
      let startTime = null;
      let memSamples = [];

      function onFrame(timestamp) {
        if (!startTime) startTime = timestamp;
        frames.push(timestamp);

        // 采集内存（如果可用）
        if (performance.memory) {
          memSamples.push({
            usedJSHeapSize: performance.memory.usedJSHeapSize,
            totalJSHeapSize: performance.memory.totalJSHeapSize,
          });
        }

        if (timestamp - startTime < measureMs) {
          requestAnimationFrame(onFrame);
        } else {
          // 计算 FPS
          const duration = (frames[frames.length - 1] - frames[0]) / 1000;
          const fps = duration > 0 ? (frames.length - 1) / duration : 0;

          // 计算帧时间统计
          const frameTimes = [];
          for (let i = 1; i < frames.length; i++) {
            frameTimes.push(frames[i] - frames[i - 1]);
          }
          frameTimes.sort((a, b) => a - b);

          const p99 = frameTimes[Math.floor(frameTimes.length * 0.99)] || 0;
          const p95 = frameTimes[Math.floor(frameTimes.length * 0.95)] || 0;

          // 内存峰值
          const peakMem = memSamples.length > 0
            ? Math.max(...memSamples.map(s => s.usedJSHeapSize))
            : 0;
          const peakTotalMem = memSamples.length > 0
            ? Math.max(...memSamples.map(s => s.totalJSHeapSize))
            : 0;

          // DOM 节点数
          const domNodes = document.querySelectorAll('*').length;

          // Resource timing
          const resources = performance.getEntriesByType('resource');
          const totalTransfer = resources.reduce((sum, r) => sum + (r.transferSize || 0), 0);

          resolve({
            fps: Math.round(fps * 10) / 10,
            frameTime_p95_ms: Math.round(p95 * 10) / 10,
            frameTime_p99_ms: Math.round(p99 * 10) / 10,
            totalFrames: frames.length,
            memory_peak_mb: Math.round(peakMem / 1024 / 1024 * 10) / 10,
            memory_heap_total_mb: Math.round(peakTotalMem / 1024 / 1024 * 10) / 10,
            dom_nodes: domNodes,
            network_transfer_kb: Math.round(totalTransfer / 1024),
            memory_available: memSamples.length > 0,
          });
        }
      }

      requestAnimationFrame(onFrame);
    });
  }, measureSec * 1000);

  await browser.close();

  // 组装标准输出格式
  const result = {
    version: "1.0",
    timestamp: new Date().toISOString(),
    commit: commit,
    run_index: runIndex,
    total_runs: totalRuns,
    environment: {
      machine_id: require('os').hostname(),
      os: `${require('os').platform()} ${require('os').release()}`,
      cpu: require('os').cpus()[0]?.model || 'unknown',
      ram_gb: Math.round(require('os').totalmem() / 1024 / 1024 / 1024),
      browser: 'chromium (playwright)',
    },
    metrics: {
      fps_avg: {
        value: perfData.fps,
        unit: "fps",
        lower_is_better: false,
      },
      memory_peak_mb: {
        value: perfData.memory_peak_mb,
        unit: "MB",
        lower_is_better: true,
      },
      load_time_sec: {
        value: Math.round(loadTime * 100) / 100,
        unit: "seconds",
        lower_is_better: true,
      },
      dom_nodes: {
        value: perfData.dom_nodes,
        unit: "count",
        lower_is_better: true,
      },
      build_size_mb: {
        value: buildSizeMB,
        unit: "MB",
        lower_is_better: true,
      },
      frame_time_p99_ms: {
        value: perfData.frameTime_p99_ms,
        unit: "ms",
        lower_is_better: true,
      },
    },
    diagnostics: {
      fps_avg: {
        frame_time_p95_ms: perfData.frameTime_p95_ms,
        frame_time_p99_ms: perfData.frameTime_p99_ms,
        total_frames: perfData.totalFrames,
      },
      memory_peak_mb: {
        heap_total_mb: perfData.memory_heap_total_mb,
        memory_api_available: perfData.memory_available,
        note: perfData.memory_available
          ? "Chromium performance.memory API"
          : "memory API not available in this browser context",
      },
    },
    errors: errors.slice(0, 10),
  };

  require('fs').writeFileSync(outputFile, JSON.stringify(result, null, 2));
  console.log(`  Run ${runIndex}: FPS=${perfData.fps} | Mem=${perfData.memory_peak_mb}MB | Load=${loadTime.toFixed(2)}s | DOM=${perfData.dom_nodes}`);
})().catch(err => {
  console.error('Collector error:', err.message);
  process.exit(1);
});
JSEOF
)

# ---------------------------------------------------------------------------
# 执行多次采集
# ---------------------------------------------------------------------------
echo "🔍 采集 Web 性能指标 ($RUNS 次运行)"
echo "   URL: $URL"
echo "   预热: ${WARMUP_SEC}s | 测量: ${MEASURE_DURATION}s"
echo ""

COLLECT_SCRIPT_FILE="$OUTPUT_DIR/_collect.js"
echo "$COLLECT_SCRIPT" > "$COLLECT_SCRIPT_FILE"

for i in $(seq 1 "$RUNS"); do
  RESULT_FILE="$OUTPUT_DIR/result_${i}.json"
  timeout "$TIMEOUT_SEC" node "$COLLECT_SCRIPT_FILE" \
    "$URL" "$WARMUP_SEC" "$MEASURE_DURATION" "$RESULT_FILE" \
    "$i" "$RUNS" "$COMMIT" "$BUILD_SIZE_MB" \
    || { echo "ERROR: 第 $i 次运行失败" >&2; exit 1; }
done

# 清理临时脚本
rm -f "$COLLECT_SCRIPT_FILE"

echo ""
echo "✅ 采集完成，结果在 $OUTPUT_DIR/"
