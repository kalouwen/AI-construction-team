#!/usr/bin/env bash
# =============================================================================
# Jest 测试采集器
#
# 运行 Jest 测试，解析 JSON 输出，转换为标准 result.json 格式
#
# 用法: bash collector.sh <test.yaml> <output_dir>
# =============================================================================

set -euo pipefail

export CONFIG="${1:?用法: collector.sh <test.yaml> <output_dir>}"
OUTPUT_DIR="${2:?缺少输出目录}"

mkdir -p "$OUTPUT_DIR"

COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

# 运行 Jest
JEST_OUTPUT="$OUTPUT_DIR/_jest_raw.json"
echo "Running Jest..."
npx jest --json --outputFile "$JEST_OUTPUT" 2>/dev/null || true

if [[ ! -f "$JEST_OUTPUT" ]]; then
  echo "ERROR: Jest did not produce output" >&2
  exit 1
fi

# 转换为标准格式
python - "$JEST_OUTPUT" "$OUTPUT_DIR/result_1.json" "$COMMIT" << 'PYEOF'
import json, sys, os
from datetime import datetime, timezone

jest_path = sys.argv[1]
output_path = sys.argv[2]
commit = sys.argv[3]

with open(jest_path) as f:
    jest = json.load(f)

# 收集通过/失败的测试名
passed = []
failed = []

for suite in jest.get("testResults", []):
    for test in suite.get("testResults", []):
        full_name = test.get("fullName") or test.get("title", "unknown")
        status = test.get("status", "")

        if status == "passed":
            passed.append(full_name)
        elif status == "failed":
            messages = test.get("failureMessages", [])
            failed.append({
                "name": full_name,
                "message": messages[0][:500] if messages else "",
                "file": suite.get("name", ""),
                "duration_sec": round(test.get("duration", 0) / 1000, 2),
            })

skipped = []
for suite in jest.get("testResults", []):
    for test in suite.get("testResults", []):
        if test.get("status") == "pending":
            skipped.append(test.get("fullName") or test.get("title", "unknown"))

total = jest.get("numTotalTests", 0)
num_passed = jest.get("numPassedTests", 0)
num_failed = jest.get("numFailedTests", 0)
num_skipped = jest.get("numPendingTests", 0)
pass_rate = round((num_passed / total * 100), 1) if total > 0 else 0
duration = round((jest.get("testResults", [{}])[-1].get("endTime", 0) -
                   jest.get("startTime", 0)) / 1000, 1) if jest.get("startTime") else 0

# 覆盖率（如果有）
coverage_pct = 0
cov_map = jest.get("coverageMap", {})
if cov_map:
    total_stmts = 0
    covered_stmts = 0
    for file_cov in cov_map.values():
        s = file_cov.get("statementMap", {})
        sc = file_cov.get("s", {})
        total_stmts += len(s)
        covered_stmts += sum(1 for v in sc.values() if v > 0)
    coverage_pct = round(covered_stmts / total_stmts * 100, 1) if total_stmts > 0 else 0

result = {
    "version": "1.0",
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "commit": commit,
    "environment": {
        "machine_id": os.environ.get("HOSTNAME", os.environ.get("COMPUTERNAME", "unknown")),
        "os": sys.platform,
        "framework": "jest",
    },
    "metrics": {
        "test_total": {"value": total, "unit": "count", "lower_is_better": False},
        "test_passed": {"value": num_passed, "unit": "count", "lower_is_better": False},
        "test_failed": {"value": num_failed, "unit": "count", "lower_is_better": True},
        "test_skipped": {"value": num_skipped, "unit": "count", "lower_is_better": True},
        "pass_rate": {"value": pass_rate, "unit": "%", "lower_is_better": False},
        "test_duration_sec": {"value": duration, "unit": "seconds", "lower_is_better": True},
        "coverage_pct": {"value": coverage_pct, "unit": "%", "lower_is_better": False},
    },
    "tests": {
        "passed": sorted(passed),
        "failed": failed,
        "skipped": sorted(skipped),
    },
}

with open(output_path, "w") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print(f"  Total: {total} | Passed: {num_passed} | Failed: {num_failed} | Skipped: {num_skipped}")
print(f"  Pass rate: {pass_rate}% | Duration: {duration}s | Coverage: {coverage_pct}%")
PYEOF

rm -f "$JEST_OUTPUT"
echo "Done: $OUTPUT_DIR/result_1.json"
