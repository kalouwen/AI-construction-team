#!/bin/bash
# SessionStart Hook — 注入项目上下文
# 触发时机：新会话启动 + compact 后
# 输出内容会作为 additionalContext 注入 Claude 的上下文

if git rev-parse --is-inside-work-tree &>/dev/null; then
  BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
  RECENT=$(git log --oneline -5 2>/dev/null)
  MODIFIED=$(git diff --name-only 2>/dev/null | head -10)
  STAGED=$(git diff --cached --name-only 2>/dev/null | head -10)

  echo "=== 项目状态 ==="
  echo "当前分支: $BRANCH"

  if [ -n "$RECENT" ]; then
    echo ""
    echo "最近提交:"
    echo "$RECENT"
  fi

  if [ -n "$MODIFIED" ]; then
    echo ""
    echo "未暂存修改:"
    echo "$MODIFIED"
  fi

  if [ -n "$STAGED" ]; then
    echo ""
    echo "已暂存待提交:"
    echo "$STAGED"
  fi

  # 如果有活跃的执行计划，注入摘要
  ACTIVE_PLAN=$(ls docs/exec-plans/active/*.md 2>/dev/null | head -1)
  if [ -n "$ACTIVE_PLAN" ]; then
    echo ""
    echo "=== 活跃执行计划 ==="
    echo "文件: $ACTIVE_PLAN"
    head -20 "$ACTIVE_PLAN"
  fi

  # 注入上次会话摘要（session-save.sh 产出）
  LATEST_SESSION=".claude/sessions/latest.md"
  if [ -f "$LATEST_SESSION" ]; then
    echo ""
    echo "=== 上次会话摘要 ==="
    head -20 "$LATEST_SESSION"
  fi

  # 注入 instinct 经验（最近提取的信号句，让经验回流到行为中）
  INSTINCTS_FILE="$HOME/.claude/instincts/learned.md"
  if [ -f "$INSTINCTS_FILE" ]; then
    INSTINCT_LINES=$(tail -15 "$INSTINCTS_FILE" 2>/dev/null)
    if [ -n "$INSTINCT_LINES" ]; then
      echo ""
      echo "=== 近期经验（自动提取，供参考） ==="
      echo "$INSTINCT_LINES"
    fi
  fi

  # 注入 feedback memory 关键规则（减少 repeated_mistake）
  MEMORY_DIR="$HOME/.claude/projects"
  if [ -d "$MEMORY_DIR" ]; then
    # 找到当前项目的 memory 目录
    PROJ_MEMORY=""
    for d in "$MEMORY_DIR"/*/memory; do
      if [ -d "$d" ]; then
        PROJ_MEMORY="$d"
        break
      fi
    done
    if [ -n "$PROJ_MEMORY" ] && [ -d "$PROJ_MEMORY" ]; then
      FEEDBACK_FILES=$(find "$PROJ_MEMORY" -name 'feedback_*.md' -type f 2>/dev/null | head -5)
      if [ -n "$FEEDBACK_FILES" ]; then
        echo ""
        echo "=== 关键行为规则（feedback memory）==="
        while IFS= read -r ffile; do
          # 提取 description 行作为摘要
          DESC=$(grep -m1 '^description:' "$ffile" 2>/dev/null | sed 's/^description: *//')
          if [ -n "$DESC" ]; then
            echo "  - $DESC"
          fi
        done <<< "$FEEDBACK_FILES"
      fi
    fi
  fi

  # 进化信号积累提醒
  SCORES_FILE=".claude/evolution/scores.jsonl"
  if [ -f "$SCORES_FILE" ]; then
    SCORE_COUNT=$(wc -l < "$SCORES_FILE" 2>/dev/null || echo 0)
    # 检查上次分析时间标记
    LAST_REVIEW=".claude/evolution/last-review-at"
    REVIEWED_AT=0
    if [ -f "$LAST_REVIEW" ]; then
      REVIEWED_AT=$(cat "$LAST_REVIEW" 2>/dev/null || echo 0)
    fi
    UNREVIEWED=$((SCORE_COUNT - REVIEWED_AT))
    if [ "$UNREVIEWED" -ge 50 ]; then
      echo ""
      echo "=== 进化提醒 ==="
      echo "已积累 $UNREVIEWED 条未分析的进化信号（共 $SCORE_COUNT 条）。"
      echo "建议运行 /evolution-review 生成进化报告。"
    fi
  fi

  # ── 健康检查 + 仪表盘刷新（每次会话开始自动运行）──
  HEALTH_CHECK=".reward-loop/health-check.py"
  DASHBOARD=".reward-loop/dashboard.py"
  SIGNALS_DIR=".signals"

  if [ -f "$HEALTH_CHECK" ] && [ -d "$SIGNALS_DIR" ]; then
    # 静默运行健康检查（不阻塞会话启动）
    python3 "$HEALTH_CHECK" "$SIGNALS_DIR" --output "$SIGNALS_DIR/health-report.md" 2>/dev/null
    HC_EXIT=$?

    # 刷新仪表盘
    if [ -f "$DASHBOARD" ]; then
      python3 "$DASHBOARD" "$SIGNALS_DIR" 2>/dev/null
    fi

    # 注入健康摘要到上下文
    echo ""
    echo "=== 项目健康状态 ==="
    if [ $HC_EXIT -eq 0 ]; then
      echo "状态: 健康"
    elif [ $HC_EXIT -eq 1 ]; then
      echo "状态: 有退化（查看 $SIGNALS_DIR/health-report.md）"
    elif [ $HC_EXIT -eq 2 ]; then
      echo "状态: 环境异常（查看 $SIGNALS_DIR/health-report.md）"
    fi
    echo "仪表盘: $SIGNALS_DIR/dashboard.html"
  fi
fi

# === 环境健康快检（verify.py 轻量版）===
# 只输出 FAIL 和 WARN 项，让新会话立刻知道哪里有问题
VERIFY_SCRIPT="$PROJECT_DIR/.reward-loop/verify.py"
[ ! -f "$VERIFY_SCRIPT" ] && VERIFY_SCRIPT="$PROJECT_DIR/templates/reward-loop/verify.py"
if [ -f "$VERIFY_SCRIPT" ]; then
  VERIFY_OUTPUT=$(python "$VERIFY_SCRIPT" "$PROJECT_DIR" --output /dev/null 2>/dev/null)
  ISSUES=$(echo "$VERIFY_OUTPUT" | grep -E '^\s*\[!!\]|^\s*\[WARN\]' | head -5)
  if [ -n "$ISSUES" ]; then
    echo ""
    echo "=== 环境问题（verify.py）==="
    echo "$ISSUES"
  fi
fi
