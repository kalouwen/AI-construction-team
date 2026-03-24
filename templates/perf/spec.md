---
name: perf-reward-signal-spec
description: 性能指标自动化奖励信号系统协议规范
---

# 性能奖励信号系统协议规范

## 概述

将性能指标转化为可自动计算的奖励信号，驱动 AI 自主优化循环。

## 核心流程

```
观测 → 策略 → 执行 → 判定 → 学习 → 继续/停止
```

### 观测阶段
- 在干净基准分支上运行 profiler
- 输出：指标数值 + 瓶颈诊断 + profiler 快照

### 策略阶段
- AI 收到：当前状态报告 + 历史摘要 + 已合并改进列表
- AI 输出：N 个独立优化点，每个一句话描述预期影响

### 执行阶段
- 每个优化点一个提交（一个提交只做一件事）
- 每个提交独立测试（采集器跑 3 次取中位数）
- 逐个判定：PASS / FAIL / PARTIAL

### 判定阶段
- 双基准线对比（相对 + 绝对）
- 输出结构化结果：每项指标的变化量和判定

### 学习阶段
- 记录 trajectory（改了什么 / 预期 / 实际 / 结果）
- 更新历史摘要（有效策略 / 无效策略 / 剩余瓶颈）
- 检测收敛（连续 N 轮改善 < 1% → 切换策略）

### 退出判定
- 达到目标指标 → 停止
- 最大轮次/时长耗尽 → 停止
- 连续 M 轮无改善（含策略切换后仍无改善）→ 停止

---

## 数据格式

### 采集器输出 (result.json)

采集器是唯一的技术栈相关组件。任何采集器只要输出以下格式，整个判定链路就能通用。

```json
{
  "version": "1.0",
  "timestamp": "2026-03-16T10:30:00Z",
  "commit": "abc1234",
  "run_index": 1,
  "total_runs": 3,
  "environment": {
    "machine_id": "ci-runner-01",
    "os": "Windows 11",
    "cpu": "i7-12700",
    "ram_gb": 32,
    "gpu": "RTX 3060"
  },
  "metrics": {
    "memory_peak_mb": {
      "value": 512,
      "unit": "MB",
      "lower_is_better": true
    },
    "gc_alloc_per_frame_kb": {
      "value": 34,
      "unit": "KB",
      "lower_is_better": true
    },
    "fps_avg": {
      "value": 60,
      "unit": "fps",
      "lower_is_better": false
    },
    "build_size_mb": {
      "value": 128,
      "unit": "MB",
      "lower_is_better": true
    },
    "load_time_sec": {
      "value": 3.2,
      "unit": "seconds",
      "lower_is_better": true
    }
  },
  "diagnostics": {
    "memory_peak_mb": {
      "top_contributors": [
        { "source": "SceneLoader.LoadAssets()", "value": 180, "unit": "MB", "pct": 33 },
        { "source": "ParticlePool.Expand()", "value": 95, "unit": "MB", "pct": 17 },
        { "source": "TextureCache.Warm()", "value": 72, "unit": "MB", "pct": 13 }
      ]
    },
    "gc_alloc_per_frame_kb": {
      "top_contributors": [
        { "source": "UIManager.Update()", "value": 12, "unit": "KB", "pct": 35 },
        { "source": "EventSystem.Poll()", "value": 8, "unit": "KB", "pct": 24 }
      ]
    }
  }
}
```

### 基准线 (baseline.json)

```json
{
  "version": "1.0",
  "absolute": {
    "commit": "release-v1.0",
    "created_at": "2026-03-01T00:00:00Z",
    "metrics": {
      "memory_peak_mb": { "value": 500 },
      "gc_alloc_per_frame_kb": { "value": 30 },
      "fps_avg": { "value": 62 },
      "build_size_mb": { "value": 125 },
      "load_time_sec": { "value": 3.0 }
    }
  },
  "relative": {
    "commit": "abc1230",
    "updated_at": "2026-03-16T09:00:00Z",
    "metrics": {
      "memory_peak_mb": { "value": 510 },
      "gc_alloc_per_frame_kb": { "value": 32 },
      "fps_avg": { "value": 61 },
      "build_size_mb": { "value": 126 },
      "load_time_sec": { "value": 3.1 }
    }
  }
}
```

### 判定输出 (verdict.json)

```json
{
  "version": "1.0",
  "verdict": "FAIL",
  "commit": "abc1234",
  "timestamp": "2026-03-16T10:31:00Z",
  "summary": "1 of 5 metrics exceeded threshold",
  "details": {
    "memory_peak_mb": {
      "baseline_relative": 510,
      "baseline_absolute": 500,
      "measured": 548,
      "change_vs_relative": "+7.5%",
      "change_vs_absolute": "+9.6%",
      "threshold_relative": "5%",
      "threshold_absolute": "10%",
      "verdict": "FAIL",
      "reason": "exceeded relative threshold (+7.5% > 5%)"
    },
    "gc_alloc_per_frame_kb": {
      "baseline_relative": 32,
      "baseline_absolute": 30,
      "measured": 28,
      "change_vs_relative": "-12.5%",
      "change_vs_absolute": "-6.7%",
      "threshold_relative": "5%",
      "threshold_absolute": "10%",
      "verdict": "PASS"
    }
  },
  "diagnostics_hint": "Top memory contributor: SceneLoader.LoadAssets() at 180MB (33%)"
}
```

### 历史摘要 (history.json)

每轮循环后更新，喂给 AI 作为策略输入。

```json
{
  "version": "1.0",
  "total_rounds": 5,
  "merged_improvements": [
    {
      "round": 3,
      "commit": "abc1232",
      "description": "压缩纹理格式 RGBA32 → ETC2",
      "impact": { "memory_peak_mb": "-45MB (-8.8%)" }
    }
  ],
  "failed_attempts": [
    {
      "round": 1,
      "description": "对象池化 ParticlePool",
      "reason": "内存 -12MB 但 FPS -8%，FPS 硬指标不允许劣化"
    },
    {
      "round": 2,
      "description": "延迟加载 TextureCache",
      "reason": "内存 -30MB 但加载时间 +2s，超过软指标阈值"
    }
  ],
  "remaining_bottlenecks": [
    { "metric": "memory_peak_mb", "source": "SceneLoader.LoadAssets()", "value": 180, "unit": "MB" }
  ],
  "convergence": {
    "recent_improvement_rate": "1.2% per round",
    "rounds_without_improvement": 0,
    "strategy_switches": 0
  }
}
```

### Trajectory 记录 (trajectory.jsonl)

每轮一行，追加写入，用于事后分析。

```json
{"round": 1, "timestamp": "...", "commit": "...", "plan": "对象池化 ParticlePool", "expected": "memory -20MB", "actual": {"memory_peak_mb": "-12MB", "fps_avg": "-8%"}, "verdict": "FAIL", "reason": "FPS degradation", "duration_sec": 180}
```

---

## 配置格式 (perf.yaml)

见 `perf.yaml` 模板文件。

---

## 设计原则

1. **采集器是唯一的技术栈相关组件** — 判定器、历史管理、循环编排全部技术栈无关
2. **外部判定，不在 AI 对话内** — 判定逻辑是确定性脚本，不受 AI 幻觉影响
3. **诊断数据是一等公民** — 不只是分数，要给 AI 瓶颈热力图
4. **一个提交一件事** — 支持逐个评估和 cherry-pick
5. **双基准线防漂移** — 相对基准防单次大劣化，绝对基准防累积劣化
6. **历史喂回策略** — 每轮都比上一轮更聪明
7. **收敛检测 + 策略切换** — 不在局部最优里打转
