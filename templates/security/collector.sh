#!/usr/bin/env bash
# 安全信号采集器 — 扫描变更文件中的密钥泄露
# 等价于 gitleaks，但在本地运行，不依赖 GitHub CI
# 用法: bash collector.sh <config.yaml> <output_dir>

set -euo pipefail

OUTPUT_DIR="${2:?缺少输出目录}"
mkdir -p "$OUTPUT_DIR"

# 密钥模式（和 guard-patterns.conf [secret-patterns] 一致）
PATTERNS='(PRIVATE|SECRET|ACCESS)[_-]?KEY\s*[:=]'
PATTERNS="$PATTERNS|"'(api|auth)[_-]?(key|token|secret)\s*[:=]'
PATTERNS="$PATTERNS|"'-----BEGIN.*(RSA|DSA|EC|OPENSSH).*PRIVATE.*KEY-----'
PATTERNS="$PATTERNS|"'password\s*[:=]\s*['"'"'"][^'"'"'"]{8,}'

# 扫描范围：HEAD~1 以来的变更文件
CHANGED=$(git diff --name-only HEAD~1 2>/dev/null || git diff --name-only --cached 2>/dev/null || echo "")
MATCHES=0
DETAILS=""

for file in $CHANGED; do
  # 跳过二进制和不存在的文件
  [ ! -f "$file" ] && continue
  file --mime "$file" 2>/dev/null | grep -q "text/" || continue

  hits=$(grep -cE "$PATTERNS" "$file" 2>/dev/null || echo 0)
  if [ "$hits" -gt 0 ]; then
    MATCHES=$((MATCHES + hits))
    DETAILS="${DETAILS}${file}: ${hits} potential secret(s); "
  fi
done

cat > "$OUTPUT_DIR/result_1.json" << SECEOF
{
  "version": "1.0",
  "metrics": {
    "secret_matches": {"value": $MATCHES, "unit": "count", "lower_is_better": true}
  },
  "details": "$DETAILS"
}
SECEOF

echo "Security scan: $MATCHES potential secret(s) found"
