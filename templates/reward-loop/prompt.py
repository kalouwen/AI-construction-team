#!/usr/bin/env python3
"""
prompt.py — AI 任务 Prompt 组装器

读取观测报告 + 历史 + 策略级别 + 冻结边界，
组装成给 AI agent 的完整任务描述。

用法: python prompt.py <signals_dir> <config> [--strategy-level 1] [--output prompt.md]

strategy levels:
  1 = 参数调优（改配置/常量/阈值）
  2 = 函数优化（改实现逻辑，不改接口）
  3 = 模块重构（改架构/数据结构/接口）
  4 = 方案替换（换算法/换库/换技术路线）
"""

import hashlib
import json
import os
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


STRATEGY_DESCRIPTIONS = {
    1: {
        "name": "Parameter Tuning",
        "scope": "Only modify configuration values, constants, thresholds, and numeric parameters",
        "forbidden": "Do NOT change function signatures, add/remove files, or restructure code",
        "examples": "Adjust timing values, buffer sizes, animation durations, spawn rates",
    },
    2: {
        "name": "Function Optimization",
        "scope": "Optimize implementation within existing functions. Keep interfaces unchanged",
        "forbidden": "Do NOT add new modules, change APIs, or alter the overall architecture",
        "examples": "Better algorithms, caching, lazy initialization, reducing allocations",
    },
    3: {
        "name": "Module Refactoring",
        "scope": "Restructure code, change data structures, modify interfaces between modules",
        "forbidden": "Do NOT change the overall technology stack or add major dependencies",
        "examples": "Extract components, change data flow, introduce patterns, redesign state management",
    },
    4: {
        "name": "Approach Replacement",
        "scope": "Replace the underlying approach: different algorithms, libraries, or techniques",
        "forbidden": "Do NOT break the external API contract or remove user-facing features",
        "examples": "Switch rendering approach, replace physics library, use web workers, change build tool",
    },
}


def determine_strategy_level(history_path, config):
    """根据历史自动判断当前策略级别。"""
    if not os.path.exists(history_path):
        return 1

    with open(history_path, encoding="utf-8") as f:
        history = json.load(f)

    rounds_stuck = history.get("convergence", {}).get("rounds_without_improvement", 0)
    thresholds = config.get("strategy", {}).get("escalation", [2, 4, 6])

    if len(thresholds) >= 3 and rounds_stuck >= thresholds[2]:
        return 4
    elif len(thresholds) >= 2 and rounds_stuck >= thresholds[1]:
        return 3
    elif len(thresholds) >= 1 and rounds_stuck >= thresholds[0]:
        return 2
    return 1


def extract_top_bottleneck(observation: str) -> dict:
    """
    从观测报告中提取最高优先级的瓶颈，生成结构化假设。
    返回: {hypothesis, target_files, expected_metric, expected_direction}
    """
    hypothesis = ""
    target_files = []
    expected_metric = ""
    expected_direction = "decrease"

    # 从观测报告中提取 top_contributors 文件路径
    import re
    # 匹配形如 "source: Assets/Scripts/UIManager.cs" 或 "SceneLoader.cs" 的行
    # 支持 .tsx/.jsx/.vue/.lua 等复合扩展名，用 \b 确保不截断
    file_pattern = re.compile(
        r'(?:source|file|path)["\s:]+([^\s"\']+\.(?:cs|py|tsx|jsx|ts|js|go|rs|vue|lua|dart|swift))\b',
        re.IGNORECASE
    )
    metric_pattern = re.compile(
        r'(?:top|worst|highest)[^\n]*?([a-z_]+(?:_mb|_kb|fps|_sec|_ms|coverage))',
        re.IGNORECASE
    )

    file_matches = file_pattern.findall(observation)
    metric_matches = metric_pattern.findall(observation)

    if file_matches:
        # 取出现频率最高的前 3 个文件（认知原子化：一轮最多聚焦 3 个文件）
        from collections import Counter
        top_files = [f for f, _ in Counter(file_matches).most_common(3)]
        if len(top_files) > 3:
            top_files = top_files[:3]
        target_files = top_files
        primary_file = top_files[0] if top_files else "（见观测报告）"
        hypothesis = f"Optimize {primary_file} to reduce resource usage"

    if metric_matches:
        expected_metric = metric_matches[0]
        if "fps" in expected_metric.lower():
            expected_direction = "increase"

    return {
        "hypothesis": hypothesis or "Reduce the top bottleneck identified in Current State",
        "target_files": target_files,
        "expected_metric": expected_metric,
        "expected_direction": expected_direction,
    }


def build_prompt(signals_dir, config, strategy_level=None):
    """组装完整的 AI 任务 prompt。"""
    guardrail_cfg = config.get("guardrail", {})

    # 读取用户目标（如果有）
    goal = ""
    goal_path = os.path.join(signals_dir, "goal.txt")
    if os.path.exists(goal_path):
        with open(goal_path, encoding="utf-8") as f:
            goal = f.read().strip()

    # 自动判断策略级别
    history_path = None
    for candidate in [
        os.path.join(signals_dir, "history.json"),
        os.path.join(signals_dir, "..", "history.json"),
    ]:
        if os.path.exists(candidate):
            history_path = candidate
            break

    if strategy_level is None:
        strategy_level = determine_strategy_level(
            history_path or "", config
        )

    strategy = STRATEGY_DESCRIPTIONS.get(strategy_level, STRATEGY_DESCRIPTIONS[1])

    # 读取观测报告
    obs_path = os.path.join(signals_dir, "observation.md")
    observation = ""
    if os.path.exists(obs_path):
        with open(obs_path, encoding="utf-8") as f:
            observation = f.read()

    # 提取结构化假设（从观测报告中自动生成）
    bottleneck = extract_top_bottleneck(observation)

    # 冻结边界
    frozen = guardrail_cfg.get("frozen", [
        ".reward-loop/", ".signals/", "baseline.json",
        "signals.yaml", "*test*", "*spec*",
    ])

    # 组装 prompt
    lines = []

    if goal:
        lines.append(f"# Goal: {goal}")
    else:
        lines.append("# Optimization Task")
    lines.append("")

    # ── 核心：本轮假设和目标文件 ──
    lines.append("## This Round's Hypothesis")
    lines.append(f"**Hypothesis**: {bottleneck['hypothesis']}")
    if bottleneck["target_files"]:
        lines.append(f"**Target files** (you may ONLY modify these):")
        for tf in bottleneck["target_files"]:
            lines.append(f"  - `{tf}`")
    else:
        lines.append("**Target files**: Identify from Current State below, then modify ONLY those files.")
    if bottleneck["expected_metric"]:
        lines.append(
            f"**Expected outcome**: `{bottleneck['expected_metric']}` should "
            f"{bottleneck['expected_direction']}"
        )
    lines.append("")
    lines.append("> **HARD CONSTRAINT**: Modifying any file NOT listed above will be automatically")
    lines.append("> rejected by guardrail. If you need to touch other files, revise your hypothesis.")
    lines.append("")

    lines.append(f"## Strategy: Level {strategy_level} — {strategy['name']}")
    lines.append(f"- **Scope**: {strategy['scope']}")
    lines.append(f"- **Forbidden**: {strategy['forbidden']}")
    lines.append("")

    lines.append("## Frozen Boundaries (DO NOT MODIFY)")
    for f_pattern in frozen:
        lines.append(f"- `{f_pattern}`")
    lines.append("")

    lines.append("## Rules")
    lines.append("1. ONE commit for this entire round (one change, one purpose)")
    lines.append("2. Commit message format: `perf: <what you changed and why>`")
    lines.append("3. Do NOT delete or skip tests to make them pass")
    lines.append("4. Do NOT modify scoring/evaluation logic")
    lines.append("5. Do NOT hide problems (disable rendering, increase timeouts, etc.)")
    lines.append("6. If unsure, make a smaller change rather than a larger one")
    lines.append("")

    if observation:
        lines.append("## Current State")
        lines.append(observation)
        lines.append("")

    lines.append("## Your Action")
    lines.append("1. **Understand first**: Read each target file completely before changing anything")
    lines.append("2. **State your plan**: For each file, write ONE sentence: what you will change and why")
    lines.append("3. **Implement**: Make the change in target files ONLY")
    lines.append("4. **One commit**: `git add <target_files> && git commit -m 'perf: ...'`")
    lines.append("5. Do NOT touch any file not listed in Target files above")

    return "\n".join(lines), strategy_level, bottleneck


def main():
    if len(sys.argv) < 3:
        print("用法: python prompt.py <signals_dir> <config> [--strategy-level N] [--output file]")
        sys.exit(1)

    signals_dir = sys.argv[1]
    config_path = sys.argv[2]

    strategy_level = None
    output_path = None

    if "--strategy-level" in sys.argv:
        idx = sys.argv.index("--strategy-level")
        if idx + 1 < len(sys.argv):
            strategy_level = int(sys.argv[idx + 1])

    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]

    config = load_yaml(config_path)
    prompt, level, bottleneck = build_prompt(signals_dir, config, strategy_level)

    # 默认输出路径
    if output_path is None:
        output_path = os.path.join(signals_dir, "prompt.md")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(prompt)

    # 生成 prompt 元数据（用于归因：哪个版本的 prompt 模板产生了哪个结果）
    # template_hash = prompt.py 源码的 hash（模板变了才变，用于版本归因）
    # prompt_hash   = 最终生成内容的 hash（每轮不同，用于精确复现）
    template_source = Path(__file__).read_text(encoding="utf-8")
    template_hash = hashlib.sha256(template_source.encode()).hexdigest()[:12]
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:12]

    meta = {
        "template_hash": template_hash,
        "prompt_hash": prompt_hash,
        "strategy_level": level,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hypothesis": bottleneck["hypothesis"],
        "target_files": bottleneck["target_files"],      # guardrail 用这个做文件级白名单
        "expected_metric": bottleneck["expected_metric"],
        "expected_direction": bottleneck["expected_direction"],
    }
    meta_path = os.path.join(signals_dir, "prompt_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    print(f"Strategy level: {level} ({STRATEGY_DESCRIPTIONS[level]['name']})")
    print(f"Prompt saved to: {output_path}")
    print(f"Prompt meta: {meta_path} (template={template_hash}, prompt={prompt_hash})")
    print(f"Length: {len(prompt)} chars")


if __name__ == "__main__":
    main()
