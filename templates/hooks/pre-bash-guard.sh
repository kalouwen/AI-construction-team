#!/bin/bash
# PreToolUse Hook — Bash 命令安全守卫（配置驱动版）
# 触发时机：每次 Claude 执行 Bash 命令前
# 职责：敏感文件检测 / staged 内容扫描 / commit 格式检查 / build check / push 门禁 / 危险命令拦截
#
# 所有检测模式从 guard-patterns.conf 读取，新增模式不改脚本
#
# 退出码：
#   0 = 放行
#   2 = 阻塞（stderr 内容会反馈给 Claude）

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [ -z "$COMMAND" ]; then
  exit 0
fi

# 定位配置文件
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONF="$SCRIPT_DIR/guard-patterns.conf"
source "$SCRIPT_DIR/parse-config.sh" 2>/dev/null || true

# ============================================================
# 辅助函数：读取配置文件指定区块的模式列表
# 用法：read_section "section-name" → 每行输出一个模式
# ============================================================
read_section() {
  local section="$1"
  local in_section=false
  [ ! -f "$CONF" ] && return
  while IFS= read -r line; do
    [[ -z "$line" || "$line" =~ ^# ]] && continue
    if [[ "$line" =~ ^\[.*\] ]]; then
      if [[ "$line" == "[$section]" ]]; then
        in_section=true
      else
        $in_section && break
      fi
      continue
    fi
    $in_section && echo "$line"
  done < "$CONF"
}

# ============================================================
# 场景 1: git add — 敏感文件泄露检测
# ============================================================
if echo "$COMMAND" | grep -qE 'git\s+add'; then
  while IFS= read -r pattern; do
    if echo "$COMMAND" | grep -qi "$pattern"; then
      echo "BLOCKED: 检测到疑似敏感文件 ($pattern)。如果确实需要添加，请手动执行 git add。" >&2
      log_hook_event "pre-bash-guard" "block" "sensitive_file:$pattern"
      exit 2
    fi
  done < <(read_section "sensitive-files")
fi

# ============================================================
# 场景 2: git commit — staged 内容密钥扫描
# ============================================================
if echo "$COMMAND" | grep -qE 'git\s+commit'; then
  STAGED_CONTENT=$(git diff --cached 2>/dev/null)
  if [ -n "$STAGED_CONTENT" ]; then
    while IFS= read -r pattern; do
      if echo "$STAGED_CONTENT" | grep -qE "$pattern"; then
        echo "BLOCKED: staged 文件中检测到疑似密钥/敏感信息 (匹配: $pattern)。请检查后重试。" >&2
        log_hook_event "pre-bash-guard" "block" "secret:$pattern"
        exit 2
      fi
    done < <(read_section "secret-patterns")
  fi
fi

# ============================================================
# 场景 3: git commit -m — commit message 格式检查
# ============================================================
if echo "$COMMAND" | grep -qE 'git\s+commit\s+.*-m\s'; then
  # 提取 commit message 第一行（支持单行引号和 HEREDOC 多行格式）
  # 单行: git commit -m "feat: xxx" → 取引号内容
  # HEREDOC: git commit -m "$(cat <<'EOF'\nfeat: xxx\n..." → 取 EOF 后第一行
  COMMIT_MSG=$(echo "$COMMAND" | sed -n "s/.*-m\s*[\"']\(.*\)[\"'].*/\1/p" | head -1)
  if [ -z "$COMMIT_MSG" ]; then
    # HEREDOC 格式：提取 EOF 后的第一个非空行作为 commit message 首行
    COMMIT_MSG=$(echo "$COMMAND" | sed -n '/<<.*EOF/,/^EOF/{/<<.*EOF/d;/^EOF/d;/^\s*$/d;p;}' | head -1 | sed 's/^\s*//')
  fi
  if [ -n "$COMMIT_MSG" ]; then
    FORMAT_OK=false
    while IFS= read -r pattern; do
      if echo "$COMMIT_MSG" | grep -qE "$pattern"; then
        FORMAT_OK=true
        break
      fi
    done < <(read_section "commit-format")
    if ! $FORMAT_OK; then
      echo "BLOCKED: commit message 格式不符合规范。需要: type(scope): description 或 type: description" >&2
      echo "  允许的 type: feat|fix|refactor|docs|test|chore|style|perf|ci|build|revert" >&2
      echo "  示例: feat(auth): add login validation" >&2
      log_hook_event "pre-bash-guard" "block" "commit_format"
      exit 2
    fi
  fi
fi

# ============================================================
# 场景 4: git commit — 自动 build check
# ============================================================
if echo "$COMMAND" | grep -qE 'git\s+commit'; then
  if [ -f "package.json" ]; then
    if grep -q '"typecheck"' package.json 2>/dev/null; then
      if ! npm run --silent typecheck 2>/dev/null; then
        echo "BLOCKED: typecheck 失败，请先修复类型错误再提交。" >&2
        log_hook_event "pre-bash-guard" "block" "typecheck_fail"
        exit 2
      fi
    fi
  elif [ -f "pyproject.toml" ] || [ -f "setup.py" ]; then
    if command -v mypy &>/dev/null; then
      if ! mypy . --ignore-missing-imports 2>/dev/null; then
        echo "BLOCKED: mypy 类型检查失败，请先修复再提交。" >&2
        log_hook_event "pre-bash-guard" "block" "mypy_fail"
        exit 2
      fi
    fi
  fi
fi

# ============================================================
# 场景 5: git push — 审查门禁
# ============================================================
if echo "$COMMAND" | grep -qE 'git\s+push'; then
  MARKER=".claude/push-approved"
  if [ ! -f "$MARKER" ]; then
    echo "BLOCKED: push 前需要先通过审查。请运行 /review-pr 获取审查通过标记后再试。" >&2
    log_hook_event "pre-bash-guard" "block" "push_gate"
    exit 2
  fi
  rm -f "$MARKER"
fi

# ============================================================
# 场景 6: --no-verify 防护 — 阻止绕过 git hooks
# ============================================================
if echo "$COMMAND" | grep -qE 'git\s+(commit|push|merge|rebase)\s.*--no-verify'; then
  echo "BLOCKED: --no-verify 会跳过所有 git hooks（测试、格式校验、密钥扫描）。" >&2
  echo "  请移除 --no-verify 重新运行。如果 hook 报错，修掉 hook 抓到的问题。" >&2
  log_hook_event "pre-bash-guard" "block" "no_verify"
  exit 2
fi

# ============================================================
# 场景 7: 危险命令拦截（配置驱动）
# ============================================================
while IFS= read -r pattern; do
  if echo "$COMMAND" | grep -qE "$pattern"; then
    echo "BLOCKED: 检测到高危命令 (匹配: $pattern)，已拦截。如确需执行，请手动操作。" >&2
    log_hook_event "pre-bash-guard" "block" "dangerous:$pattern"
    exit 2
  fi
done < <(read_section "dangerous-commands")

# 默认放行
exit 0
