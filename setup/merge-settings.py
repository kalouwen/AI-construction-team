#!/usr/bin/env python3
"""
merge-settings.py — 智能合并 settings.json

保留项目已有的所有 hooks 和 permissions，
只追加模板里项目没有的条目。

用法: python merge-settings.py <existing.json> <template.json> > merged.json
"""

import json
import sys
import os


def extract_commands(hook_entries):
    """提取所有 hook command 的 basename 用于去重"""
    cmds = set()
    for entry in hook_entries:
        for h in entry.get("hooks", []):
            cmd = h.get("command", "")
            # 取 basename: "bash .claude/hooks/pre-bash-guard.sh" → "pre-bash-guard.sh"
            parts = cmd.split("/")
            cmds.add(parts[-1] if parts else cmd)
    return cmds


def merge_hooks(existing_hooks, template_hooks):
    """合并 hooks：保留已有，追加缺失"""
    merged = {}

    # 先过滤掉注释 key（如 "//"、"//详见" 等），它们不是合法事件名
    existing_hooks = {k: v for k, v in existing_hooks.items() if isinstance(v, list)}
    template_hooks = {k: v for k, v in template_hooks.items() if isinstance(v, list)}

    all_events = set(list(existing_hooks.keys()) + list(template_hooks.keys()))

    for event in all_events:
        existing = existing_hooks.get(event, [])
        template = template_hooks.get(event, [])

        if not existing:
            # 项目没有这个 event 的 hooks，用模板的
            merged[event] = template
        elif not template:
            # 模板没有这个 event 的 hooks，保留项目的
            merged[event] = existing
        else:
            # 两边都有，需要合并
            existing_cmds = extract_commands(existing)
            merged[event] = list(existing)  # 先保留所有已有

            for t_entry in template:
                t_cmds = extract_commands([t_entry])
                # 如果模板的 hook 在已有里不存在，追加
                if not t_cmds.intersection(existing_cmds):
                    merged[event].append(t_entry)

    return merged


def merge_permissions(existing_perms, template_perms):
    """合并 permissions：保留已有，追加缺失"""
    merged = {}

    for key in ("allow", "deny"):
        existing = set(existing_perms.get(key, []))
        template = set(template_perms.get(key, []))
        merged[key] = sorted(existing | template)

    return merged


def main():
    if len(sys.argv) < 3:
        print("用法: python merge-settings.py <existing.json> <template.json>", file=sys.stderr)
        sys.exit(1)

    existing_path = sys.argv[1]
    template_path = sys.argv[2]

    # 读取
    existing = {}
    if os.path.exists(existing_path):
        with open(existing_path, encoding="utf-8") as f:
            existing = json.load(f)

    with open(template_path, encoding="utf-8") as f:
        template = json.load(f)

    # 合并
    merged = dict(existing)  # 保留项目的所有顶级字段

    # 合并 hooks
    merged["hooks"] = merge_hooks(
        existing.get("hooks", {}),
        template.get("hooks", {})
    )

    # 合并 permissions
    merged["permissions"] = merge_permissions(
        existing.get("permissions", {}),
        template.get("permissions", {})
    )

    # 输出（Windows 下 stdout 默认 GBK，强制 UTF-8）
    output = json.dumps(merged, indent=2, ensure_ascii=False)
    sys.stdout.buffer.write(output.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
