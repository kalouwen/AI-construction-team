#!/usr/bin/env bash
# 质量信号采集器 — 扫描 TODO/FIXME/HACK + 大文件
# 等价于 weekly-quality.yml 的 CI 检查，但在本地运行
# 用法: bash collector.sh <config.yaml> <output_dir>

set -euo pipefail

OUTPUT_DIR="${2:?缺少输出目录}"
mkdir -p "$OUTPUT_DIR"

# 扫描代码文件的 TODO/FIXME/HACK 数量
CODE_INCLUDES='--include=*.cs --include=*.ts --include=*.tsx --include=*.py --include=*.go --include=*.js --include=*.jsx --include=*.rs'
EXCLUDES='--exclude-dir=.git --exclude-dir=node_modules --exclude-dir=Library --exclude-dir=Packages --exclude-dir=__pycache__ --exclude-dir=.venv'

# shellcheck disable=SC2086
TODO=$(grep -rn "TODO" $CODE_INCLUDES $EXCLUDES . 2>/dev/null | wc -l || echo 0)
# shellcheck disable=SC2086
FIXME=$(grep -rn "FIXME" $CODE_INCLUDES $EXCLUDES . 2>/dev/null | wc -l || echo 0)
# shellcheck disable=SC2086
HACK=$(grep -rn "HACK" $CODE_INCLUDES $EXCLUDES . 2>/dev/null | wc -l || echo 0)

# 超过 500 行的代码文件数量
LARGE_FILES=0
while IFS= read -r file; do
  [ ! -f "$file" ] && continue
  lines=$(wc -l < "$file" 2>/dev/null || echo 0)
  if [ "$lines" -gt 500 ]; then
    LARGE_FILES=$((LARGE_FILES + 1))
  fi
done < <(find . -type f \( -name "*.cs" -o -name "*.ts" -o -name "*.py" -o -name "*.go" -o -name "*.js" -o -name "*.rs" \) \
  -not -path "./.git/*" -not -path "*/node_modules/*" -not -path "*/Library/*" \
  -not -path "*/Packages/*" -not -path "*/__pycache__/*" 2>/dev/null)

cat > "$OUTPUT_DIR/result_1.json" << QUALEOF
{
  "version": "1.0",
  "metrics": {
    "todo_count": {"value": $TODO, "unit": "count", "lower_is_better": true},
    "fixme_count": {"value": $FIXME, "unit": "count", "lower_is_better": true},
    "hack_count": {"value": $HACK, "unit": "count", "lower_is_better": true},
    "large_files": {"value": $LARGE_FILES, "unit": "count", "lower_is_better": true}
  }
}
QUALEOF

echo "Quality scan: TODO=$TODO FIXME=$FIXME HACK=$HACK LargeFiles=$LARGE_FILES"
