#!/bin/bash
# Stop Hook — Claude 完成回复后批量格式化
# 触发时机：Claude 每次回复结束后
#
# 为什么不在 PostToolUse（每次编辑后）格式化？
# → 每次 formatter 改文件都产生 system reminder，大量吃上下文 token
# → 在 Stop 时批量格式化，每轮回复仅跑 1 次，上下文干净

# 获取本轮修改但未暂存的文件
MODIFIED=$(git diff --name-only 2>/dev/null)

if [ -z "$MODIFIED" ]; then
  exit 0
fi

for FILE in $MODIFIED; do
  # 跳过不存在的文件（可能被删除了）
  if [ ! -f "$FILE" ]; then
    continue
  fi

  case "$FILE" in
    # JavaScript / TypeScript / Web
    *.ts|*.tsx|*.js|*.jsx|*.json|*.css|*.scss|*.html|*.vue|*.svelte)
      if command -v npx &>/dev/null; then
        npx prettier --write "$FILE" 2>/dev/null
      fi
      ;;
    # Python
    *.py)
      if command -v black &>/dev/null; then
        black "$FILE" 2>/dev/null
      elif command -v autopep8 &>/dev/null; then
        autopep8 --in-place "$FILE" 2>/dev/null
      fi
      ;;
    # Go
    *.go)
      if command -v gofmt &>/dev/null; then
        gofmt -w "$FILE" 2>/dev/null
      fi
      ;;
    # Rust
    *.rs)
      if command -v rustfmt &>/dev/null; then
        rustfmt "$FILE" 2>/dev/null
      fi
      ;;
    # C#
    *.cs)
      if command -v dotnet-format &>/dev/null; then
        dotnet format --include "$FILE" 2>/dev/null
      fi
      ;;
  esac
done

exit 0
