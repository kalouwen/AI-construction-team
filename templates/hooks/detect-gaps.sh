#!/usr/bin/env bash
# SessionStart Hook — 知识缺口检测
# 触发时机：新会话启动 + compact 后
# 职责：检测"代码密度 vs 文档密度"比例，自动暴露知识缺口
# 输出内容会作为 additionalContext 注入 Claude 的上下文
#
# 兼容：macOS / Linux / Windows Git Bash

set -euo pipefail

PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
KNOWLEDGE_DIR="$PROJECT_ROOT/.claude/knowledge"

# 源代码扩展名（覆盖主流语言）
SRC_EXTENSIONS="cs|ts|tsx|js|jsx|py|go|rs|java|kt|cpp|c|h|swift|rb|lua|sh"

# 收集警告
WARNINGS=()

# --- 1. 新项目检测 ---
if [ ! -d "$KNOWLEDGE_DIR" ]; then
  # 检查是否连构建配置都没有
  HAS_BUILD_CONFIG=false
  for f in package.json Cargo.toml go.mod pyproject.toml setup.py Makefile CMakeLists.txt *.sln *.csproj; do
    if compgen -G "$PROJECT_ROOT/$f" >/dev/null 2>&1; then
      HAS_BUILD_CONFIG=true
      break
    fi
  done
  if [ "$HAS_BUILD_CONFIG" = false ]; then
    WARNINGS+=("  [!] 新项目：无 .claude/knowledge/ 且无构建配置 — 建议运行 /survey 初始化")
  else
    WARNINGS+=("  [!] 无 .claude/knowledge/ 目录 — 建议运行 /survey 生成项目画像")
  fi
fi

# --- 2. 代码无文档：源代码多但知识卡片少 ---
if [ -d "$PROJECT_ROOT" ]; then
  SRC_COUNT=$(find "$PROJECT_ROOT" -maxdepth 5 \
    -not -path '*/.git/*' \
    -not -path '*/node_modules/*' \
    -not -path '*/vendor/*' \
    -not -path '*/__pycache__/*' \
    -not -path '*/bin/*' \
    -not -path '*/obj/*' \
    -not -path '*/Library/*' \
    -not -path '*/Temp/*' \
    -type f | grep -cE "\\.(${SRC_EXTENSIONS})$" 2>/dev/null || echo 0)

  MODULES_DIR="$KNOWLEDGE_DIR/modules"
  if [ -d "$MODULES_DIR" ]; then
    CARD_COUNT=$(find "$MODULES_DIR" -maxdepth 1 -name '*.md' -type f 2>/dev/null | wc -l | tr -d ' ')
  else
    CARD_COUNT=0
  fi

  if [ "$SRC_COUNT" -gt 30 ] && [ "$CARD_COUNT" -lt 3 ]; then
    WARNINGS+=("  [!] 发现 ${SRC_COUNT} 个代码文件但只有 ${CARD_COUNT} 个知识卡片 — 建议运行 /survey 补全")
  fi
fi

# --- 3. 核心模块无知识卡片 ---
if [ -d "$PROJECT_ROOT" ] && [ -d "$KNOWLEDGE_DIR" ]; then
  # 找代码量最大的 top 5 目录（第一层子目录）
  TOP_DIRS=$(find "$PROJECT_ROOT" -maxdepth 2 -mindepth 1 -type d \
    -not -path '*/.git/*' \
    -not -path '*/.git' \
    -not -path '*/.claude/*' \
    -not -path '*/node_modules/*' \
    -not -path '*/vendor/*' \
    -not -path '*/__pycache__/*' \
    -not -path '*/bin/*' \
    -not -path '*/obj/*' \
    -not -path '*/Library/*' \
    -not -path '*/Temp/*' \
    2>/dev/null | while read -r dir; do
      COUNT=$(find "$dir" -type f 2>/dev/null | grep -cE "\\.(${SRC_EXTENSIONS})$" 2>/dev/null || echo 0)
      if [ "$COUNT" -gt 0 ]; then
        echo "$COUNT $dir"
      fi
    done | sort -rn | head -5)

  if [ -n "$TOP_DIRS" ]; then
    while IFS= read -r line; do
      DIR_PATH=$(echo "$line" | cut -d' ' -f2-)
      DIR_NAME=$(basename "$DIR_PATH")
      if [ ! -f "$KNOWLEDGE_DIR/modules/${DIR_NAME}.md" ]; then
        WARNINGS+=("  [!] 核心模块 ${DIR_NAME}/ 无对应知识卡片")
      fi
    done <<< "$TOP_DIRS"
  fi
fi

# --- 4. 痛点未处理 ---
PAIN_POINTS_FILE="$KNOWLEDGE_DIR/pain-points.md"
if [ -f "$PAIN_POINTS_FILE" ]; then
  P0_COUNT=$(grep -c '\[P0\]' "$PAIN_POINTS_FILE" 2>/dev/null || echo 0)
  if [ "$P0_COUNT" -gt 0 ]; then
    WARNINGS+=("  [!] 有 ${P0_COUNT} 个 P0 级痛点未处理 — 查看 .claude/knowledge/pain-points.md")
  fi
fi

# --- 5. 画像过期 ---
PROFILE_FILE="$KNOWLEDGE_DIR/profile.json"
if [ -f "$PROFILE_FILE" ]; then
  # 提取 surveyed_at（jq 优先，grep 降级）
  if command -v jq &>/dev/null; then
    SURVEYED_AT=$(jq -r '.surveyed_at // empty' "$PROFILE_FILE" 2>/dev/null || true)
  else
    SURVEYED_AT=$(grep -oE '"surveyed_at"\s*:\s*"[^"]*"' "$PROFILE_FILE" | grep -oE '"[^"]*"$' | tr -d '"' || true)
  fi

  if [ -n "$SURVEYED_AT" ]; then
    # 计算天数差（兼容 macOS date -j 和 GNU date -d）
    SURVEY_EPOCH=""
    if date -d "$SURVEYED_AT" +%s &>/dev/null 2>&1; then
      SURVEY_EPOCH=$(date -d "$SURVEYED_AT" +%s)
    elif date -jf "%Y-%m-%d" "$SURVEYED_AT" +%s &>/dev/null 2>&1; then
      SURVEY_EPOCH=$(date -jf "%Y-%m-%d" "$SURVEYED_AT" +%s)
    elif date -jf "%Y-%m-%dT%H:%M:%S" "$SURVEYED_AT" +%s &>/dev/null 2>&1; then
      SURVEY_EPOCH=$(date -jf "%Y-%m-%dT%H:%M:%S" "$SURVEYED_AT" +%s)
    fi

    if [ -n "$SURVEY_EPOCH" ]; then
      NOW_EPOCH=$(date +%s)
      DAYS_AGO=$(( (NOW_EPOCH - SURVEY_EPOCH) / 86400 ))
      if [ "$DAYS_AGO" -gt 30 ]; then
        WARNINGS+=("  [!] 项目画像已过期 (${DAYS_AGO} 天前) — 建议重新运行 /survey")
      fi
    fi
  fi
fi

# --- 输出 ---
if [ ${#WARNINGS[@]} -gt 0 ]; then
  echo ""
  echo "=== 知识缺口检测 ==="
  for w in "${WARNINGS[@]}"; do
    echo "$w"
  done
fi
