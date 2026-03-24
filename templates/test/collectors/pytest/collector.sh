#!/usr/bin/env bash
# =============================================================================
# pytest 测试采集器
#
# 运行 pytest，解析 json-report 输出，转换为标准 result.json 格式
#
# 用法: bash collector.sh <test.yaml> <output_dir>
# 依赖: pytest-json-report (pip install pytest-json-report)
# =============================================================================

set -euo pipefail

export CONFIG="${1:?用法: collector.sh <test.yaml> <output_dir>}"
OUTPUT_DIR="${2:?缺少输出目录}"

mkdir -p "$OUTPUT_DIR"

COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

# 运行 pytest
PYTEST_OUTPUT="$OUTPUT_DIR/_pytest_raw.json"
echo "Running pytest..."
python -m pytest --tb=short -q --json-report --json-report-file="$PYTEST_OUTPUT" 2>/dev/null || true

if [[ ! -f "$PYTEST_OUTPUT" ]]; then
  echo "ERROR: pytest did not produce output" >&2
  echo "  Ensure pytest-json-report is installed: pip install pytest-json-report" >&2
  exit 1
fi

# 转换为标准格式
python - "$PYTEST_OUTPUT" "$OUTPUT_DIR/result_1.json" "$COMMIT" << 'PYEOF'
import json, sys, os
from datetime import datetime, timezone

report_path = sys.argv[1]
output_path = sys.argv[2]
commit = sys.argv[3]

with open(report_path) as f:
    report = json.load(f)

passed = []
failed = []
skipped = []

for test in report.get("tests", []):
    nodeid = test.get("nodeid", "unknown")
    outcome = test.get("outcome", "")
    duration = test.get("duration", 0)

    if outcome == "passed":
        passed.append(nodeid)
    elif outcome == "failed":
        # 提取失败信息
        call = test.get("call", {})
        crash = call.get("crash", {})
        longrepr = call.get("longrepr", "")

        failed.append({
            "name": nodeid,
            "message": (crash.get("message", "") or str(longrepr))[:500],
            "file": f"{crash.get('path', '')}:{crash.get('lineno', '')}",
            "duration_sec": round(duration, 2),
        })
    elif outcome == "skipped":
        skipped.append(nodeid)

summary = report.get("summary", {})
total = summary.get("total", len(passed) + len(failed) + len(skipped))
num_passed = summary.get("passed", len(passed))
num_failed = summary.get("failed", len(failed))
num_skipped = summary.get("skipped", len(skipped))
pass_rate = round(num_passed / total * 100, 1) if total > 0 else 0
duration = round(report.get("duration", 0), 1)

result = {
    "version": "1.0",
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "commit": commit,
    "environment": {
        "machine_id": os.environ.get("HOSTNAME", os.environ.get("COMPUTERNAME", "unknown")),
        "os": sys.platform,
        "framework": "pytest",
        "python_version": report.get("environment", {}).get("Python", ""),
    },
    "metrics": {
        "test_total": {"value": total, "unit": "count", "lower_is_better": False},
        "test_passed": {"value": num_passed, "unit": "count", "lower_is_better": False},
        "test_failed": {"value": num_failed, "unit": "count", "lower_is_better": True},
        "test_skipped": {"value": num_skipped, "unit": "count", "lower_is_better": True},
        "pass_rate": {"value": pass_rate, "unit": "%", "lower_is_better": False},
        "test_duration_sec": {"value": duration, "unit": "seconds", "lower_is_better": True},
        "coverage_pct": {"value": 0, "unit": "%", "lower_is_better": False},
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
print(f"  Pass rate: {pass_rate}% | Duration: {duration}s")
PYEOF

rm -f "$PYTEST_OUTPUT"
echo "Done: $OUTPUT_DIR/result_1.json"
