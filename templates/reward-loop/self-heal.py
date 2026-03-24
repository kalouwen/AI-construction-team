#!/usr/bin/env python3
"""
self-heal.py — 自愈诊断引擎

读取构建/测试错误输出，匹配 friction-patterns.yaml 中的已知模式，
返回结构化诊断和修复建议。

两层使用：
  1. Driver 层：driver.py 在轮次失败后调用，写诊断注入下一轮 prompt
  2. 独立调试：开发者手动喂错误文本，排查匹配情况

用法:
  python self-heal.py <friction-patterns.yaml> --error-file <error.txt>
  python self-heal.py <friction-patterns.yaml> --error-text "error message"
  echo "error output" | python self-heal.py <friction-patterns.yaml>

选项:
  --history <fix-history.jsonl>    修复历史（用于循环检测）
  --output <path>                  诊断输出路径（默认同目录下 self-heal-diagnosis.json）

exit code: 0=可修复, 1=需升级给人类, 2=无已知模式匹配
"""

import json
import os
import re
import sys
import yaml
from datetime import datetime, timezone


def load_patterns(yaml_path):
    """加载摩擦模式注册表。"""
    with open(yaml_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    patterns = list(config.get("patterns", []))
    # 合并代码生成专用模式（如果项目启用了）
    patterns.extend(config.get("codegen_patterns", []))

    return config.get("settings", {}), patterns


def match_error(error_text, patterns):
    """将错误文本与已知模式匹配。返回所有命中的模式。

    每个 pattern 最多匹配一次（命中第一条 regex 即停）。
    """
    matches = []

    for pattern in patterns:
        for regex in pattern.get("match_any", []):
            try:
                if re.search(regex, error_text, re.IGNORECASE | re.MULTILINE):
                    matches.append({
                        "pattern_id": pattern["id"],
                        "class": pattern.get("class", "code"),
                        "diagnosis": pattern.get("diagnosis", ""),
                        "fix_steps": pattern.get("fix_steps", []),
                        "comprehensive": pattern.get("comprehensive", False),
                        "requires_check": pattern.get("requires_check", False),
                        "escalate": pattern.get("escalate", False),
                        "cascade_targets": pattern.get("cascade_targets", []),
                        "matched_regex": regex,
                    })
                    break  # 此 pattern 已匹配，跳到下一个
            except re.error:
                continue

    return matches


def detect_cycle(current_matches, fix_history, patterns):
    """检测修复循环：修复 A 导致 B，修复 B 又导致 A。

    两种检测方式：
      1. cycle_indicator_for 声明式：模式 X 标注"如果我出现在修复模式 Y 之后，就是循环"
      2. 重复出现检测：同一 pattern 修了 2 次以上还在出现
    """
    if not fix_history:
        return False, ""

    current_ids = {m["pattern_id"] for m in current_matches}
    pattern_map = {p["id"]: p for p in patterns}

    # 方式 1：声明式循环指示器
    for match in current_matches:
        pid = match["pattern_id"]
        p_def = pattern_map.get(pid, {})
        indicators = p_def.get("cycle_indicator_for", [])

        for hist_entry in reversed(fix_history[-5:]):
            if hist_entry.get("pattern_id") in indicators:
                return True, (
                    f"Fix cycle: fixed '{hist_entry['pattern_id']}' → "
                    f"caused '{pid}' — these patterns form a loop"
                )

    # 方式 2：同一 pattern 反复出现（与方式 1 使用相同窗口）
    for match in current_matches:
        pid = match["pattern_id"]
        recent_same = [h for h in fix_history[-5:] if h.get("pattern_id") == pid]
        if len(recent_same) >= 3:
            return True, (
                f"Pattern '{pid}' persists after {len(recent_same)} fix attempts "
                f"— needs different approach or human intervention"
            )

    return False, ""


def generate_diagnosis(matches, fix_history, is_cycle, cycle_detail, settings):
    """生成结构化诊断报告。"""
    max_attempts = settings.get("max_fix_attempts_per_pattern", 3)

    diagnosis = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "matched_patterns": len(matches),
        "is_cycle": is_cycle,
        "cycle_detail": cycle_detail,
        "should_escalate": False,
        "matches": [],
        "recommended_action": "",
    }

    for match in matches:
        pid = match["pattern_id"]
        attempt_count = sum(1 for h in fix_history if h.get("pattern_id") == pid)
        remaining = max_attempts - attempt_count

        entry = {
            **match,
            "attempt_number": attempt_count + 1,
            "remaining_attempts": max(0, remaining),
            "exhausted": remaining <= 0,
        }
        diagnosis["matches"].append(entry)

        if match.get("escalate") or remaining <= 0:
            diagnosis["should_escalate"] = True

    # 推荐行动
    if is_cycle:
        diagnosis["recommended_action"] = (
            "ESCALATE: Fix cycle detected. "
            "Write diagnostic report and mark BLOCKED."
        )
        diagnosis["should_escalate"] = True
    elif diagnosis["should_escalate"]:
        diagnosis["recommended_action"] = (
            "ESCALATE: Pattern requires human intervention "
            "or fix attempts exhausted."
        )
    elif not matches:
        diagnosis["recommended_action"] = (
            "UNKNOWN: No known pattern matched. "
            "Read the full error output carefully and attempt a novel fix."
        )
    else:
        actions = []
        for m in diagnosis["matches"]:
            if not m["exhausted"]:
                step = m["fix_steps"][0] if m["fix_steps"] else "see pattern"
                actions.append(f"[{m['pattern_id']}] {step}")
        diagnosis["recommended_action"] = " → ".join(actions)

    return diagnosis


def main():
    if len(sys.argv) < 2:
        print(
            "用法:\n"
            "  python self-heal.py <friction-patterns.yaml> --error-file <file>\n"
            "  python self-heal.py <friction-patterns.yaml> --error-text \"...\"\n"
            "  echo \"error\" | python self-heal.py <friction-patterns.yaml>"
        )
        sys.exit(1)

    yaml_path = sys.argv[1]

    # 读取错误文本（三种输入方式）
    error_text = ""
    if "--error-file" in sys.argv:
        idx = sys.argv.index("--error-file")
        if idx + 1 < len(sys.argv):
            with open(sys.argv[idx + 1], encoding="utf-8") as f:
                error_text = f.read()
    elif "--error-text" in sys.argv:
        idx = sys.argv.index("--error-text")
        if idx + 1 < len(sys.argv):
            error_text = sys.argv[idx + 1]
    elif not sys.stdin.isatty():
        error_text = sys.stdin.read()

    if not error_text:
        print("Error: No error text provided", file=sys.stderr)
        sys.exit(1)

    # 读取修复历史（用于循环检测）
    fix_history = []
    if "--history" in sys.argv:
        idx = sys.argv.index("--history")
        if idx + 1 < len(sys.argv):
            history_path = sys.argv[idx + 1]
            if os.path.exists(history_path):
                with open(history_path, encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            fix_history.append(json.loads(line))

    # 输出路径
    output_path = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]

    # 加载模式 → 匹配 → 循环检测 → 诊断
    settings, patterns = load_patterns(yaml_path)
    matches = match_error(error_text, patterns)
    is_cycle, cycle_detail = detect_cycle(matches, fix_history, patterns)
    diagnosis = generate_diagnosis(
        matches, fix_history, is_cycle, cycle_detail, settings
    )

    # 输出 JSON
    result_json = json.dumps(diagnosis, indent=2, ensure_ascii=False)
    print(result_json)

    # 写到文件
    if output_path is None:
        output_path = os.path.join(
            os.path.dirname(yaml_path) or ".", "self-heal-diagnosis.json"
        )
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result_json)

    # exit code: 0=可修复, 1=需升级, 2=无匹配
    if diagnosis["should_escalate"]:
        sys.exit(1)
    elif not matches:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
