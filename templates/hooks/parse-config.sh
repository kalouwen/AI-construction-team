#!/bin/bash
# parse-config.sh — 共享配置解析库
# 用法：source ~/.claude/hooks/parse-config.sh
#       get_patterns "区块名"  → 返回该区块下的所有模式（每行一个）
#       get_active_profile     → 返回当前激活的 profile（minimal|standard|strict）
#       should_run "hook名"    → 当前 profile 下该 hook 是否应执行（exit 0=是, exit 1=否）

# 优先找脚本同目录下的配置，找不到再 fallback 到全局
_PARSE_CONFIG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$_PARSE_CONFIG_DIR/guard-patterns.conf" ]; then
  GUARD_CONF="${GUARD_CONF:-$_PARSE_CONFIG_DIR/guard-patterns.conf}"
else
  GUARD_CONF="${GUARD_CONF:-$HOME/.claude/hooks/guard-patterns.conf}"
fi

# get_patterns <section_name>
# 提取指定区块的模式行（跳过注释和空行）
get_patterns() {
  local section="$1"
  local in_section=0

  if [ ! -f "$GUARD_CONF" ]; then
    return 1
  fi

  while IFS= read -r line; do
    # 跳过空行和注释
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue

    # 检测区块头
    if [[ "$line" =~ ^\[(.+)\]$ ]]; then
      if [[ "${BASH_REMATCH[1]}" == "$section" ]]; then
        in_section=1
      else
        # 进入了其他区块，停止
        [[ $in_section -eq 1 ]] && break
        in_section=0
      fi
      continue
    fi

    # 输出当前区块的模式
    if [[ $in_section -eq 1 ]]; then
      echo "$line"
    fi
  done < "$GUARD_CONF"
}

# patterns_to_grep_args <section_name>
# 将模式行合并为 grep -E 的单个正则（用 | 连接）
patterns_to_regex() {
  local section="$1"
  local regex=""

  while IFS= read -r pattern; do
    if [ -z "$regex" ]; then
      regex="$pattern"
    else
      regex="$regex|$pattern"
    fi
  done < <(get_patterns "$section")

  echo "$regex"
}

# get_active_profile
# 返回当前激活的 profile（默认 standard）
get_active_profile() {
  local profile
  profile=$(get_patterns "profile" | head -1 | sed 's/^active=//')
  echo "${profile:-standard}"
}

# should_run <hook_script_name>
# 检查当前 hook 是否应在当前 profile 下执行
# 返回 0=应执行, 1=跳过
should_run() {
  local hook_name="$1"
  local active_profile
  active_profile=$(get_active_profile)

  # 从 profile-map 区块读取该 hook 的允许 profile 列表
  local allowed
  allowed=$(get_patterns "profile-map" | grep "^${hook_name}=" | sed "s/^${hook_name}=//")

  # 如果没配置映射，默认 standard,strict 下执行
  if [ -z "$allowed" ]; then
    allowed="standard,strict"
  fi

  # 检查当前 profile 是否在允许列表中
  if echo ",$allowed," | grep -q ",$active_profile,"; then
    return 0
  else
    return 1
  fi
}

# log_hook_event <hook_name> <event_type> [detail]
# 记录 hook 触发事件到进化日志，供 evolution-review 分析
# event_type: block | warn | pass
log_hook_event() {
  local hook_name="$1"
  local event_type="$2"
  local detail="${3:-}"
  local evo_dir="${CLAUDE_PROJECT_DIR:-.}/.claude/evolution"

  mkdir -p "$evo_dir" 2>/dev/null || return 0
  local ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%S")
  echo "{\"ts\":\"$ts\",\"hook\":\"$hook_name\",\"event\":\"$event_type\",\"detail\":\"$detail\"}" \
    >> "$evo_dir/hooks.jsonl" 2>/dev/null || true
}
