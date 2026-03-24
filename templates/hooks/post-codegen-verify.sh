#!/usr/bin/env bash
# post-codegen-verify.sh — Proto/codegen 文件变更守卫
# PostToolUse hook: 编辑 proto/schema/codegen 文件后自动提醒验证
#
# 触发条件: Edit|Write 操作命中 codegen 相关文件
# 行为: 检测到 proto/schema 文件变更 → 提醒验证生成代码一致性
#
# 支持的文件类型（可在 guard-patterns.conf [codegen-patterns] 扩展）:
#   .proto, .fbs, .thrift, .graphql, .schema, *codegen*, *generated*

set -euo pipefail

# 从 stdin 读取 hook input
INPUT=$(cat)

# 提取被编辑的文件路径
EDITED_FILE=$(echo "$INPUT" | grep -oP '"file_path"\s*:\s*"([^"]*)"' | head -1 | sed 's/.*"\([^"]*\)"/\1/' 2>/dev/null || echo "")

if [ -z "$EDITED_FILE" ]; then
  exit 0
fi

# 检测是否为 codegen 相关文件
CODEGEN_PATTERNS=(
  '\.proto$'
  '\.fbs$'
  '\.thrift$'
  '\.graphql$'
  '\.schema$'
  'codegen'
  'generated'
  '_pb\.'
  '_pb2\.'
  '\.g\.cs$'
  '\.gen\.'
)

IS_CODEGEN=false
for pattern in "${CODEGEN_PATTERNS[@]}"; do
  if echo "$EDITED_FILE" | grep -qiE "$pattern"; then
    IS_CODEGEN=true
    break
  fi
done

if [ "$IS_CODEGEN" = true ]; then
  # 输出到 stderr 作为 AI 可见的提醒（不 block，不打扰用户）
  cat >&2 <<'WARN'
⚠️ CODEGEN GUARD: Proto/schema file was edited.
Required actions before proceeding:
  1. Run codegen tool to regenerate derived files
  2. Verify generated output matches expected (diff check)
  3. Check proto direction (cs vs cc) matches target language
  4. Do NOT overwrite hand-written compatibility files
  5. Confirm all downstream consumers still compile
WARN
fi

exit 0
