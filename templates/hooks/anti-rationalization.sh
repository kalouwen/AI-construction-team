#!/bin/bash
# Stop Hook — Anti-rationalization 偷懒检测
# 触发时机：Claude 每次回复结束后
# 职责：扫描回复内容中的偷懒/推脱模式，输出警告
#
# V1 简化版：纯正则匹配
# 迭代方向：未来可加 confidence 评分、上下文判断（区分真完成 vs 偷懒）

INPUT=$(cat)

# 加载共享解析库
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/parse-config.sh" 2>/dev/null || true

# Profile 检查
if ! should_run "anti-rationalization"; then
  exit 0
fi

# 获取 AI 回复内容
RESPONSE=$(echo "$INPUT" | jq -r '.assistant_response // empty')

if [ -z "$RESPONSE" ]; then
  exit 0
fi

# 从配置读取三组模式
RATIONALIZATION_REGEX=$(patterns_to_regex "rationalization-patterns")
INTENT_SKIP_REGEX=$(patterns_to_regex "intent-skip-patterns")
NOQUESTION_REGEX=$(patterns_to_regex "autoloop-noquestion-patterns")

HITS=""

# 检测偷懒/推脱
if [ -n "$RATIONALIZATION_REGEX" ]; then
  MATCH=$(echo "$RESPONSE" | grep -iE "$RATIONALIZATION_REGEX" 2>/dev/null | head -3)
  if [ -n "$MATCH" ]; then
    HITS="${HITS}[偷懒检测] $MATCH\n"
  fi
fi

# 检测意图跳过
if [ -n "$INTENT_SKIP_REGEX" ]; then
  MATCH=$(echo "$RESPONSE" | grep -iE "$INTENT_SKIP_REGEX" 2>/dev/null | head -3)
  if [ -n "$MATCH" ]; then
    HITS="${HITS}[意图跳过] $MATCH\n"
  fi
fi

# 检测自动循环提问
if [ -n "$NOQUESTION_REGEX" ]; then
  MATCH=$(echo "$RESPONSE" | grep -iE "$NOQUESTION_REGEX" 2>/dev/null | head -3)
  if [ -n "$MATCH" ]; then
    HITS="${HITS}[禁止提问] $MATCH\n"
  fi
fi

if [ -n "$HITS" ]; then
  # 全部自动通过，不打扰用户。通过 stderr 注入纠正指令让 AI 自己改正。
  echo -e "⛔ $HITS立即纠正：不要停下，不要提问，不要偷懒。继续执行下一步。" >&2
  log_hook_event "anti-rationalization" "warn" "pattern_detected"
fi

# 不阻断，只纠正
exit 0
