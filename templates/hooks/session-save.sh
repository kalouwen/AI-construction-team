#!/bin/bash
# Stop Hook — Session Persistence 会话持久化
# 触发时机：Claude 每次回复结束后
# 职责：保存当前 session 的工作摘要，下次 session-start 时自动注入
#
# V1 简化版：保存分支 + 最近commit + 修改文件列表
# 迭代方向：
#   V2: 保存活跃 plan 的进度（哪些步骤完成了）
#   V3: 保存关键决策记录（为什么选方案A不选方案B）

# 加载共享解析库
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/parse-config.sh" 2>/dev/null || true

# Profile 检查
if ! should_run "session-save"; then
  exit 0
fi

# 只在 git 仓库内执行
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  exit 0
fi

PROJECT_DIR=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$PROJECT_DIR" ]; then
  exit 0
fi

SESSION_DIR="$PROJECT_DIR/.claude/sessions"
mkdir -p "$SESSION_DIR"

SESSION_FILE="$SESSION_DIR/latest.md"

BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
RECENT_COMMITS=$(git log --oneline -3 2>/dev/null)
MODIFIED=$(git diff --name-only 2>/dev/null | head -10)
STAGED=$(git diff --cached --name-only 2>/dev/null | head -10)
TIMESTAMP=$(date '+%Y-%m-%d %H:%M')

{
  echo "# Session 摘要 ($TIMESTAMP)"
  echo ""
  echo "**分支**: $BRANCH"
  echo ""

  if [ -n "$RECENT_COMMITS" ]; then
    echo "**最近提交**:"
    echo '```'
    echo "$RECENT_COMMITS"
    echo '```'
    echo ""
  fi

  if [ -n "$MODIFIED" ]; then
    echo "**未提交修改**:"
    echo "$MODIFIED" | while IFS= read -r f; do echo "- $f"; done
    echo ""
  fi

  if [ -n "$STAGED" ]; then
    echo "**已暂存**:"
    echo "$STAGED" | while IFS= read -r f; do echo "- $f"; done
    echo ""
  fi

  # 检查活跃 plan
  ACTIVE_PLAN=$(ls "$PROJECT_DIR/docs/exec-plans/active/"*.md 2>/dev/null | head -1)
  if [ -n "$ACTIVE_PLAN" ]; then
    echo "**活跃计划**: $(basename "$ACTIVE_PLAN")"
    echo ""
  fi
} > "$SESSION_FILE"

exit 0
