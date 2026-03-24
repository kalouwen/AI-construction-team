#!/bin/bash
# PostToolUse Hook — 编辑后自检
# 触发时机：每次 Claude 编辑或写入文件后
# 职责：检查是否新增了调试语句（警告，不阻断）
#
# 退出码：
#   0 = 放行（始终放行，仅输出警告）

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty')

if [ -z "$FILE_PATH" ] || [ ! -f "$FILE_PATH" ]; then
  exit 0
fi

# 只检查 git 仓库中的文件
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  exit 0
fi

# 获取本文件新增的行（+ 开头的行）
ADDED=$(git diff -- "$FILE_PATH" 2>/dev/null | grep '^+' | grep -v '^+++')

if [ -z "$ADDED" ]; then
  exit 0
fi

# 加载共享库（用于进化日志）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/parse-config.sh" 2>/dev/null || true

WARNINGS=""

# 检测调试语句
if echo "$ADDED" | grep -qE 'console\.(log|debug|info)\(|print\(|Debug\.Log\(|fmt\.Print'; then
  WARNINGS="${WARNINGS}\n  - 检测到新增调试语句（console.log/print/Debug.Log），提交前记得清理"
fi

# 检测新增 TODO/FIXME/HACK
if echo "$ADDED" | grep -qE 'TODO|FIXME|HACK|XXX'; then
  WARNINGS="${WARNINGS}\n  - 检测到新增 TODO/FIXME 标记，确认是否需要立即处理"
fi

if [ -n "$WARNINGS" ]; then
  echo -e "WARNING ($FILE_PATH):$WARNINGS" >&2
  log_hook_event "post-edit-verify" "warn" "debug_or_todo:$FILE_PATH"
fi

exit 0
