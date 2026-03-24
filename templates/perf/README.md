---
name: perf-reward-signal
description: 性能指标自动化奖励信号系统 — 让 AI 自主跑"改代码→测性能→留/弃"的循环
---

# 性能奖励信号系统

把性能指标变成自动计算的奖励信号，驱动 AI 自主优化代码。

## 快速接入（3步）

### 1. 复制模板到你的项目

```bash
cp -r templates/perf/ <your-project>/.perf-system/
```

### 2. 配置 perf.yaml

```yaml
# 必改项
metrics:
  fps_avg:
    tier: hard              # hard/soft/info
    threshold_relative: 5   # 相对上次允许的劣化百分比

collector:
  runs: 3                   # 采集次数（取中位数）
  web:                      # 或 unity: 二选一
    url: "http://localhost:3000"
```

### 3. 录制 baseline

第一次运行采集器，用结果创建 baseline：

```bash
# Web 项目
bash .perf-system/collectors/web/collector.sh .perf-system/perf.yaml .perf/results/initial

# 用第一次结果初始化 baseline
python .perf-system/init_baseline.py .perf/results/initial .perf/baseline.json
```

## 文件说明

```
perf/
├── spec.md              协议规范（数据格式、流程定义）
├── perf.yaml            配置模板（指标、阈值、循环参数）
├── baseline.json        基准线模板（绝对 + 相对双基准）
├── judge.py             判定器（中位数对比 → pass/fail + 原因）
├── history.py           历史管理（trajectory + 摘要）
├── loop.py              循环编排（主控脚本）
├── README.md            本文件
├── collectors/
│   ├── web/             Playwright + Performance API
│   │   └── collector.sh
│   └── unity/           Unity batch mode + Profiler
│       └── collector.sh
└── test/
    ├── index.html       测试用 HTML 页面
    └── run_e2e.py       端到端验证脚本
```

## 核心流程

```
AI 改代码（每个优化点一个提交）
    ↓
采集器跑基准测试（3次取中位数）
    ↓
judge.py 对比双基准线（相对 + 绝对）
    ↓
输出: PASS/FAIL + 每项指标变化 + 瓶颈诊断
    ↓
PASS → 合并到主分支，更新相对基准
FAIL → reset，失败原因喂回 AI，继续下一轮
    ↓
history.py 记录 trajectory，更新历史摘要
    ↓
检查退出条件 → 继续/停止
```

## 单独使用各组件

### 只跑判定器

```bash
python judge.py perf.yaml baseline.json results/ verdict.json
# exit code: 0=PASS, 1=FAIL
```

### 只更新历史

```bash
python history.py perf.yaml verdict.json \
  '{"round":1,"description":"优化纹理压缩","expected":"memory -40MB","duration_sec":120}' \
  history.json trajectory.jsonl
```

### 完整自动循环

```bash
python loop.py perf.yaml           # 实际运行
python loop.py perf.yaml --dry-run # 只打印流程
```

## 设计原则

1. **采集器是唯一的技术栈相关组件** — 换技术栈只换采集器
2. **外部判定** — 判定逻辑在 Python 脚本里，不在 AI 对话中
3. **诊断数据是一等公民** — 不只是分数，要告诉 AI 瓶颈在哪
4. **双基准线防漂移** — 相对基准防单次劣化，绝对基准防累积劣化
5. **一个提交一件事** — 支持逐个评估和 cherry-pick

## 依赖

- Python 3.8+
- pyyaml (`pip install pyyaml`)
- Web 采集器额外需要: Node.js, Playwright
- Unity 采集器额外需要: Unity Editor
