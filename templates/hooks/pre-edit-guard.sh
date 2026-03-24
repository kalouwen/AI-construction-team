#!/bin/bash
# PreToolUse Hook — 编辑路径守卫
# 触发时机：每次 Claude 执行 Edit/Write 前
# 职责：阻止修改受保护目录下的文件
#
# 退出码：
#   0 = 放行
#   2 = 阻塞（stderr 内容会反馈给 Claude）

INPUT=$(cat)

# jq 缺失检查：没有 jq 则无法解析输入，放行但警告
if ! command -v jq &>/dev/null; then
  echo "WARNING: jq not found, pre-edit-guard cannot parse input. Install jq for edit protection." >&2
  exit 0
fi

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.filePath // empty')

# 无法获取路径则放行
if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# 加载共享解析库
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/parse-config.sh" 2>/dev/null || true

# Profile 检查
if ! should_run "pre-edit-guard"; then
  exit 0
fi

# 读取编辑模式（默认 blocklist）
EDIT_MODE=$(get_patterns "edit-mode" | head -1)
EDIT_MODE="${EDIT_MODE:-blocklist}"

if [ "$EDIT_MODE" = "allowlist" ]; then
  # ── Allowlist 模式：只放行匹配 allowed-paths 的文件 ──
  ALLOWED=false
  while IFS= read -r pattern; do
    if echo "$FILE_PATH" | grep -qE "$pattern"; then
      ALLOWED=true
      break
    fi
  done < <(get_patterns "allowed-paths")

  if [ "$ALLOWED" = "false" ]; then
    echo "BLOCKED: 当前为 allowlist 模式，文件 $FILE_PATH 不在允许列表中。" >&2
    log_hook_event "pre-edit-guard" "block" "allowlist_denied:$FILE_PATH"
    exit 2
  fi
else
  # ── Blocklist 模式（默认）：阻断匹配 protected-paths 的文件 ──
  while IFS= read -r pattern; do
    if echo "$FILE_PATH" | grep -qE "$pattern"; then
      echo "BLOCKED: 文件 $FILE_PATH 位于受保护路径 ($pattern)。如确需修改，请先与用户确认。" >&2
      log_hook_event "pre-edit-guard" "block" "protected_path:$pattern"
      exit 2
    fi
  done < <(get_patterns "protected-paths")
fi

# ── "先搜再写"检查 ──
# 如果是 Write（创建新文件），检查 AI 是否搜索过同名内容
# 防止 AI 不查就从零开始写，忽略已有实现
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
if [ "$TOOL_NAME" = "Write" ]; then
  BASENAME=$(basename "$FILE_PATH" 2>/dev/null)
  STEM="${BASENAME%.*}"
  # 检查文件是否已存在（存在则是编辑不是新建，放行）
  if [ ! -f "$FILE_PATH" ] && [ -n "$STEM" ] && [ ${#STEM} -gt 3 ]; then
    # 新文件：发出提醒（不阻塞，但提醒 AI 检查）
    echo "⚠️ NEW FILE: Creating $BASENAME. Did you grep for existing '$STEM' implementations first? If similar code already exists, extend it instead of creating new files." >&2
  fi
fi

# 放行
exit 0
