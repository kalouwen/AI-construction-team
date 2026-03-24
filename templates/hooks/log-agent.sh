#!/usr/bin/env bash
# SubagentStart Hook — Agent 调用审计日志
# 触发时机：每次 subagent 启动时
# 职责：记录时间戳 + agent 名到审计日志
#
# 兼容：macOS / Linux / Windows Git Bash

set -euo pipefail

PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
LOG_FILE="$PROJECT_ROOT/.claude/agent-audit.log"
INPUT=$(cat)

# 解析 agent_name（jq 优先，grep 降级）
if command -v jq &>/dev/null; then
  AGENT_NAME=$(echo "$INPUT" | jq -r '.agent_name // "unknown"')
else
  AGENT_NAME=$(echo "$INPUT" | grep -oE '"agent_name"\s*:\s*"[^"]*"' | grep -oE '"[^"]*"$' | tr -d '"')
  AGENT_NAME="${AGENT_NAME:-unknown}"
fi

# 确保目录存在
mkdir -p "$(dirname "$LOG_FILE")"

echo "$(date -Iseconds) | agent=$AGENT_NAME" >> "$LOG_FILE"
