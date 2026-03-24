#!/bin/bash
# 项目类型自动检测脚本
# 输出 JSON 格式的检测结果，供 deploy.sh 使用

PROJECT_DIR="${1:-.}"
cd "$PROJECT_DIR" || exit 1

# 默认值
LANGUAGE="unknown"
FRAMEWORK="unknown"
BUILD_CMD="# 请填写构建命令"
TEST_CMD="# 请填写测试命令"
TEST_UNIT_CMD=""       # 单元测试（秒级，每次 commit 跑）
TEST_E2E_CMD=""        # 端到端测试（分钟级，push / reward loop 跑）
TEST_LIVE_CMD=""       # 真实环境测试（可选，发版前跑）
LINT_CMD="# 请填写 lint 命令"
HAS_GIT="false"
MAIN_BRANCH="main"

# Git 检测
if git rev-parse --is-inside-work-tree &>/dev/null; then
  HAS_GIT="true"
  # 检测主分支名称
  if git show-ref --verify --quiet refs/heads/main 2>/dev/null; then
    MAIN_BRANCH="main"
  elif git show-ref --verify --quiet refs/heads/master 2>/dev/null; then
    MAIN_BRANCH="master"
  fi
fi

# ============================================================
# Node.js / TypeScript 项目
# ============================================================
if [ -f "package.json" ]; then
  LANGUAGE="node"

  # 检测框架
  if grep -q '"next"' package.json 2>/dev/null; then
    FRAMEWORK="Next.js"
  elif grep -q '"nuxt"' package.json 2>/dev/null; then
    FRAMEWORK="Nuxt.js"
  elif grep -q '"react"' package.json 2>/dev/null; then
    FRAMEWORK="React"
  elif grep -q '"vue"' package.json 2>/dev/null; then
    FRAMEWORK="Vue"
  elif grep -q '"svelte"' package.json 2>/dev/null; then
    FRAMEWORK="Svelte"
  elif grep -q '"express"' package.json 2>/dev/null; then
    FRAMEWORK="Express"
  elif grep -q '"fastify"' package.json 2>/dev/null; then
    FRAMEWORK="Fastify"
  fi

  # 检测包管理器
  if [ -f "pnpm-lock.yaml" ]; then
    PKG_MGR="pnpm"
  elif [ -f "yarn.lock" ]; then
    PKG_MGR="yarn"
  elif [ -f "bun.lockb" ] || [ -f "bun.lock" ]; then
    PKG_MGR="bun"
  else
    PKG_MGR="npm"
  fi

  # 检测命令
  if grep -q '"build"' package.json 2>/dev/null; then
    BUILD_CMD="$PKG_MGR run build"
  fi
  if grep -q '"test"' package.json 2>/dev/null; then
    TEST_CMD="$PKG_MGR test"
  fi
  # 测试分级探测
  if grep -q '"test:unit"' package.json 2>/dev/null; then
    TEST_UNIT_CMD="$PKG_MGR run test:unit"
  fi
  if grep -q '"test:e2e"' package.json 2>/dev/null; then
    TEST_E2E_CMD="$PKG_MGR run test:e2e"
  fi
  if grep -q '"test:live"' package.json 2>/dev/null; then
    TEST_LIVE_CMD="$PKG_MGR run test:live"
  fi
  if grep -q '"lint"' package.json 2>/dev/null; then
    LINT_CMD="$PKG_MGR run lint"
  fi

# ============================================================
# Python 项目
# ============================================================
elif [ -f "pyproject.toml" ] || [ -f "setup.py" ] || [ -f "requirements.txt" ]; then
  LANGUAGE="python"

  if [ -f "manage.py" ]; then
    FRAMEWORK="Django"
    BUILD_CMD="python manage.py check"
    TEST_CMD="python manage.py test"
  elif grep -q "fastapi" requirements.txt 2>/dev/null || grep -q "fastapi" pyproject.toml 2>/dev/null; then
    FRAMEWORK="FastAPI"
    TEST_CMD="pytest"
  elif grep -q "flask" requirements.txt 2>/dev/null || grep -q "flask" pyproject.toml 2>/dev/null; then
    FRAMEWORK="Flask"
    TEST_CMD="pytest"
  else
    TEST_CMD="pytest"
  fi
  LINT_CMD="ruff check ."
  # Python 测试分级
  TEST_UNIT_CMD="pytest -m 'not e2e and not live' --timeout=30"
  TEST_E2E_CMD="pytest -m 'e2e' --timeout=300"
  TEST_LIVE_CMD="pytest -m 'live' --timeout=600"

# ============================================================
# Go 项目
# ============================================================
elif [ -f "go.mod" ]; then
  LANGUAGE="go"
  FRAMEWORK="Go"
  BUILD_CMD="go build ./..."
  TEST_CMD="go test ./..."
  LINT_CMD="golangci-lint run"

# ============================================================
# Rust 项目
# ============================================================
elif [ -f "Cargo.toml" ]; then
  LANGUAGE="rust"
  FRAMEWORK="Rust"
  BUILD_CMD="cargo build"
  TEST_CMD="cargo test"
  LINT_CMD="cargo clippy"

# ============================================================
# Unity 项目
# ============================================================
elif [ -d "Assets" ] && [ -d "ProjectSettings" ]; then
  LANGUAGE="csharp"
  FRAMEWORK="unity"

  # 自动探测 Unity 安装路径（Windows + macOS）
  UNITY_EXE=""
  if [ -d "/c/Program Files/Unity/Hub/Editor" ]; then
    UNITY_EXE=$(find "/c/Program Files/Unity/Hub/Editor" -maxdepth 2 -name "Unity.exe" 2>/dev/null | sort -r | head -1)
  elif [ -d "$HOME/AppData/Local/Programs/Unity/Hub/Editor" ]; then
    UNITY_EXE=$(find "$HOME/AppData/Local/Programs/Unity/Hub/Editor" -maxdepth 2 -name "Unity.exe" 2>/dev/null | sort -r | head -1)
  elif [ -d "/Applications/Unity/Hub/Editor" ]; then
    UNITY_EXE=$(find "/Applications/Unity/Hub/Editor" -maxdepth 3 -name "Unity" -type f 2>/dev/null | sort -r | head -1)
  fi

  if [ -n "$UNITY_EXE" ]; then
    # EditMode = 秒级单元测试，PlayMode = 分钟级端到端测试
    TEST_CMD="\"$UNITY_EXE\" -batchmode -nographics -runTests -projectPath . -testResults TestResults.xml -testPlatform EditMode"
    TEST_UNIT_CMD="\"$UNITY_EXE\" -batchmode -nographics -runTests -projectPath . -testResults TestResults-Unit.xml -testPlatform EditMode"
    TEST_E2E_CMD="\"$UNITY_EXE\" -batchmode -nographics -runTests -projectPath . -testResults TestResults-E2E.xml -testPlatform PlayMode"
    BUILD_CMD="\"$UNITY_EXE\" -batchmode -nographics -quit -projectPath . -buildTarget StandaloneWindows64"
  else
    TEST_CMD="# Unity not found — configure manually"
    BUILD_CMD="# Unity not found — configure manually"
  fi
  LINT_CMD="# dotnet format"

# ============================================================
# .NET / C# 项目
# ============================================================
elif [ -n "$(ls *.sln 2>/dev/null)" ] || [ -n "$(ls *.csproj 2>/dev/null)" ]; then
  LANGUAGE="csharp"
  FRAMEWORK=".NET"
  BUILD_CMD="dotnet build"
  TEST_CMD="dotnet test"
  LINT_CMD="dotnet format --verify-no-changes"
fi

# 输出 JSON
cat << EOF
{
  "language": "$LANGUAGE",
  "framework": "$FRAMEWORK",
  "build_cmd": "$BUILD_CMD",
  "test_cmd": "$TEST_CMD",
  "test_unit_cmd": "$TEST_UNIT_CMD",
  "test_e2e_cmd": "$TEST_E2E_CMD",
  "test_live_cmd": "$TEST_LIVE_CMD",
  "lint_cmd": "$LINT_CMD",
  "has_git": $HAS_GIT,
  "main_branch": "$MAIN_BRANCH",
  "project_dir": "$(pwd)"
}
EOF
