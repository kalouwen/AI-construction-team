#!/bin/bash
# PreCompact Hook — compact 前保留关键上下文
# 触发时机：手动 /compact 或自动 compact 前
# 输出的内容会在 compact 后重新注入，防止长对话丢失关键状态

echo "=== 关键上下文（compact 后保留）==="

if git rev-parse --is-inside-work-tree &>/dev/null; then
  BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
  echo "当前分支: $BRANCH"

  # 未提交的修改
  MODIFIED=$(git diff --name-only 2>/dev/null | head -5)
  if [ -n "$MODIFIED" ]; then
    echo "未提交修改: $MODIFIED"
  fi
fi

# 活跃执行计划
ACTIVE_PLAN=$(ls docs/exec-plans/active/*.md 2>/dev/null | head -1)
if [ -n "$ACTIVE_PLAN" ]; then
  echo ""
  echo "=== 活跃执行计划 ==="
  head -30 "$ACTIVE_PLAN"
fi

# push 标记状态
if [ -f ".claude/push-approved" ]; then
  echo ""
  echo "注意: push 审查标记已存在，可以 push。"
fi
