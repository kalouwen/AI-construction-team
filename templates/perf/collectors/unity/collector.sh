#!/usr/bin/env bash
# =============================================================================
# Unity 性能采集器
#
# 用 Unity Editor batch mode 运行基准场景，采集性能指标，
# 输出标准 result.json 格式
#
# 用法: bash collector.sh <perf.yaml> <output_dir>
#
# 前提:
#   - Unity Editor 已安装（需在 PATH 或配置中指定路径）
#   - 项目有基准场景和 PerfBenchmark.cs 测试脚本
#   - 首次运行需要将 PerfBenchmark.cs 复制到项目 Assets/Editor/ 下
#
# 配置 (在 perf.yaml 中添加):
#   collector:
#     unity:
#       editor_path: ""                    # Unity Editor 路径（空则自动检测）
#       project_path: "."                  # Unity 项目路径
#       benchmark_scene: "Assets/Scenes/Benchmark.unity"
#       build_target: "StandaloneWindows64"
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
WARMUP_FRAMES=$(read_config "collector.warmup_frames" "120")
MEASURE_FRAMES=$(read_config "collector.measure_frames" "600")
TIMEOUT_SEC=$(read_config "collector.timeout_sec" "300")
EDITOR_PATH=$(read_config "collector.unity.editor_path" "")
PROJECT_PATH=$(read_config "collector.unity.project_path" ".")
BENCHMARK_SCENE=$(read_config "collector.unity.benchmark_scene" "")
export BUILD_TARGET
BUILD_TARGET=$(read_config "collector.unity.build_target" "StandaloneWindows64")

# ---------------------------------------------------------------------------
# 自动检测 Unity Editor
# ---------------------------------------------------------------------------
find_unity() {
  if [[ -n "$EDITOR_PATH" ]] && [[ -f "$EDITOR_PATH" ]]; then
    echo "$EDITOR_PATH"
    return
  fi

  # Windows 常见路径
  for base in "/c/Program Files/Unity/Hub/Editor" "/c/Program Files (x86)/Unity/Hub/Editor"; do
    if [[ -d "$base" ]]; then
      # 取最新版本
      local latest
      latest=$(ls -1 "$base" 2>/dev/null | sort -V | tail -1)
      if [[ -n "$latest" ]] && [[ -f "$base/$latest/Editor/Unity.exe" ]]; then
        echo "$base/$latest/Editor/Unity.exe"
        return
      fi
    fi
  done

  # macOS
  if [[ -f "/Applications/Unity Hub.app/../Unity/Unity.app/Contents/MacOS/Unity" ]]; then
    echo "/Applications/Unity Hub.app/../Unity/Unity.app/Contents/MacOS/Unity"
    return
  fi

  # PATH 中查找
  if command -v Unity >/dev/null 2>&1; then
    which Unity
    return
  fi

  echo ""
}

UNITY=$(find_unity)
if [[ -z "$UNITY" ]]; then
  echo "ERROR: 找不到 Unity Editor" >&2
  echo "       请在 perf.yaml 中设置 collector.unity.editor_path" >&2
  exit 1
fi
echo "🎮 Unity Editor: $UNITY"

# ---------------------------------------------------------------------------
# 获取 git commit
# ---------------------------------------------------------------------------
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

# ---------------------------------------------------------------------------
# 获取构建体积（如果有 Library/Bee 或 Build 目录）
# ---------------------------------------------------------------------------
export BUILD_SIZE_MB
BUILD_SIZE_MB=0
for dir in Build Builds build; do
  if [[ -d "$PROJECT_PATH/$dir" ]]; then
    BUILD_SIZE_KB=$(du -sk "$PROJECT_PATH/$dir" 2>/dev/null | cut -f1)
    BUILD_SIZE_MB=$(python3 -c "print(round($BUILD_SIZE_KB / 1024, 2))")
    break
  fi
done

# ---------------------------------------------------------------------------
# 确保 PerfBenchmark.cs 存在
# ---------------------------------------------------------------------------
BENCHMARK_CS="$PROJECT_PATH/Assets/Editor/PerfBenchmark.cs"
if [[ ! -f "$BENCHMARK_CS" ]]; then
  echo "📝 部署 PerfBenchmark.cs 到项目..."
  mkdir -p "$PROJECT_PATH/Assets/Editor"
  cat > "$BENCHMARK_CS" << 'CSEOF'
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.Profiling;
using System.IO;
using System.Collections.Generic;
using System.Linq;

/// <summary>
/// 性能基准测试脚本。由 collector.sh 通过 batch mode 调用。
/// 通过环境变量读取配置，输出标准 JSON 格式结果。
/// </summary>
public class PerfBenchmark : MonoBehaviour
{
    private int warmupFrames;
    private int measureFrames;
    private string outputPath;
    private int runIndex;
    private int totalRuns;
    private string commitHash;

    private int frameCount;
    private bool measuring;
    private List<float> frameTimes = new List<float>();
    private List<long> memSamples = new List<long>();
    private List<long> gcSamples = new List<long>();
    private float loadStartTime;
    private float loadEndTime;

    void Awake()
    {
        // 从环境变量读取配置
        warmupFrames = int.Parse(GetEnvOr("PERF_WARMUP_FRAMES", "120"));
        measureFrames = int.Parse(GetEnvOr("PERF_MEASURE_FRAMES", "600"));
        outputPath = GetEnvOr("PERF_OUTPUT_PATH", "perf_result.json");
        runIndex = int.Parse(GetEnvOr("PERF_RUN_INDEX", "1"));
        totalRuns = int.Parse(GetEnvOr("PERF_TOTAL_RUNS", "3"));
        commitHash = GetEnvOr("PERF_COMMIT", "unknown");

        loadStartTime = Time.realtimeSinceStartup;
        Application.targetFrameRate = -1; // 不限帧率
        QualitySettings.vSyncCount = 0;
    }

    void Update()
    {
        frameCount++;

        if (frameCount == 1)
        {
            loadEndTime = Time.realtimeSinceStartup;
        }

        if (frameCount <= warmupFrames)
        {
            return; // 预热阶段
        }

        if (!measuring)
        {
            measuring = true;
            frameTimes.Clear();
            memSamples.Clear();
            gcSamples.Clear();
        }

        // 采集帧时间
        frameTimes.Add(Time.unscaledDeltaTime * 1000f); // ms

        // 采集内存
        memSamples.Add(Profiler.GetTotalAllocatedMemoryLong());

        // 采集 GC
        gcSamples.Add(Profiler.GetMonoUsedSizeLong());

        if (frameTimes.Count >= measureFrames)
        {
            OutputResults();
            #if UNITY_EDITOR
            UnityEditor.EditorApplication.isPlaying = false;
            #else
            Application.Quit();
            #endif
        }
    }

    void OutputResults()
    {
        float avgFrameTime = frameTimes.Average();
        float fps = 1000f / avgFrameTime;

        var sorted = frameTimes.OrderBy(x => x).ToList();
        float p95 = sorted[(int)(sorted.Count * 0.95f)];
        float p99 = sorted[(int)(sorted.Count * 0.99f)];

        long memPeak = memSamples.Max();
        float memPeakMB = memPeak / (1024f * 1024f);

        // GC 分配估算（最后 - 最前，除以帧数）
        long gcDelta = gcSamples.Last() - gcSamples.First();
        float gcPerFrameKB = (gcDelta / 1024f) / frameTimes.Count;
        if (gcPerFrameKB < 0) gcPerFrameKB = 0;

        float loadTime = loadEndTime - loadStartTime;

        string json = $@"{{
  ""version"": ""1.0"",
  ""timestamp"": ""{System.DateTime.UtcNow:yyyy-MM-ddTHH:mm:ssZ}"",
  ""commit"": ""{commitHash}"",
  ""run_index"": {runIndex},
  ""total_runs"": {totalRuns},
  ""environment"": {{
    ""machine_id"": ""{SystemInfo.deviceName}"",
    ""os"": ""{SystemInfo.operatingSystem}"",
    ""cpu"": ""{SystemInfo.processorType}"",
    ""ram_gb"": {SystemInfo.systemMemorySize / 1024},
    ""gpu"": ""{SystemInfo.graphicsDeviceName}""
  }},
  ""metrics"": {{
    ""fps_avg"": {{ ""value"": {fps:F1}, ""unit"": ""fps"", ""lower_is_better"": false }},
    ""memory_peak_mb"": {{ ""value"": {memPeakMB:F1}, ""unit"": ""MB"", ""lower_is_better"": true }},
    ""gc_alloc_per_frame_kb"": {{ ""value"": {gcPerFrameKB:F1}, ""unit"": ""KB"", ""lower_is_better"": true }},
    ""load_time_sec"": {{ ""value"": {loadTime:F2}, ""unit"": ""seconds"", ""lower_is_better"": true }},
    ""frame_time_p99_ms"": {{ ""value"": {p99:F1}, ""unit"": ""ms"", ""lower_is_better"": true }}
  }},
  ""diagnostics"": {{
    ""fps_avg"": {{
      ""frame_time_avg_ms"": {avgFrameTime:F2},
      ""frame_time_p95_ms"": {p95:F1},
      ""frame_time_p99_ms"": {p99:F1},
      ""total_frames"": {frameTimes.Count}
    }},
    ""memory_peak_mb"": {{
      ""note"": ""Profiler.GetTotalAllocatedMemoryLong""
    }}
  }}
}}";

        File.WriteAllText(outputPath, json);
        Debug.Log($"[PerfBenchmark] Results written to {outputPath}");
        Debug.Log($"[PerfBenchmark] FPS={fps:F1} | Mem={memPeakMB:F1}MB | GC/f={gcPerFrameKB:F1}KB | Load={loadTime:F2}s");
    }

    static string GetEnvOr(string key, string fallback)
    {
        string val = System.Environment.GetEnvironmentVariable(key);
        return string.IsNullOrEmpty(val) ? fallback : val;
    }
}
CSEOF
  echo "  → $BENCHMARK_CS"
fi

# ---------------------------------------------------------------------------
# 执行多次采集
# ---------------------------------------------------------------------------
echo "🔍 采集 Unity 性能指标 ($RUNS 次运行)"
echo "   项目: $PROJECT_PATH"
echo "   场景: $BENCHMARK_SCENE"
echo "   预热: ${WARMUP_FRAMES} 帧 | 测量: ${MEASURE_FRAMES} 帧"
echo ""

for i in $(seq 1 "$RUNS"); do
  RESULT_FILE="$OUTPUT_DIR/result_${i}.json"

  echo "  运行 $i/$RUNS..."

  # 设置环境变量，Unity batch mode 运行场景
  export PERF_WARMUP_FRAMES="$WARMUP_FRAMES"
  export PERF_MEASURE_FRAMES="$MEASURE_FRAMES"
  ABS_OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
  export PERF_OUTPUT_PATH="${ABS_OUTPUT_DIR}/result_${i}.json"
  export PERF_RUN_INDEX="$i"
  export PERF_TOTAL_RUNS="$RUNS"
  export PERF_COMMIT="$COMMIT"

  # Unity batch mode: 打开项目 → 打开场景 → 进入 Play Mode → PerfBenchmark 自动运行
  timeout "$TIMEOUT_SEC" "$UNITY" \
    -projectPath "$PROJECT_PATH" \
    -executeMethod "PerfBenchmark.RunBatch" \
    -batchmode \
    -nographics \
    -logFile "$OUTPUT_DIR/unity_log_${i}.txt" \
    -quit \
    2>/dev/null || true

  # 如果 batch mode 不支持直接 play，用替代方案：
  # 打开场景并运行 EditorApplication.EnterPlaymode
  if [[ ! -f "$RESULT_FILE" ]]; then
    # 回退方案：通过 -executeMethod 调用自定义入口
    timeout "$TIMEOUT_SEC" "$UNITY" \
      -projectPath "$PROJECT_PATH" \
      -openScene "$BENCHMARK_SCENE" \
      -executeMethod "PerfBenchmarkRunner.Run" \
      -batchmode \
      -logFile "$OUTPUT_DIR/unity_log_${i}.txt" \
      -quit \
      2>/dev/null || true
  fi

  if [[ ! -f "$RESULT_FILE" ]]; then
    echo "  WARNING: 第 $i 次运行未生成结果文件" >&2
    echo "  查看日志: $OUTPUT_DIR/unity_log_${i}.txt" >&2
  else
    # 打印摘要
    python3 -c "
import json
with open('$RESULT_FILE') as f:
    r = json.load(f)
m = r['metrics']
print(f\"  Run $i: FPS={m['fps_avg']['value']} | Mem={m['memory_peak_mb']['value']}MB | GC/f={m.get('gc_alloc_per_frame_kb',{}).get('value','N/A')}KB\")
" 2>/dev/null || true
  fi
done

echo ""
echo "✅ 采集完成，结果在 $OUTPUT_DIR/"
