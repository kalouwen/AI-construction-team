#!/usr/bin/env bash
# evolution-score.sh — Stop hook: 进化信号采集
# 每次 AI 回复后提取正负信号，写入 JSONL 日志
# 数据供 /evolution-review skill 分析，驱动框架持续进化

set -euo pipefail

HOOKS_DIR="$(cd "$(dirname "$0")" && pwd)"

# 加载共享配置
if [ -f "$HOOKS_DIR/parse-config.sh" ]; then
  source "$HOOKS_DIR/parse-config.sh"
  if ! should_run "evolution-score"; then exit 0; fi
fi

# 日志目录
EVO_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/evolution"
mkdir -p "$EVO_DIR"

# 读取 AI 回复
response=$(cat)

# 跳过过短的回复（可能是工具调用中间态）
if [ ${#response} -lt 20 ]; then
  exit 0
fi

# ─── 负面信号检测 ───
neg=0
signals=""

# AI 自我纠正（说明之前理解错了）
if echo "$response" | grep -qiE '抱歉|sorry|我的错|我理解错|你说得对.*改|让我修正|我搞错|确实不对'; then
  neg=$((neg + 1))
  signals="${signals}self_correction,"
fi

# 重复错误（同一问题反复出现）
if echo "$response" | grep -qiE '又.*错了|重复.*问题|again.*mistake|same issue'; then
  neg=$((neg + 2))
  signals="${signals}repeated_mistake,"
fi

# 过度道歉/合理化（可能在掩盖不确定性）
if echo "$response" | grep -qiE '可能.*没问题|大概.*行|应该.*可以吧'; then
  neg=$((neg + 1))
  signals="${signals}vague_confidence,"
fi

# ─── 正面信号检测 ───
pos=0

# 任务完成
if echo "$response" | grep -qiE '完成了|已经.*好|done|搞定|successfully|全部通过'; then
  pos=$((pos + 1))
  signals="${signals}completed,"
fi

# 先咨询再行动（遵循意图分解规则）
if echo "$response" | grep -qiE '确认后再|你觉得.*哪|要不要先|是否需要|你怎么看'; then
  pos=$((pos + 1))
  signals="${signals}consulted_user,"
fi

# 提供了多路径选择（遵循路径穷举规则）
if echo "$response" | grep -qiE '路径[A-C ABC]|方案[一二三123]|选项.*[：:]'; then
  pos=$((pos + 1))
  signals="${signals}multi_path,"
fi

# 主动标注不确定性（遵循不确定性量化规则）
if echo "$response" | grep -qiE '我不确定|需要验证|信心.*[高中低]|依据.*支持.*反对'; then
  pos=$((pos + 1))
  signals="${signals}honest_uncertainty,"
fi

# ─── 只在有信号时记录 ───
if [ $((neg + pos)) -gt 0 ]; then
  ts=$(date -u +"%Y-%m-%dT%H:%M:%S")
  # 移除末尾逗号
  signals="${signals%,}"
  echo "{\"ts\":\"$ts\",\"neg\":$neg,\"pos\":$pos,\"signals\":\"$signals\"}" >> "$EVO_DIR/scores.jsonl"
fi

exit 0
