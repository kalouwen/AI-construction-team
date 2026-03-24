#!/bin/bash
# ============================================================
# Harness 一键部署脚本
# 用法：在目标项目目录下运行
#   bash "/c/AI for better/setup/deploy.sh"
#
# 它会自动：
# 1. 检测项目类型（Node/Python/Unity/Go/Rust...）
# 2. 复制 hooks 和 skills 到正确位置
# 3. 生成适配的 settings.json 和 CLAUDE.md
# 4. 只在需要你选择时暂停提问
# ============================================================

set -e

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# 模板目录（此脚本所在位置的上级）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$(cd "$SCRIPT_DIR/../templates" && pwd)"
PROJECT_DIR="$(pwd)"

# 找 Python（Windows 上可能只有 python，没有 python3）
PY=""
if command -v python3 &>/dev/null; then PY="python3"
elif command -v python &>/dev/null; then PY="python"
fi

# 部署日志（供仪表盘读取）
mkdir -p .deploy
DEPLOY_LOG=".deploy/deploy-log.jsonl"
: > "$DEPLOY_LOG"   # 清空
log_deploy() {
  local step="$1" status="$2" detail="$3"
  local ts
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "")
  echo "{\"step\":\"$step\",\"status\":\"$status\",\"detail\":\"$detail\",\"time\":\"$ts\"}" >> "$DEPLOY_LOG"
}

echo ""
echo -e "${BOLD}========================================${NC}"
echo -e "${BOLD}  Harness 自动化体系 — 一键部署${NC}"
echo -e "${BOLD}========================================${NC}"
echo ""

# ============================================================
# Step 1: 分析项目（读懂项目，生成部署计划）
# ============================================================
echo -e "${BLUE}[Step 1/6]${NC} 分析项目..."

# 用 analyze-project.py 读项目文档和代码结构，生成 plan.json
$PY "$SCRIPT_DIR/analyze-project.py" "$PROJECT_DIR"

# 同时跑 detect-project.sh 获取构建/测试命令（这些 analyze 不负责）
DETECT_RESULT=$(bash "$SCRIPT_DIR/detect-project.sh" "$PROJECT_DIR")
_pj() { echo "$DETECT_RESULT" | $PY -c "import sys,json; d=json.load(sys.stdin); print(d.get('$1',''))" 2>/dev/null; }

# 从 plan.json 读项目画像
PLAN_FILE=".deploy/plan.json"
_plan() { $PY -c "import json; d=json.load(open('$PLAN_FILE',encoding='utf-8')); print(d$1)" 2>/dev/null; }
_plan_bool() { $PY -c "import json; d=json.load(open('$PLAN_FILE',encoding='utf-8')); print('y' if d$1 else 'n')" 2>/dev/null; }
_plan_action() { $PY -c "
import json
d=json.load(open('$PLAN_FILE',encoding='utf-8'))
for dec in d['decisions']:
    if dec['component']=='$1':
        print(dec['action'])
        break
else:
    print('skip')
" 2>/dev/null; }

# 项目基本信息
LANGUAGE=$(_plan "['project']['language']")
PROJECT_TYPE=$(_plan "['project']['type']")
PROJECT_NAME=$(basename "$PROJECT_DIR")
HAS_GIT=$(_plan_bool "['project']['has_git']")
HAS_TESTS=$(_plan_bool "['project']['has_tests']")

# 构建/测试命令从 detect-project.sh 获取（analyze 不负责这些）
BUILD_CMD=$(_pj build_cmd)
TEST_CMD=$(_pj test_cmd)
TEST_UNIT_CMD=$(_pj test_unit_cmd)
TEST_E2E_CMD=$(_pj test_e2e_cmd)
LINT_CMD=$(_pj lint_cmd)
MAIN_BRANCH=$(_pj main_branch)
[ -z "$MAIN_BRANCH" ] && MAIN_BRANCH="main"

# 从 plan.json 读每个组件的部署决策
ENABLE_GIT_HOOKS=$(_plan_action "git_hooks"); [ "$ENABLE_GIT_HOOKS" = "deploy" ] && ENABLE_GIT_HOOKS="y" || ENABLE_GIT_HOOKS="n"
ENABLE_ACTIONS=$(_plan_action "github_actions"); [ "$ENABLE_ACTIONS" = "deploy" ] && ENABLE_ACTIONS="y" || ENABLE_ACTIONS="n"
ENABLE_COMMUNITY=$(_plan_action "community_files"); [ "$ENABLE_COMMUNITY" = "deploy" ] && ENABLE_COMMUNITY="y" || ENABLE_COMMUNITY="n"
ENABLE_TEST_SIGNAL=$(_plan_action "test_signal"); [ "$ENABLE_TEST_SIGNAL" = "deploy" ] && ENABLE_TEST_SIGNAL="y" || ENABLE_TEST_SIGNAL="n"
ENABLE_PERF_SIGNAL=$(_plan_action "perf_signal"); [ "$ENABLE_PERF_SIGNAL" = "deploy" ] && ENABLE_PERF_SIGNAL="y" || ENABLE_PERF_SIGNAL="n"
ENABLE_REWARD_LOOP=$(_plan_action "reward_loop"); [ "$ENABLE_REWARD_LOOP" = "deploy" ] && ENABLE_REWARD_LOOP="y" || ENABLE_REWARD_LOOP="n"
ENABLE_CONFIG_FILES="y"  # 配置文件始终部署
ENABLE_FORMAT="y"
ENABLE_BUILD_CHECK="n"
ENABLE_PUSH_GATE="y"

# profile 保护路径（从 profile 文件加载，如果有的话）
PROFILE_PROTECTED_PATHS=""
PROFILE_FROZEN_TESTS=""
PROFILE_FILE="$TEMPLATE_DIR/profiles/default.sh"
if [ -f "$TEMPLATE_DIR/profiles/$LANGUAGE.sh" ]; then
  PROFILE_FILE="$TEMPLATE_DIR/profiles/$LANGUAGE.sh"
fi
# 只读保护路径，不覆盖 ENABLE_* （plan.json 的决策优先）
PROFILE_NAME=$(basename "$PROFILE_FILE" .sh)
eval "$(grep -E '^PROFILE_' "$PROFILE_FILE" 2>/dev/null)"

# ============================================================
# 检测部署模式：fresh（全新项目）或 update（已有配置）
# ============================================================
DEPLOY_MODE="fresh"
if [ -d ".claude/hooks" ] || [ -f "CLAUDE.md" ]; then
  DEPLOY_MODE="update"
  echo ""
  echo -e "${YELLOW}检测到已有 AI 环境配置，将使用 update 模式：${NC}"
  echo -e "  - hooks：${GREEN}更新到最新版${NC}（始终覆盖，由 harness 管理）"
  echo -e "  - guard-patterns.conf：${GREEN}合并追加${NC}（保留已有规则）"
  echo -e "  - CLAUDE.md：${YELLOW}保留不覆盖${NC}（用户自定义）"
  echo -e "  - Rules / Agents / Skills：${GREEN}仅添加缺失项${NC}"
fi

# ============================================================
# Step 2: 展示部署计划（plan.json 的决策）
# ============================================================
echo ""
echo -e "${BLUE}[Step 2/6]${NC} 部署计划（基于项目分析）"
echo ""

log_deploy "项目分析" "success" "$PROJECT_TYPE / $LANGUAGE"

# 显示决策和原因
$PY -c "
import json,sys
d=json.load(open('$PLAN_FILE',encoding='utf-8'))
for dec in d['decisions']:
    action = dec['action']
    name = dec['component']
    reason = dec['reason']
    if action == 'deploy':
        sys.stdout.buffer.write(('    \033[0;32m+\033[0m ' + name + '\n').encode('utf-8'))
    else:
        sys.stdout.buffer.write(('    \033[1;33m-\033[0m ' + name + ' (' + reason[:50] + ')\n').encode('utf-8'))
" 2>/dev/null
echo ""

# ============================================================
# Step 4: 创建目录结构
# ============================================================
echo -e "${BLUE}[Step 3/6]${NC} 创建目录结构..."

mkdir -p .claude/hooks
mkdir -p .claude/rules
mkdir -p .claude/agents
mkdir -p .claude/evolution
mkdir -p docs/design-docs
mkdir -p docs/exec-plans/active
mkdir -p docs/exec-plans/completed
mkdir -p docs/.archive/references

echo -e "  ${GREEN}✓${NC} 目录结构已创建"

# ============================================================
# Step 5: 复制 Hook 脚本
# ============================================================
echo -e "${BLUE}[Step 4/6]${NC} 部署 Hook 脚本..."

# 核心 hooks（始终部署）
cp "$TEMPLATE_DIR/hooks/parse-config.sh" .claude/hooks/
# guard-patterns.conf: update 模式下合并（保留已有规则），fresh 模式下覆盖
if [ "$DEPLOY_MODE" = "update" ] && [ -f ".claude/hooks/guard-patterns.conf" ]; then
  # 追加模板中新增的区块（如果目标文件里不存在该区块）
  while IFS= read -r line; do
    if [[ "$line" == "["*"]" ]]; then
      if ! grep -qF "$line" .claude/hooks/guard-patterns.conf; then
        echo "" >> .claude/hooks/guard-patterns.conf
        echo "$line" >> .claude/hooks/guard-patterns.conf
        APPENDING="true"
      else
        APPENDING="false"
      fi
    elif [ "$APPENDING" = "true" ]; then
      echo "$line" >> .claude/hooks/guard-patterns.conf
    fi
  done < "$TEMPLATE_DIR/hooks/guard-patterns.conf"
  echo -e "  ${GREEN}✓${NC} guard-patterns.conf 已合并更新"
else
  cp "$TEMPLATE_DIR/hooks/guard-patterns.conf" .claude/hooks/
fi
cp "$TEMPLATE_DIR/hooks/session-start.sh" .claude/hooks/
cp "$TEMPLATE_DIR/hooks/session-save.sh" .claude/hooks/
cp "$TEMPLATE_DIR/hooks/pre-bash-guard.sh" .claude/hooks/
cp "$TEMPLATE_DIR/hooks/pre-compact-inject.sh" .claude/hooks/
cp "$TEMPLATE_DIR/hooks/pre-edit-guard.sh" .claude/hooks/
cp "$TEMPLATE_DIR/hooks/post-edit-verify.sh" .claude/hooks/
cp "$TEMPLATE_DIR/hooks/anti-rationalization.sh" .claude/hooks/

# 进化系统 hooks（信号采集 + 经验提取）
cp "$TEMPLATE_DIR/hooks/evolution-score.sh" .claude/hooks/
cp "$TEMPLATE_DIR/hooks/instinct-extract.sh" .claude/hooks/

if [ "$ENABLE_FORMAT" = "y" ] || [ "$ENABLE_FORMAT" = "Y" ]; then
  cp "$TEMPLATE_DIR/hooks/stop-format.sh" .claude/hooks/
fi

# 部署规则目录（进化系统的评估基准）
if [ -f "$TEMPLATE_DIR/evolution/rules-catalog.json" ]; then
  cp "$TEMPLATE_DIR/evolution/rules-catalog.json" .claude/evolution/
fi

# 设置可执行权限
chmod +x .claude/hooks/*.sh 2>/dev/null

# 根据选项修改 pre-bash-guard.sh
if [ "$ENABLE_PUSH_GATE" != "y" ] && [ "$ENABLE_PUSH_GATE" != "Y" ]; then
  # 注释掉 push 门禁部分
  sed -i 's/^# === 场景 3: git push/# [DISABLED] === 场景 3: git push/' .claude/hooks/pre-bash-guard.sh
  echo -e "  ${YELLOW}○${NC} push 门禁已禁用"
fi

if [ "$ENABLE_BUILD_CHECK" != "y" ] && [ "$ENABLE_BUILD_CHECK" != "Y" ]; then
  sed -i 's/^# === 场景 2: git commit/# [DISABLED] === 场景 2: git commit/' .claude/hooks/pre-bash-guard.sh
  echo -e "  ${YELLOW}○${NC} commit build check 已禁用"
fi

echo -e "  ${GREEN}✓${NC} Hook 脚本已部署"
log_deploy "Claude Code Hooks" "success" "11 个 hook + guard-patterns.conf"

# 追加 profile 的额外保护路径到 guard-patterns.conf
if [ -n "$PROFILE_PROTECTED_PATHS" ]; then
  echo "" >> .claude/hooks/guard-patterns.conf
  echo "# === Profile: $PROFILE_NAME ===" >> .claude/hooks/guard-patterns.conf
  # 将 | 分隔的路径拆成每行一条
  echo "$PROFILE_PROTECTED_PATHS" | tr '|' '\n' | while IFS= read -r path; do
    [ -n "$path" ] && echo "$path" >> .claude/hooks/guard-patterns.conf
  done
  echo -e "  ${GREEN}✓${NC} Profile 保护路径已追加到 guard-patterns.conf"
fi

# ============================================================
# Step 4b: 部署 Rules（项目级，Claude Code 自动按路径加载）
# ============================================================
echo -e "${BLUE}[Step 4b/6]${NC} 部署 Rules..."

RULES_TO_COPY=("code-style.md" "git-workflow.md" "security.md")
for RULE in "${RULES_TO_COPY[@]}"; do
  if [ "$DEPLOY_MODE" = "update" ] && [ -f ".claude/rules/$RULE" ]; then
    echo -e "  ${YELLOW}○${NC} $RULE 已存在，保留"
  else
    cp "$TEMPLATE_DIR/rules/$RULE" .claude/rules/
    echo -e "  ${GREEN}✓${NC} $RULE"
  fi
done

# ============================================================
# Step 4c: 部署 Agents（项目级）
# ============================================================
echo -e "${BLUE}[Step 4c/6]${NC} 部署 Agents..."

AGENTS_TO_COPY=("code-reviewer" "planner" "research" "security-reviewer" "test-writer")
for AGENT in "${AGENTS_TO_COPY[@]}"; do
  if [ "$DEPLOY_MODE" = "update" ] && [ -f ".claude/agents/$AGENT.md" ]; then
    echo -e "  ${YELLOW}○${NC} $AGENT 已存在，保留"
  else
    cp "$TEMPLATE_DIR/agents/$AGENT.md" .claude/agents/
    echo -e "  ${GREEN}✓${NC} $AGENT"
  fi
done

echo -e "  ${GREEN}✓${NC} 5 个 Agents 已部署 (.claude/agents/)"

# ============================================================
# Step 4d: 部署 GitHub Actions（可选）
# ============================================================
if [ "$ENABLE_ACTIONS" = "y" ] || [ "$ENABLE_ACTIONS" = "Y" ]; then
  echo -e "${BLUE}[Step 4d/6]${NC} 部署 GitHub Actions..."
  mkdir -p .github/workflows
  # Layer 2: CI 主流程（测试矩阵 + 密钥扫描）
  cp "$TEMPLATE_DIR/github-actions/ci.yml" .github/workflows/
  # Layer 2: AI PR 审查
  cp "$TEMPLATE_DIR/github-actions/pr-review.yml" .github/workflows/
  # Layer 4: 后台维护
  cp "$TEMPLATE_DIR/github-actions/weekly-quality.yml" .github/workflows/
  cp "$TEMPLATE_DIR/github-actions/dependency-audit.yml" .github/workflows/
  cp "$TEMPLATE_DIR/github-actions/stale.yml" .github/workflows/
  cp "$TEMPLATE_DIR/github-actions/auto-label.yml" .github/workflows/
  # Dependabot 配置（不放 workflows/，放 .github/ 根目录）
  cp "$TEMPLATE_DIR/config/dependabot.yml" .github/
  # Auto-labeler 路径规则
  cp "$TEMPLATE_DIR/github-community/labeler.yml" .github/

  # ── CI 按语言适配（核心：不能给 Python 项目装 Node CI） ──
  CI_YML=".github/workflows/ci.yml"
  case "$LANGUAGE" in
    python)
      # 用 Python 生成适配的 CI（替换 setup/matrix/install 块）
      $PY -c "
import sys
ci = open('$CI_YML', encoding='utf-8').read()
# 替换 lint 步骤
ci = ci.replace('Setup Node.js', 'Setup Python')
ci = ci.replace(\"uses: actions/setup-node@1a4442cacd436585916779262731d1f68e8812b5  # v3.8.0\", 'uses: actions/setup-python@v5')
ci = ci.replace('node-version-file: \".nvmrc\"', 'python-version: \"3.12\"')
ci = ci.replace(\"cache: \\\"npm\\\"\", '')
ci = ci.replace('run: npm ci', 'run: pip install ruff 2>/dev/null || true')
# 替换 test matrix
ci = ci.replace('Node \${{ matrix.version }}', 'Python \${{ matrix.python-version }}')
ci = ci.replace('os: [ubuntu-latest, windows-latest]', 'os: [ubuntu-latest]')
ci = ci.replace('version: [\"20\", \"22\"]   # adjust to your supported versions', 'python-version: [\"3.11\", \"3.12\"]')
ci = ci.replace('Setup Node.js \${{ matrix.version }}', 'Setup Python \${{ matrix.python-version }}')
ci = ci.replace('node-version: \${{ matrix.version }}', 'python-version: \${{ matrix.python-version }}')
ci = ci.replace('Install dependencies\n        run: npm ci', 'Install dependencies\n        run: pip install -r requirements.txt 2>/dev/null || pip install pytest')
ci = ci.replace(\"matrix.version == '20'\", \"matrix.python-version == '3.12'\")
# 标注
ci = ci.replace('# Installed by AI for better', '# Installed by AI for better (Python profile)')
sys.stdout.buffer.write(ci.encode('utf-8'))
" > "${CI_YML}.tmp" 2>/dev/null && mv "${CI_YML}.tmp" "$CI_YML"
      echo -e "  ${GREEN}✓${NC} ci.yml 已适配 Python（setup-python + pytest）"
      ;;
    go)
      echo -e "  ${YELLOW}⚠${NC}  ci.yml 需要手动适配 Go（setup-go + go test）"
      ;;
    csharp|unity)
      echo -e "  ${YELLOW}⚠${NC}  ci.yml 需要手动适配 C#/Unity"
      ;;
    *)
      # Node.js 或其他：保持模板默认（Node.js）
      ;;
  esac

  # 测试命令替换
  sed -i "s|__TEST_CMD__|$TEST_CMD|g" "$CI_YML"
  # lint 命令替换
  if [ -z "$LINT_CMD" ] || [ "$LINT_CMD" = "null" ] || [ "$LINT_CMD" = "# 请填写 lint 命令" ]; then
    sed -i 's|"__LINT_CMD__" != ""|false|g' "$CI_YML"
    sed -i 's|__LINT_CMD__|true|g' "$CI_YML"
  else
    sed -i "s|__LINT_CMD__|$LINT_CMD|g" "$CI_YML"
  fi
  echo -e "  ${GREEN}✓${NC} 6 个 GitHub Actions 已部署 (.github/workflows/)"
  echo -e "  ${GREEN}✓${NC} dependabot.yml 已部署 (.github/dependabot.yml)"
  echo -e "  ${YELLOW}⚠${NC}  pr-review.yml 需要在 GitHub Secrets 中配置 ANTHROPIC_API_KEY"
fi

# ============================================================
# Step 4d2: 部署安全 + 质量信号（始终部署，不依赖 CI）
# ============================================================
echo -e "${BLUE}[Step 4d2/6]${NC} 部署本地安全 + 质量信号..."

mkdir -p .security .quality

cp "$TEMPLATE_DIR/security/collector.sh" .security/
cp "$TEMPLATE_DIR/security/judge.py" .security/
cp "$TEMPLATE_DIR/security/security.yaml" .security/
chmod +x .security/collector.sh 2>/dev/null

cp "$TEMPLATE_DIR/quality/collector.sh" .quality/
cp "$TEMPLATE_DIR/quality/judge.py" .quality/
cp "$TEMPLATE_DIR/quality/quality.yaml" .quality/
chmod +x .quality/collector.sh 2>/dev/null

echo -e "  ${GREEN}✓${NC} 安全信号（密钥扫描，零容忍）"
echo -e "  ${GREEN}✓${NC} 质量信号（TODO/FIXME/大文件棘轮）"

# ============================================================
# Step 4e: 部署测试奖励信号系统（可选）
# ============================================================
if [ "$ENABLE_TEST_SIGNAL" = "y" ] || [ "$ENABLE_TEST_SIGNAL" = "Y" ]; then
  echo -e "${BLUE}[Step 4e/6]${NC} 部署测试信号系统..."
  mkdir -p .test-system/collectors

  cp "$TEMPLATE_DIR/test/test.yaml" .test-system/
  cp "$TEMPLATE_DIR/test/init_baseline.py" .test-system/
  cp "$TEMPLATE_DIR/test/test_judge.py" .test-system/

  # 按语言选择采集器
  case "$LANGUAGE" in
    node|javascript|typescript)
      mkdir -p .test-system/collectors/jest
      cp "$TEMPLATE_DIR/test/collectors/jest/collector.sh" .test-system/collectors/jest/
      chmod +x .test-system/collectors/jest/collector.sh 2>/dev/null
      echo -e "  ${GREEN}✓${NC} 测试信号系统已部署（Jest 采集器）"
      ;;
    python)
      mkdir -p .test-system/collectors/pytest
      cp "$TEMPLATE_DIR/test/collectors/pytest/collector.sh" .test-system/collectors/pytest/
      chmod +x .test-system/collectors/pytest/collector.sh 2>/dev/null
      echo -e "  ${GREEN}✓${NC} 测试信号系统已部署（pytest 采集器）"
      ;;
    *)
      # 两个都复制，让用户选
      mkdir -p .test-system/collectors/jest .test-system/collectors/pytest
      cp "$TEMPLATE_DIR/test/collectors/jest/collector.sh" .test-system/collectors/jest/
      cp "$TEMPLATE_DIR/test/collectors/pytest/collector.sh" .test-system/collectors/pytest/
      chmod +x .test-system/collectors/jest/collector.sh .test-system/collectors/pytest/collector.sh 2>/dev/null
      echo -e "  ${GREEN}✓${NC} 测试信号系统已部署（Jest + pytest 采集器，请选择适合的）"
      ;;
  esac
fi

# ============================================================
# Step 4f: 部署性能奖励信号系统（可选）
# ============================================================
if [ "$ENABLE_PERF_SIGNAL" = "y" ] || [ "$ENABLE_PERF_SIGNAL" = "Y" ]; then
  echo -e "${BLUE}[Step 4f/6]${NC} 部署性能信号系统..."
  mkdir -p .perf-system/collectors

  cp "$TEMPLATE_DIR/perf/README.md" .perf-system/
  cp "$TEMPLATE_DIR/perf/spec.md" .perf-system/
  cp "$TEMPLATE_DIR/perf/perf.yaml" .perf-system/
  cp "$TEMPLATE_DIR/perf/baseline.json" .perf-system/
  cp "$TEMPLATE_DIR/perf/judge.py" .perf-system/
  cp "$TEMPLATE_DIR/perf/history.py" .perf-system/
  cp "$TEMPLATE_DIR/perf/init_baseline.py" .perf-system/
  cp "$TEMPLATE_DIR/perf/loop.py" .perf-system/

  # 按框架选择采集器
  case "$FRAMEWORK" in
    unity)
      mkdir -p .perf-system/collectors/unity
      cp "$TEMPLATE_DIR/perf/collectors/unity/collector.sh" .perf-system/collectors/unity/
      chmod +x .perf-system/collectors/unity/collector.sh 2>/dev/null
      echo -e "  ${GREEN}✓${NC} 性能信号系统已部署（Unity 采集器）"
      ;;
    *)
      mkdir -p .perf-system/collectors/web
      cp "$TEMPLATE_DIR/perf/collectors/web/collector.sh" .perf-system/collectors/web/
      chmod +x .perf-system/collectors/web/collector.sh 2>/dev/null
      echo -e "  ${GREEN}✓${NC} 性能信号系统已部署（Web 采集器）"
      ;;
  esac

  echo -e "  ${YELLOW}⚠${NC}  部署后需要运行 init_baseline.py 初始化性能基准线"
fi

# ============================================================
# Step 4g: 部署 Reward Loop（可选，需要 test + perf）
# ============================================================
if [ "$ENABLE_REWARD_LOOP" = "y" ] || [ "$ENABLE_REWARD_LOOP" = "Y" ]; then
  echo -e "${BLUE}[Step 4g/6]${NC} 部署 Reward Loop（全自动进化循环）..."
  mkdir -p .reward-loop

  # 核心组件
  cp "$TEMPLATE_DIR/reward-loop/driver.py" .reward-loop/
  cp "$TEMPLATE_DIR/reward-loop/orchestrator.py" .reward-loop/
  cp "$TEMPLATE_DIR/reward-loop/signals.yaml" .reward-loop/
  # 修正 signals.yaml 中的相对路径（适配实际部署目录）
  sed -i "s|\.\./test/|../.test-system/|g" .reward-loop/signals.yaml
  sed -i "s|\.\./perf/|../.perf-system/|g" .reward-loop/signals.yaml
  sed -i "s|\.\./security/|../.security/|g" .reward-loop/signals.yaml
  sed -i "s|\.\./quality/|../.quality/|g" .reward-loop/signals.yaml

  # 按语言适配 signals.yaml 中的采集器路径
  case "$LANGUAGE" in
    python)
      # Python 项目用 pytest 采集器，不用 jest
      sed -i "s|collectors/jest/collector.sh|collectors/pytest/collector.sh|g" .reward-loop/signals.yaml
      # perf 默认关闭（Python 项目不需要 web/Unity 性能测试）
      if [ "$ENABLE_PERF_SIGNAL" != "y" ]; then
        $PY -c "
import yaml,sys
with open('.reward-loop/signals.yaml', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)
for sig in cfg.get('signals', []):
    if sig['name'] == 'perf':
        sig['enabled'] = False
with open('.reward-loop/signals.yaml', 'w', encoding='utf-8') as f:
    yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
" 2>/dev/null
      fi
      ;;
    node)
      # Node 项目默认 jest，不需要改
      ;;
    unity)
      # Unity 用自己的采集器
      sed -i "s|collectors/jest/collector.sh|collectors/unity/collector.sh|g" .reward-loop/signals.yaml
      sed -i "s|collectors/web/collector.sh|collectors/unity/collector.sh|g" .reward-loop/signals.yaml
      ;;
  esac

  # 安全机制
  cp "$TEMPLATE_DIR/reward-loop/guardrail.py" .reward-loop/
  cp "$TEMPLATE_DIR/reward-loop/circuit_breaker.py" .reward-loop/

  # 观测 + 策略
  cp "$TEMPLATE_DIR/reward-loop/observe.py" .reward-loop/
  cp "$TEMPLATE_DIR/reward-loop/prompt.py" .reward-loop/

  # 环境校准
  cp "$TEMPLATE_DIR/reward-loop/calibrate.py" .reward-loop/
  cp "$TEMPLATE_DIR/reward-loop/health-check.py" .reward-loop/
  cp "$TEMPLATE_DIR/reward-loop/dashboard.py" .reward-loop/

  echo -e "  ${GREEN}✓${NC} Reward Loop 已部署（8 个组件）"
  echo -e "    driver.py        — 全自动循环驱动器"
  echo -e "    orchestrator.py  — 多信号联合判定"
  echo -e "    guardrail.py     — 护栏 + reward hacking 检测"
  echo -e "    circuit_breaker.py — 熔断器"
  echo -e "    observe.py       — 状态诊断"
  echo -e "    prompt.py        — AI 任务组装 + 策略阶梯"
  echo -e "    calibrate.py     — 环境漂移检测"
  echo -e "    signals.yaml     — 统一配置"
  echo -e "  ${YELLOW}⚠${NC}  部署后需要编辑 signals.yaml 配置 collector 路径和冻结边界"
fi

# 辅助函数：raw .git/hooks/ 安装（非 Node/Python 项目降级方案）
_install_raw_hooks() {
  local HOOKS_GIT_DIR=".git/hooks"
  # pre-commit: unit 测试（快）
  sed -e "s|__TEST_CMD__|$TEST_CMD|g" \
      -e "s|__TEST_UNIT_CMD__|$TEST_UNIT_CMD|g" \
      "$TEMPLATE_DIR/git-hooks/pre-commit" > "$HOOKS_GIT_DIR/pre-commit"
  cp "$TEMPLATE_DIR/git-hooks/commit-msg" "$HOOKS_GIT_DIR/commit-msg"
  # pre-push: e2e 测试（完整）
  sed -e "s|__TEST_CMD__|$TEST_CMD|g" \
      -e "s|__TEST_E2E_CMD__|$TEST_E2E_CMD|g" \
      -e "s|__MAIN_BRANCH__|$MAIN_BRANCH|g" \
      "$TEMPLATE_DIR/git-hooks/pre-push" > "$HOOKS_GIT_DIR/pre-push"
  chmod +x "$HOOKS_GIT_DIR/pre-commit" "$HOOKS_GIT_DIR/commit-msg" "$HOOKS_GIT_DIR/pre-push"
  echo -e "  ${GREEN}✓${NC} 3 个 git hooks 已安装 (.git/hooks/)"
  echo -e "  ${YELLOW}⚠${NC}  hooks 不随仓库传递，新成员需手动运行 deploy.sh"
}

# ============================================================
# Step 4h: 部署 Git Hooks（本地提交门禁，Layer 1）
# ============================================================
if [ "$ENABLE_GIT_HOOKS" = "y" ] || [ "$ENABLE_GIT_HOOKS" = "Y" ]; then
  if [ "$HAS_GIT" = "true" ]; then
    echo -e "${BLUE}[Step 4h/6]${NC} 部署 git 提交门禁..."

    case "$LANGUAGE" in
      node|javascript|typescript)
        # Node.js：使用 husky，hooks 随仓库传递，npm install 后自动生效
        if command -v npm &>/dev/null; then
          echo -e "  → 安装 husky（hooks 将随仓库传递）..."
          npm install --save-dev "husky@^9" @commitlint/cli @commitlint/config-conventional 2>/dev/null
          npx husky init 2>/dev/null
          # 确保 .husky/ 目录存在（husky init 可能因网络问题未创建）
          mkdir -p .husky

          # 写入 .husky/pre-commit（unit 测试）
          sed -e "s|__TEST_CMD__|$TEST_CMD|g" \
              -e "s|__TEST_UNIT_CMD__|$TEST_UNIT_CMD|g" \
              "$TEMPLATE_DIR/git-hooks/pre-commit" > .husky/pre-commit
          chmod +x .husky/pre-commit

          # 写入 .husky/commit-msg
          cp "$TEMPLATE_DIR/git-hooks/commit-msg" .husky/commit-msg
          chmod +x .husky/commit-msg

          # 写入 .husky/pre-push（e2e 测试）
          sed -e "s|__TEST_CMD__|$TEST_CMD|g" \
              -e "s|__TEST_E2E_CMD__|$TEST_E2E_CMD|g" \
              -e "s|__MAIN_BRANCH__|$MAIN_BRANCH|g" \
              "$TEMPLATE_DIR/git-hooks/pre-push" > .husky/pre-push
          chmod +x .husky/pre-push

          # 确保 npm install 后自动初始化 husky
          node -e "
            const fs = require('fs');
            const pkg = JSON.parse(fs.readFileSync('package.json','utf8'));
            if (!pkg.scripts) pkg.scripts = {};
            if (!pkg.scripts.prepare) pkg.scripts.prepare = 'husky';
            fs.writeFileSync('package.json', JSON.stringify(pkg, null, 2) + '\n');
          " 2>/dev/null && echo -e "  ${GREEN}✓${NC} package.json 已添加 prepare: husky"

          # commitlint 配置
          if [ ! -f "commitlint.config.js" ]; then
            cp "$TEMPLATE_DIR/config/commitlint.config.js" .
            echo -e "  ${GREEN}✓${NC} commitlint.config.js 已生成"
          fi

          echo -e "  ${GREEN}✓${NC} 3 个 git hooks 已通过 husky 安装 (.husky/)"
          echo -e "  ${GREEN}✓${NC} 新成员 npm install 后自动生效，无需手动操作"
        else
          echo -e "  ${YELLOW}⚠${NC}  未找到 npm，降级为 .git/hooks/ 安装"
          _install_raw_hooks
        fi
        ;;

      python)
        # Python：使用 pre-commit 框架，配置文件随仓库传递
        if command -v pip &>/dev/null || command -v pip3 &>/dev/null; then
          echo -e "  → 安装 pre-commit 框架..."
          pip install pre-commit 2>/dev/null || pip3 install pre-commit 2>/dev/null

          if [ ! -f ".pre-commit-config.yaml" ]; then
            cat > .pre-commit-config.yaml << 'PRECOMMIT_EOF'
repos:
  - repo: local
    hooks:
      - id: check-file-size
        name: Check file size (< 500 lines)
        entry: bash -c 'for f in "$@"; do [ -f "$f" ] && lines=$(wc -l < "$f") && [ "$lines" -gt 500 ] && echo "❌ $f has $lines lines (max 500)" && exit 1; done; exit 0'
        language: system
        pass_filenames: true
        exclude: '__LARGE_FILE_EXCLUDE__'
      - id: run-tests
        name: Run tests
        entry: __TEST_CMD__
        language: system
        pass_filenames: false
        always_run: true
      - id: commit-msg-format
        name: Commit message format
        entry: bash -c 'echo "$1" | grep -qE "^(feat|fix|refactor|test|docs|chore|ci|perf|revert)(\(.+\))?: .{1,100}$" || (echo "❌ Commit format: type(scope): description" && exit 1)'
        language: system
        stages: [commit-msg]
        always_run: true
      - id: pre-push-tests
        name: Pre-push full tests
        entry: __TEST_CMD__
        language: system
        pass_filenames: false
        always_run: true
        stages: [pre-push]
PRECOMMIT_EOF
            sed -i "s|__TEST_CMD__|$TEST_CMD|g" .pre-commit-config.yaml

            # 自动扫描已有大文件，生成 exclude 白名单
            LARGE_EXCLUDE=$($PY -c "
import os, re
excludes = [r'\.lock$', r'\.min\.', r'/out/', r'/dist/', r'/build/', r'node_modules/', r'/projects/', r'/vendor/']
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules','__pycache__','venv','.venv','dist','build','Library','out','Temp','obj','bin','target','vendor','projects','packages')]
    for f in files:
        if f.endswith(('.py','.ts','.tsx','.js','.jsx','.cs','.go','.rs')):
            fp = os.path.join(root, f)
            try:
                lines = sum(1 for _ in open(fp, encoding='utf-8', errors='replace'))
                if lines > 500:
                    name = re.escape(os.path.basename(fp))
                    excludes.append(name)
            except: pass
print('|'.join(excludes))
" 2>/dev/null)
            if [ -n "$LARGE_EXCLUDE" ]; then
              sed -i "s|__LARGE_FILE_EXCLUDE__|$LARGE_EXCLUDE|g" .pre-commit-config.yaml
              echo -e "  ${GREEN}✓${NC} 已自动生成大文件白名单"
            else
              sed -i "s|__LARGE_FILE_EXCLUDE__|\.lock$|\.min\.|g" .pre-commit-config.yaml
            fi
          else
            # 已有配置文件，检查并追加缺失的 hooks
            if ! grep -q "check-file-size" .pre-commit-config.yaml; then
              # 在 hooks: 下追加 500 行检查
              sed -i '/^    hooks:$/a\      - id: check-file-size\n        name: Check file size (< 500 lines)\n        entry: bash -c '\''for f in "$@"; do [ -f "$f" ] \&\& lines=$(wc -l < "$f") \&\& [ "$lines" -gt 500 ] \&\& echo "❌ $f has $lines lines (max 500)" \&\& exit 1; done; exit 0'\''\n        language: system\n        pass_filenames: true' .pre-commit-config.yaml
              echo -e "  ${GREEN}✓${NC} 已追加 500 行文件检查"
            fi
            if ! grep -q "pre-push" .pre-commit-config.yaml; then
              # 在文件末尾追加 pre-push hook
              cat >> .pre-commit-config.yaml << 'PUSH_EOF'
      - id: pre-push-tests
        name: Pre-push full tests
        entry: __TEST_CMD__
        language: system
        pass_filenames: false
        always_run: true
        stages: [pre-push]
PUSH_EOF
              sed -i "s|__TEST_CMD__|$TEST_CMD|g" .pre-commit-config.yaml
              echo -e "  ${GREEN}✓${NC} 已追加 pre-push 测试"
            fi
          fi

          pre-commit install --hook-type pre-commit 2>/dev/null
          pre-commit install --hook-type commit-msg 2>/dev/null
          pre-commit install --hook-type pre-push 2>/dev/null
          echo -e "  ${GREEN}✓${NC} pre-commit 框架已安装（pre-commit + commit-msg + pre-push）"
          echo -e "  ${GREEN}✓${NC} 新成员 pre-commit install 后自动生效"
        else
          echo -e "  ${YELLOW}⚠${NC}  未找到 pip，降级为 .git/hooks/ 安装"
          _install_raw_hooks
        fi
        ;;

      *)
        # 其他语言（Unity/Go 等）：raw .git/hooks/，在 CONTRIBUTING.md 中说明
        _install_raw_hooks
        ;;
    esac

    echo -e "    pre-commit  — 每次 commit 前跑：$TEST_CMD"
    echo -e "    commit-msg  — 校验格式：type(scope): description"
    echo -e "    pre-push    — 自动 rebase $MAIN_BRANCH + 再跑测试"
  else
    echo -e "  ${YELLOW}○${NC} 非 git 项目，跳过 git hooks"
  fi
fi

# ============================================================
# Step 4i: 部署项目配置文件
# ============================================================
if [ "$ENABLE_CONFIG_FILES" = "y" ] || [ "$ENABLE_CONFIG_FILES" = "Y" ]; then
  echo -e "${BLUE}[Step 4i/6]${NC} 部署项目配置文件..."

  # .nvmrc 只对 Node.js 项目有意义
  if [ "$LANGUAGE" = "node" ]; then
    [ ! -f ".nvmrc" ] && cp "$TEMPLATE_DIR/config/.nvmrc" . && echo -e "  ${GREEN}✓${NC} .nvmrc"
    echo -e "  ${YELLOW}⚠${NC}  .nvmrc 默认 Node 22，按项目需求修改"
  fi
  [ ! -f ".editorconfig" ]  && cp "$TEMPLATE_DIR/config/.editorconfig" .  && echo -e "  ${GREEN}✓${NC} .editorconfig"
  [ ! -f ".shellcheckrc" ]  && cp "$TEMPLATE_DIR/config/.shellcheckrc" .  && echo -e "  ${GREEN}✓${NC} .shellcheckrc"
  [ ! -f ".gitattributes" ] && cp "$TEMPLATE_DIR/config/.gitattributes" . && echo -e "  ${GREEN}✓${NC} .gitattributes"
fi

# ============================================================
# Step 4j: 部署社区文件（CONTRIBUTING / SECURITY / PR template）
# ============================================================
if [ "$ENABLE_COMMUNITY" = "y" ] || [ "$ENABLE_COMMUNITY" = "Y" ]; then
  echo -e "${BLUE}[Step 4j/6]${NC} 部署社区文件..."
  mkdir -p .github/ISSUE_TEMPLATE

  # 替换项目名和测试命令占位符
  CONTRIBUTING=$(cat "$TEMPLATE_DIR/github-community/CONTRIBUTING.md")
  CONTRIBUTING=$(echo "$CONTRIBUTING" | sed "s|__PROJECT_NAME__|$PROJECT_NAME|g")
  CONTRIBUTING=$(echo "$CONTRIBUTING" | sed "s|__TEST_CMD__|$TEST_CMD|g")
  echo "$CONTRIBUTING" > CONTRIBUTING.md

  cp "$TEMPLATE_DIR/github-community/SECURITY.md" .
  cp "$TEMPLATE_DIR/github-community/PULL_REQUEST_TEMPLATE.md" .github/
  cp "$TEMPLATE_DIR/github-community/ISSUE_TEMPLATE/bug_report.md" .github/ISSUE_TEMPLATE/
  cp "$TEMPLATE_DIR/github-community/ISSUE_TEMPLATE/feature_request.md" .github/ISSUE_TEMPLATE/

  echo -e "  ${GREEN}✓${NC} CONTRIBUTING.md"
  echo -e "  ${GREEN}✓${NC} SECURITY.md"
  echo -e "  ${GREEN}✓${NC} .github/PULL_REQUEST_TEMPLATE.md"
  echo -e "  ${GREEN}✓${NC} .github/ISSUE_TEMPLATE/ (bug_report + feature_request)"
  echo -e "  ${YELLOW}⚠${NC}  SECURITY.md 中的安全联系邮箱需要手动填写"
fi

# ============================================================
# Step 5: 复制 Docs
# ============================================================
echo -e "${BLUE}[Step 5/6]${NC} 部署文档..."

if [ ! -f "docs/ai-friendly-checklist.md" ]; then
  cp "$TEMPLATE_DIR/docs/ai-friendly-checklist.md" docs/
  echo -e "  ${GREEN}✓${NC} docs/ai-friendly-checklist.md 已生成"
fi

# ============================================================
# Step 6: 复制 Skills（到用户级目录）
# ============================================================
echo -e "${BLUE}[Step 5/6]${NC} 部署 Skills..."

SKILLS_DIR="$HOME/.claude/skills"
SKILLS_TO_COPY=("coding-standards" "simplify" "review-pr" "security-review" "verification-loop" "pre-review" "post-review" "evolution-review")

for SKILL in "${SKILLS_TO_COPY[@]}"; do
  DEST="$SKILLS_DIR/$SKILL"
  if [ -d "$DEST" ]; then
    echo -e "  ${YELLOW}○${NC} $SKILL 已存在，跳过"
  else
    mkdir -p "$DEST"
    cp "$TEMPLATE_DIR/skills/$SKILL/SKILL.md" "$DEST/"
    echo -e "  ${GREEN}✓${NC} $SKILL 已安装"
  fi
done

# ============================================================
# Step 7: 生成配置文件
# ============================================================
echo -e "${BLUE}[Step 6/6]${NC} 生成配置文件..."

# 生成 settings.json（项目级）
HOOKS_DIR=".claude/hooks"

# 先生成模板版 settings（替换占位符）
TEMPLATE_SETTINGS_TMP=".deploy/_template_settings.json"
mkdir -p .deploy
sed "s|__HOOKS_DIR__|$HOOKS_DIR|g" "$TEMPLATE_DIR/settings.template.json" > "$TEMPLATE_SETTINGS_TMP"

if [ "$DEPLOY_MODE" = "update" ] && [ -f ".claude/settings.json" ]; then
  # update 模式：合并（保留项目已有 hooks，只追加缺失的）
  echo -e "  合并 settings.json（保留项目 hooks，追加新增）..."
  $PY "$SCRIPT_DIR/merge-settings.py" .claude/settings.json "$TEMPLATE_SETTINGS_TMP" > .claude/settings.json.new 2>/dev/null
  if [ -s ".claude/settings.json.new" ]; then
    mv .claude/settings.json.new .claude/settings.json
    echo -e "  ${GREEN}✓${NC} .claude/settings.json 已合并更新"
  else
    echo -e "  ${YELLOW}⚠${NC}  合并失败，保留原文件不动"
    rm -f .claude/settings.json.new
  fi
else
  # fresh 模式：全新生成
  cp "$TEMPLATE_SETTINGS_TMP" .claude/settings.json
  echo -e "  ${GREEN}✓${NC} .claude/settings.json 已生成"
fi

rm -f "$TEMPLATE_SETTINGS_TMP"

# 生成 CLAUDE.md
CLAUDE_MD=$(cat "$TEMPLATE_DIR/CLAUDE.template.md")
CLAUDE_MD=$(echo "$CLAUDE_MD" | sed "s|__PROJECT_NAME__|$PROJECT_NAME|g")
CLAUDE_MD=$(echo "$CLAUDE_MD" | sed "s|__BUILD_CMD__|$BUILD_CMD|g")
CLAUDE_MD=$(echo "$CLAUDE_MD" | sed "s|__TEST_CMD__|$TEST_CMD|g")
CLAUDE_MD=$(echo "$CLAUDE_MD" | sed "s|__LINT_CMD__|$LINT_CMD|g")

# CLAUDE.md: update 模式下不覆盖（用户自定义），fresh 模式下生成
if [ "$DEPLOY_MODE" = "update" ] && [ -f "CLAUDE.md" ]; then
  echo -e "  ${YELLOW}○${NC} CLAUDE.md 已存在，保留不覆盖（update 模式）"
elif [ -f "CLAUDE.md" ]; then
  echo -e "  ${YELLOW}○${NC} CLAUDE.md 已存在，备份为 CLAUDE.md.bak 并覆盖"
  cp CLAUDE.md CLAUDE.md.bak
  echo "$CLAUDE_MD" > CLAUDE.md
  echo -e "  ${GREEN}✓${NC} CLAUDE.md 已生成"
else
  echo "$CLAUDE_MD" > CLAUDE.md
  echo -e "  ${GREEN}✓${NC} CLAUDE.md 已生成"
fi

# 生成 ARCHITECTURE.md（仅不存在时）
if [ ! -f "ARCHITECTURE.md" ]; then
  ARCH_MD=$(cat "$TEMPLATE_DIR/ARCHITECTURE.template.md")
  ARCH_MD=$(echo "$ARCH_MD" | sed "s|__PROJECT_NAME__|$PROJECT_NAME|g")
  ARCH_MD=$(echo "$ARCH_MD" | sed "s|__LANGUAGE__|$LANGUAGE|g")
  ARCH_MD=$(echo "$ARCH_MD" | sed "s|__FRAMEWORK__|$FRAMEWORK|g")
  ARCH_MD=$(echo "$ARCH_MD" | sed "s|__DATABASE__|待填写|g")
  echo "$ARCH_MD" > ARCHITECTURE.md
  echo -e "  ${GREEN}✓${NC} ARCHITECTURE.md 已生成"
fi

# 生成 golden-principles.md（仅不存在时）
if [ ! -f "docs/golden-principles.md" ]; then
  cp "$TEMPLATE_DIR/docs/golden-principles.md" docs/
  echo -e "  ${GREEN}✓${NC} docs/golden-principles.md 已生成"
fi

# 生成 docs/.archive/README.md
if [ ! -f "docs/.archive/README.md" ]; then
  cat > docs/.archive/README.md << 'ARCHEOF'
# 归档文档

此目录存放有价值但不属于活跃上下文的文档。
- 仍在 git 版本控制中（grep 可搜索）
- 但不会被 Claude 主动加载到上下文
- 需要时可随时取出恢复到活跃目录
ARCHEOF
  echo -e "  ${GREEN}✓${NC} docs/.archive/README.md 已生成"
fi

# ============================================================
# 完成
# ============================================================
echo ""
echo -e "${BOLD}========================================${NC}"
echo -e "${GREEN}${BOLD}  部署完成！${NC}"
echo -e "${BOLD}========================================${NC}"
echo ""
echo -e "已部署的内容："
echo -e "  ${GREEN}✓${NC} 11 个 Hook + 1 个配置 (.claude/hooks/)"
echo -e "  ${GREEN}✓${NC} 3 个 Rules (.claude/rules/)"
echo -e "  ${GREEN}✓${NC} 5 个 Agents (.claude/agents/)"
echo -e "  ${GREEN}✓${NC} 8 个 Skills (~/.claude/skills/)"
echo -e "  ${GREEN}✓${NC} 进化系统 (.claude/evolution/)"
echo -e "  ${GREEN}✓${NC} CLAUDE.md + ARCHITECTURE.md + docs/"
if [ "$ENABLE_GIT_HOOKS" = "y" ] || [ "$ENABLE_GIT_HOOKS" = "Y" ]; then
  echo -e "  ${GREEN}✓${NC} 3 个 git hooks (.git/hooks/) — 提交门禁已激活"
fi
if [ "$ENABLE_CONFIG_FILES" = "y" ] || [ "$ENABLE_CONFIG_FILES" = "Y" ]; then
  echo -e "  ${GREEN}✓${NC} 项目配置文件 (.nvmrc / .editorconfig / .shellcheckrc / .gitattributes)"
fi
if [ "$ENABLE_ACTIONS" = "y" ] || [ "$ENABLE_ACTIONS" = "Y" ]; then
  echo -e "  ${GREEN}✓${NC} 6 个 GitHub Actions (.github/workflows/) — CI + 后台维护"
  echo -e "  ${GREEN}✓${NC} dependabot.yml (.github/) — 依赖自动升级"
fi
if [ "$ENABLE_COMMUNITY" = "y" ] || [ "$ENABLE_COMMUNITY" = "Y" ]; then
  echo -e "  ${GREEN}✓${NC} 社区文件 (CONTRIBUTING.md / SECURITY.md / PR template / Issue templates)"
fi
if [ "$ENABLE_TEST_SIGNAL" = "y" ] || [ "$ENABLE_TEST_SIGNAL" = "Y" ]; then
  echo -e "  ${GREEN}✓${NC} 测试奖励信号系统 (.test-system/)"
fi
if [ "$ENABLE_PERF_SIGNAL" = "y" ] || [ "$ENABLE_PERF_SIGNAL" = "Y" ]; then
  echo -e "  ${GREEN}✓${NC} 性能奖励信号系统 (.perf-system/)"
fi
if [ "$ENABLE_REWARD_LOOP" = "y" ] || [ "$ENABLE_REWARD_LOOP" = "Y" ]; then
  echo -e "  ${GREEN}✓${NC} 全自动进化循环 (.reward-loop/ — 8 个组件)"
fi
echo ""
echo -e "${BOLD}自动能力：${NC}"
echo -e "  ${GREEN}●${NC} 安全守卫 — Bash 门禁 + 路径守卫 + 密钥扫描 + 偷懒检测"
echo -e "  ${GREEN}●${NC} 上下文注入 — 每次会话自动加载项目状态 + 经验 + 会话摘要"
echo -e "  ${GREEN}●${NC} 进化采集 — 每次回复自动采集信号，积累 50 条后提醒审查"
echo -e "  ${GREEN}●${NC} 规则自动加载 — 编辑代码时自动注入编码/安全/Git 规范"
echo ""
echo -e "${BOLD}可用命令：${NC}"
echo -e "  ${BLUE}/pre-review${NC}         — 动手前方案评审"
echo -e "  ${BLUE}/post-review${NC}        — 交付后质量验收"
echo -e "  ${BLUE}/simplify${NC}           — 代码质量审查并修复"
echo -e "  ${BLUE}/review-pr${NC}          — PR 审查（通过后解锁 push）"
echo -e "  ${BLUE}/security-review${NC}    — 安全漏洞扫描"
echo -e "  ${BLUE}/verification-loop${NC}  — 全面验证循环"
echo -e "  ${BLUE}/evolution-review${NC}   — 进化审查（分析信号 + 规则归因 + 改进方案）"
echo ""
echo -e "${BOLD}专用 Agents：${NC}"
echo -e "  ${GREEN}●${NC} code-reviewer     — 代码审查（质量/安全/可维护性）"
echo -e "  ${GREEN}●${NC} planner           — 方案设计（不改代码，只出计划）"
echo -e "  ${GREEN}●${NC} research          — 调研（只读不写）"
echo -e "  ${GREEN}●${NC} security-reviewer — OWASP Top 10 安全审查"
echo -e "  ${GREEN}●${NC} test-writer       — 为现有代码编写测试"
echo ""
echo -e "${YELLOW}下一步：${NC}"
echo -e "  1. 打开 Claude Code，开始使用"
echo -e "  2. 根据实际使用调整 CLAUDE.md 和 ARCHITECTURE.md"
echo -e "  3. 积累使用数据后运行 /evolution-review 查看进化报告"
if [ "$ENABLE_TEST_SIGNAL" = "y" ] || [ "$ENABLE_TEST_SIGNAL" = "Y" ]; then
  echo -e "  4. 运行 cd .test-system && python init_baseline.py 初始化测试基准线"
fi
if [ "$ENABLE_PERF_SIGNAL" = "y" ] || [ "$ENABLE_PERF_SIGNAL" = "Y" ]; then
  echo -e "  5. 运行 cd .perf-system && python init_baseline.py 初始化性能基准线"
fi
if [ "$ENABLE_REWARD_LOOP" = "y" ] || [ "$ENABLE_REWARD_LOOP" = "Y" ]; then
  echo -e "  6. 编辑 .reward-loop/signals.yaml 配置信号、冻结边界、熔断参数"
  echo -e "  7. 运行 python .reward-loop/driver.py .reward-loop/signals.yaml --dry-run 验证配置"
fi
echo ""

# ============================================================
# 部署后验证 + 仪表盘生成
# ============================================================
log_deploy "部署完成" "success" "所有组件已部署"

echo -e "${BLUE}[验证]${NC} 运行环境完整性检查..."

# 复制核心工具到 .deploy/
mkdir -p .deploy
cp "$TEMPLATE_DIR/reward-loop/verify.py" .deploy/ 2>/dev/null
cp "$TEMPLATE_DIR/reward-loop/dashboard.py" .deploy/ 2>/dev/null
cp "$TEMPLATE_DIR/reward-loop/monitor.py" .deploy/ 2>/dev/null

if [ -n "$PY" ]; then
  $PY .deploy/verify.py "$PROJECT_DIR" --output .deploy/verify-result.json
  log_deploy "环境验证" "success" "已完成"

  # ── 兼容性自动修复（独立脚本，避免 bash 引号/编码问题） ──
  $PY "$SCRIPT_DIR/compat-fix.py" "$PROJECT_DIR" "$LANGUAGE"
  COMPAT_EXIT=$?

  if [ "$COMPAT_EXIT" -eq 1 ]; then
    echo ""
    echo -e "${YELLOW}[兼容性修复]${NC} 已自动修复兼容性问题，重新验证..."
    $PY .deploy/verify.py "$PROJECT_DIR" --output .deploy/verify-result.json
    log_deploy "兼容性修复" "success" "自动修复完成，已重新验证"
  else
    echo -e "  ${GREEN}✓${NC} 兼容性检查全部通过，部署的内容完全适配此项目"
    log_deploy "兼容性检查" "success" "全部通过"
  fi

  echo ""
  echo -e "${BLUE}[监控面板]${NC} 启动实时监控..."
  nohup $PY .deploy/monitor.py "$PROJECT_DIR" --port 8420 > .deploy/monitor.log 2>&1 &
  MONITOR_PID=$!
  disown $MONITOR_PID 2>/dev/null
  log_deploy "监控面板" "success" "http://localhost:8420"
  echo -e "  ${GREEN}✓${NC} 实时监控面板: http://localhost:8420"
  echo -e "  ${GREEN}✓${NC} 后台运行中 (PID: $MONITOR_PID)，关闭: kill $MONITOR_PID"
else
  echo -e "  ${YELLOW}⚠${NC}  未找到 python，跳过验证和仪表盘"
  log_deploy "环境验证" "skip" "未找到 python"
fi

echo ""
