#!/bin/bash
# Stop Hook — Instincts 自动提取
# 触发时机：Claude 每次回复结束后
# 职责：从 AI 回复中提取值得记住的模式，追加到 instincts 文件
#
# V1 简化版：正则提取信号句 → 追加到 learned.md → 超长自动归档
# 迭代方向：
#   V2: 加 confidence 评分（出现频次 × 上下文权重）
#   V3: 定期聚合进化（相似 instincts 合并，高频提升为 skill）
#   V4: 按项目/领域分类存储

INPUT=$(cat)

# 加载共享解析库
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/parse-config.sh" 2>/dev/null || true

# Profile 检查
if ! should_run "instinct-extract"; then
  exit 0
fi

# 获取 AI 回复内容
RESPONSE=$(echo "$INPUT" | jq -r '.assistant_response // empty')

if [ -z "$RESPONSE" ]; then
  exit 0
fi

INSTINCTS_DIR="$HOME/.claude/instincts"
LEARNED_FILE="$INSTINCTS_DIR/learned.md"
ARCHIVE_DIR="$INSTINCTS_DIR/archive"

mkdir -p "$INSTINCTS_DIR" "$ARCHIVE_DIR"

# 提取信号句：捕获发现/纠正/结论时刻，排除普通叙述
# V1.2: 放宽正则——V1.1 过严（46条信号仅1条经验），改为三类模式：
#   类别1: 经验总结（教训/踩坑/关键发现/根因/务必/切记/千万不要）
#   类别2: 发现问题（发现问题/抓到bug/真实的bug/真正的问题）
#   类别3: 自我纠正（我错了/判断错误/我搞混了）— 高价值学习信号
#   类别4: 英文（always/never/must not/lesson learned/the real issue）
# 排除：表格行、标题行、代码块、普通解释句
SIGNALS=$(echo "$RESPONSE" | grep -iE '(教训[：:]|踩坑[：:]|关键发现[：:]|根因[：:]|务必|切记|千万不要|千万别|以后.*一定要|下次.*记得|发现.*问题|发现.*bug|抓到.*bug|抓到.*问题|真实的bug|真正的问题|真正.*原因|我错了|我搞混了|我犯了.*错|判断错误|always [a-z]|never [a-z]|must not [a-z]|lesson learned|the real issue|the real problem|actually.*should)' 2>/dev/null | grep -vE '(^[[:space:]]*$|^\||\*\*[^*]+\*\*:|^#|^--|^```|^\s*[-*] \*\*)' | head -5)

if [ -z "$SIGNALS" ]; then
  exit 0
fi

# 获取项目名和时间戳
PROJECT=$(basename "$(pwd)" 2>/dev/null || echo "unknown")
TIMESTAMP=$(date '+%Y-%m-%d %H:%M')

# 追加到 learned.md
{
  echo ""
  echo "<!-- $TIMESTAMP | $PROJECT -->"
  echo "$SIGNALS" | while IFS= read -r line; do
    # 清理行首空格，加 bullet
    cleaned=$(echo "$line" | sed 's/^[[:space:]]*//')
    echo "- $cleaned"
  done
} >> "$LEARNED_FILE"

# 自动归档：超过 100 行时，把前 70 行移到归档
LINE_COUNT=$(wc -l < "$LEARNED_FILE" 2>/dev/null || echo 0)
if [ "$LINE_COUNT" -gt 100 ]; then
  ARCHIVE_FILE="$ARCHIVE_DIR/$(date '+%Y%m%d-%H%M%S').md"
  head -70 "$LEARNED_FILE" > "$ARCHIVE_FILE"
  tail -n +71 "$LEARNED_FILE" > "$LEARNED_FILE.tmp"
  mv "$LEARNED_FILE.tmp" "$LEARNED_FILE"
fi

exit 0
