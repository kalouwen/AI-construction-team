# Claude Code 自动化体系搭建路线图

> 核心原则：Agent 出错 → 不是让它更努力 → 是修 Harness，让它永远不再犯这个错。
> 诚实标注：明确区分哪些是 Hook 机械执行的，哪些是 CLAUDE.md 指导 AI 自行判断的。
> 可靠性数学：95% 单步准确率 × 20 步 = 36% 系统可靠率。长链必须在每步自校验。

**参考来源：**
- [Claude Code 官方 Hooks 文档](https://code.claude.com/docs/en/hooks-guide)
- [Claude Code 官方 Skills 文档](https://code.claude.com/docs/en/skills)
- [Claude Code 官方 Best Practices](https://code.claude.com/docs/en/best-practices)
- [claude-code-harness](https://github.com/Chachamaru127/claude-code-harness) — 带 TypeScript 护栏引擎的成熟 Harness
- [everything-claude-code](https://github.com/affaan-m/everything-claude-code) — Anthropic Hackathon 获奖项目
- [awesome-claude-skills](https://github.com/VoltAgent/awesome-agent-skills) — 1234+ 社区 Skills
- [Harness Engineering 101](https://muraco.ai/en/articles/harness-engineering-claude-code-codex/)

---

## 架构总览

```
┌─────────────────────────────────────────────────────┐
│                   用户说意图（中文）                    │
└───────────────────────┬─────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────┐
│  SessionStart Hook → 注入分支/上下文（机械执行）         │
└───────────────────────┬─────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────┐
│  CLAUDE.md 指令 → AI 理解意图，选择 Skill（AI 判断）    │
└───────────────────────┬─────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────┐
│  PreToolUse Hook → 安全门禁（机械执行，仅关键操作）      │
│  - git add → .env 泄露检测                            │
│  - git push → 门禁检查                                │
│  - git commit → build check                          │
└───────────────────────┬─────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────┐
│  Stop Hook → 批量格式化（机械执行，每次回复仅 1 次）     │
│  - 格式化本轮所有修改过的文件                           │
│  - ⚠️ 不在 PostToolUse 上格式化（会产生 system          │
│    reminder 噪声，吃掉上下文 token）                    │
└───────────────────────┬─────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────┐
│  CLAUDE.md 规则 → 代码审查/质量检查（AI 判断）          │
│  - commit 后建议 /simplify                            │
│  - 大改动建议 /review-pr                              │
└─────────────────────────────────────────────────────┘
```

### 诚实标注表

| 规则 | 执行方式 | 触发时机 | 成本 |
|------|---------|---------|------|
| .env 泄露拦截 | ✅ Hook（机械执行） | PreToolUse → Bash 含 git add | 低（command hook） |
| git push 门禁 | ✅ Hook（机械执行） | PreToolUse → Bash 含 git push | 低 |
| commit 前 build check | ✅ Hook（机械执行） | PreToolUse → Bash 含 git commit | 中（需跑 build） |
| 完成回复后批量格式化 | ✅ Hook（机械执行） | Stop → 格式化已修改文件 | 低（每次回复仅 1 次） |
| SessionStart 注入上下文 | ✅ Hook（机械执行） | SessionStart | 低 |
| PreCompact 保留关键上下文 | ✅ Hook（机械执行） | PreCompact | 低 |
| commit 后建议审查 | 📝 CLAUDE.md（AI 判断） | AI 自行决定 | 零 |
| 代码规范遵循 | 📝 CLAUDE.md（AI 判断） | AI 自行决定 | 零 |
| 安全审查 | 📝 Skill（按需加载） | 手动 /security-review | 按需 |
| TDD 工作流 | 📝 Skill（按需加载） | 手动 /tdd | 按需 |
| 搜索先于编码 | 📝 CLAUDE.md（AI 判断） | AI 自行决定 | 零 |
| 动手前方案评审 | 📝 Skill + CLAUDE.md | 大任务自动建议 /pre-review | 按需 |
| 交付后质量验收 | 📝 Skill + CLAUDE.md | 完成时自动建议 /post-review | 按需 |
| 文档归档清理 | 📝 CLAUDE.md（AI 判断） | 定期建议归档不活跃文档 | 零 |

---

## Phase 1：地基（知识架构）

### 1.1 项目 CLAUDE.md（< 100 行，指针式）

位置：`项目根目录/CLAUDE.md` 或 `.claude/CLAUDE.md`

```markdown
# 项目名称

## Build & Test
npm run build          # 构建
npm test               # 测试
npm run lint           # lint 检查

## Architecture
见 ARCHITECTURE.md

## Git Workflow
- 分支命名：feature/[desc], fix/[desc], refactor/[desc]
- commit message：conventional commits 格式
- 每个 PR 必须包含测试

## Engineering Rules（机械执行 / AI 判断）

### 机械执行（由 Hook 强制）
- git add 前自动检测 .env 泄露
- git commit 前自动 build check
- git push 前必须通过审查标记
- 编辑文件后自动格式化

### AI 判断（由你自行遵循）
- commit 后根据改动大小建议 /simplify 或 /review-pr
- 先搜索再编码：修改前用 Grep/Glob 定位，不盲改
- 不过度工程：只做被要求的事
- 安全敏感操作前主动提醒
- 大任务动手前先跑 /pre-review（灵魂 7 问），等用户确认再动手
- 说"做完了"前先跑 /post-review（验收 6 问），全部通过才交付

### 上下文卫生
- docs/.archive/ 存放有价值但不活跃的文档，不要加载到上下文
- 活跃文档保持精简，超过 30 天未引用的考虑归档
- 引用文档时用路径指针，不要整段复制进 CLAUDE.md

## Boundaries
- 不直接修改 .env、package-lock.json、.git/
- 不在 production 代码中使用 console.log
- 不引入未审查的第三方依赖
```

### 1.2 ARCHITECTURE.md

```markdown
# Architecture

## 模块依赖方向（单向）
Types → Config → Repo → Service → Runtime → UI

## 目录结构
src/
├── types/       # 类型定义
├── config/      # 配置
├── repo/        # 数据访问层
├── service/     # 业务逻辑
├── runtime/     # 运行时（中间件、路由）
└── ui/          # 前端组件

## 关键决策
见 docs/design-docs/
```

### 1.3 docs 目录结构（活跃/归档分离）

**核心原则：活跃上下文必须精简。** 有价值但不常用的文档移到 `.archive/`，
仍在 git 里（grep 能搜到），但不会被 Claude 主动加载到上下文中。

```
docs/
├── design-docs/           # 架构决策记录（活跃）
├── golden-principles.md   # 3-5 条黄金原则（活跃）
├── exec-plans/
│   ├── active/            # 当前执行计划（活跃）
│   └── completed/         # 已完成计划（活跃，Agent 可查历史决策）
├── tech-debt-tracker.md   # 技术债清单（活跃）
│
├── .archive/              # 归档区：有价值但不属于活跃上下文
│   ├── references/        # 之前的研究/分析产出
│   ├── old-design-docs/   # 过期的设计文档
│   └── README.md          # 索引：说明归档了什么，方便搜索
│
└── README.md              # docs 目录索引（含归档区指针）
```

**归档规则：**
- 没有任何 hook、skill 或 CLAUDE.md 引用的参考文档 → 归档
- 原位置留 README.md 指向归档路径，保持可发现性
- 定期审计：`docs/` 下超过 30 天未被引用的文件考虑归档
- 归档不是删除——grep 仍然能找到，只是不污染活跃上下文

---

## Phase 2：基础 Hooks（仅机械执行的部分）

### 总体原则
- **只为必须机械执行的规则建 Hook**
- **PreToolUse Hook 必须轻量**（< 5 秒，否则每次工具调用都卡）
- **能用 PostToolUse 的不用 PreToolUse**（后者不阻塞）
- **能用 async 的就用 async**（不阻塞主流程）

### 2.1 settings.json 完整配置

位置：`~/.claude/settings.json`（全局）或 `.claude/settings.json`（项目级）

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|compact",
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/hooks/session-start.sh",
            "timeout": 10,
            "statusMessage": "正在加载项目上下文..."
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/hooks/pre-bash-guard.sh",
            "timeout": 30,
            "statusMessage": "安全检查中..."
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/hooks/stop-format.sh",
            "timeout": 30
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/hooks/pre-compact-inject.sh",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

### 2.2 Hook 脚本详解

#### `~/.claude/hooks/session-start.sh`
SessionStart 不能阻塞，只能注入上下文。

```bash
#!/bin/bash
# 输出会作为 additionalContext 注入 Claude 的上下文
if git rev-parse --is-inside-work-tree &>/dev/null; then
  BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
  RECENT=$(git log --oneline -5 2>/dev/null)
  MODIFIED=$(git diff --name-only 2>/dev/null | head -10)

  cat << EOF
当前分支: $BRANCH
最近提交:
$RECENT
未提交修改:
$MODIFIED
EOF
fi
```

#### `~/.claude/hooks/pre-bash-guard.sh`
统一的 Bash 命令守卫，处理三种场景：

```bash
#!/bin/bash
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# === 场景 1: git add 泄露检测 ===
if echo "$COMMAND" | grep -qE 'git\s+add'; then
  # 检查是否包含敏感文件
  SENSITIVE_PATTERNS=('.env' 'credentials' 'secret' '.pem' '.key' 'token')
  for pattern in "${SENSITIVE_PATTERNS[@]}"; do
    if echo "$COMMAND" | grep -qi "$pattern"; then
      echo "BLOCKED: 检测到可能的敏感文件 ($pattern)，请确认后手动添加" >&2
      exit 2
    fi
  done
fi

# === 场景 2: git commit 前 build check ===
if echo "$COMMAND" | grep -qE 'git\s+commit'; then
  # 检查是否有 build 脚本
  if [ -f "package.json" ]; then
    # 尝试 typecheck（如果有的话）
    if npm run --silent typecheck 2>/dev/null; then
      : # 通过
    elif npx tsc --noEmit 2>/dev/null; then
      : # 通过
    fi
    # 注意：如果没有 typecheck 脚本，不阻塞
  fi
fi

# === 场景 3: git push 门禁 ===
if echo "$COMMAND" | grep -qE 'git\s+push'; then
  MARKER=".claude/push-approved"
  if [ ! -f "$MARKER" ]; then
    echo "BLOCKED: push 前需要先通过审查。请运行 /review-pr 获取审查通过标记。" >&2
    exit 2
  fi
  # 通过后清除标记（一次性）
  rm -f "$MARKER"
fi

# 默认放行
exit 0
```

#### `~/.claude/hooks/stop-format.sh`
Claude 完成回复后，批量格式化本轮修改的文件。

**为什么不在 PostToolUse（每次编辑后）格式化？**
> 社区实测发现：PostToolUse 上的 formatter 每次改文件都会产生 system reminder，
> 这些 "文件已修改" 的提醒会大量吃掉上下文 token。在 Stop 时格式化，
> 每轮回复只跑一次，上下文干净。

```bash
#!/bin/bash
# 格式化本轮 git 中已修改（未暂存）的文件
MODIFIED=$(git diff --name-only 2>/dev/null)

if [ -z "$MODIFIED" ]; then
  exit 0
fi

for FILE in $MODIFIED; do
  if [ ! -f "$FILE" ]; then
    continue
  fi
  case "$FILE" in
    *.ts|*.tsx|*.js|*.jsx|*.json|*.css|*.scss)
      npx prettier --write "$FILE" 2>/dev/null
      ;;
    *.py)
      python -m black "$FILE" 2>/dev/null
      ;;
  esac
done

exit 0
```

#### `~/.claude/hooks/pre-compact-inject.sh`
compact 前保留关键上下文：

```bash
#!/bin/bash
# 输出的内容会在 compact 后重新注入
if git rev-parse --is-inside-work-tree &>/dev/null; then
  BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
  echo "重要上下文（compact 后保留）:"
  echo "- 当前分支: $BRANCH"

  # 如果有活跃的执行计划，注入摘要
  ACTIVE_PLAN=$(ls docs/exec-plans/active/*.md 2>/dev/null | head -1)
  if [ -n "$ACTIVE_PLAN" ]; then
    echo "- 活跃计划: $ACTIVE_PLAN"
    head -20 "$ACTIVE_PLAN"
  fi
fi
```

---

## Phase 3：Skills 体系

### 总体原则
- Skill 描述占 ~2% 上下文预算，**不能无限堆**
- 区分 **用户手动调用** vs **Claude 自动调用** vs **背景知识**
- 用 `context: fork` 隔离重操作，避免污染主对话

### 优先级排序

| 优先级 | Skill | 调用方式 | 说明 |
|--------|-------|---------|------|
| P0 | coding-standards | 背景知识（自动） | AI 自动参考 |
| P0 | simplify | 手动 /simplify | 代码质量审查 |
| P1 | security-review | 手动 /security-review | 安全检查 |
| P1 | review-pr | 手动 /review-pr | PR 审查 + push 标记 |
| P2 | verification-loop | 手动 /verify | 验证循环 |
| P2 | tdd-workflow | 手动 /tdd | TDD 工作流 |

### 3.1 coding-standards（背景知识，自动加载）

位置：`~/.claude/skills/coding-standards/SKILL.md`

```yaml
---
name: coding-standards
description: 项目编码规范和约定。当写代码、review 代码、讨论代码风格时参考。
user-invocable: false
---

# 编码规范

## 命名
- 函数: camelCase
- 类/组件: PascalCase
- 常量: UPPER_SNAKE_CASE
- 文件: kebab-case

## 导入顺序
1. 外部包
2. 内部模块（绝对路径）
3. 相对路径

## 错误处理
- async 操作必须 try/catch
- 用结构化日志，不用 console.log
- 返回有意义的错误信息

## 禁止
- 不要在业务层硬编码配置值
- 不要用 any 类型（除非有注释说明原因）
- 不要在循环里做异步操作（用 Promise.all）
```

### 3.2 simplify（手动调用，代码审查）

位置：`~/.claude/skills/simplify/SKILL.md`

```yaml
---
name: simplify
description: 审查最近改动的代码，检查复用性、质量和效率，修复发现的问题。
disable-model-invocation: true
---

审查当前改动的代码：

1. **检查改动范围**：`git diff --cached` 或 `git diff HEAD~1`
2. **逐文件审查**：
   - 是否有重复代码可以提取？
   - 命名是否清晰？
   - 是否过度工程？
   - 是否有性能问题？
3. **修复发现的问题**（直接改，不只是报告）
4. **输出审查摘要**：改了什么、为什么改
```

### 3.3 review-pr（手动调用，PR 审查 + push 标记）

位置：`~/.claude/skills/review-pr/SKILL.md`

```yaml
---
name: review-pr
description: 全面审查当前分支的 PR，通过后写入 push 审查标记。
disable-model-invocation: true
context: fork
agent: general-purpose
---

全面审查当前分支的所有改动：

## 审查维度
1. **功能正确性**：改动是否完成了预期目标？
2. **代码质量**：是否遵循编码规范？有无 code smell？
3. **安全性**：有无注入风险、硬编码密钥、权限问题？
4. **性能**：有无 N+1 查询、不必要的重渲染、内存泄漏？
5. **测试覆盖**：关键路径是否有测试？
6. **向后兼容**：是否会破坏现有 API/接口？

## 审查流程
1. 运行 `git log main..HEAD --oneline` 查看所有提交
2. 运行 `git diff main...HEAD` 查看完整改动
3. 逐文件深入审查
4. 如发现问题，列出并建议修复
5. **如果审查通过**，创建标记文件：
   ```bash
   mkdir -p .claude && echo "approved $(date -Iseconds)" > .claude/push-approved
   ```
6. 输出审查结论

## 评分
- ✅ PASS：可以 push
- ⚠️ WARN：有小问题但不阻塞，列出后写标记
- ❌ FAIL：有严重问题，不写标记，列出必须修复的项
```

### 3.4 security-review（手动调用，安全审查）

位置：`~/.claude/skills/security-review/SKILL.md`

```yaml
---
name: security-review
description: 安全审查，检查代码中的安全漏洞和风险。
disable-model-invocation: true
context: fork
agent: Explore
---

安全审查清单：

1. **硬编码密钥扫描**
   - 搜索：API key、token、password、secret 相关字符串
   - 检查 .env 文件是否在 .gitignore 中

2. **输入验证**
   - 所有用户输入是否经过验证/清理？
   - SQL 查询是否使用参数化？
   - 是否有 XSS 风险？

3. **认证与授权**
   - 敏感端点是否有权限检查？
   - token 是否有过期机制？

4. **依赖安全**
   - 运行 `npm audit` 或等价命令
   - 检查是否有已知漏洞

5. **数据保护**
   - 敏感数据是否加密存储？
   - 日志中是否泄露敏感信息？

输出格式：
- 🔴 严重：必须立即修复
- 🟡 警告：建议修复
- 🟢 信息：改善建议
```

### 3.5 pre-review（动手前方案评审 — 灵魂 10 问前半）

位置：`~/.claude/skills/pre-review/SKILL.md`

```yaml
---
name: pre-review
description: 动手前方案评审。当要开始写代码、实现新功能、做大改动前自动触发。确保 AI 先回答灵魂问题再动手。
user-invocable: true
---

在写第一行代码之前，你必须先回答以下问题，用大白话让非技术人员也能听懂：

## Q1 | 理解确认
用一句话解释这个模块要做什么？大白话，让我听懂的那种。

## Q2 | 任务拆解
这次的任务拆得够细吗？每个子任务是否能在一次对话内完成并独立验收？
有没有哪个子任务大到你自己都没把握一次做对、需要再拆的？

## Q3 | 抄作业审计
是在抄作业（参考现有方案）还是自己发挥？
- 抄的哪个作业，参考来源可靠吗？
- 有多少比例是发挥的？发挥的部分是否是核心设计？风险大不大？

## Q4 | 设计分层意图
你打算怎么分层？
- 哪些是稳定不变的硬逻辑（写代码）
- 哪些是未来会频繁调整的软逻辑（抽成配置/MD）

## Q5 | 接口设计意图
这个模块对外暴露什么接口？和其他模块的依赖关系是什么？
是否能即插即拔、独立可运行？

## Q6 | 扩展性压测
如果未来用户量涨 10 倍，哪里会有问题？

## Q7 | 可替换性评估
如果我以后要换掉这个模块，改动范围有多大？

---

输出格式：逐条回答，每条不超过 3 行。
**全部回答完毕后，等用户确认"可以动手"才开始写代码。**
```

### 3.6 post-review（交付后质量验收 — 灵魂 10 问后半）

位置：`~/.claude/skills/post-review/SKILL.md`

```yaml
---
name: post-review
description: 交付后质量验收。当完成编码、说"做完了"时自动触发。逐条对照灵魂问题验收。
user-invocable: true
---

你说"做完了"，在交付前需要逐条过以下验收清单：

## Q1 | 实现确认
再用一句大白话说一下你实际做了什么？和动手前说的一致吗？
如果有偏差，明确说出来。

## Q2 | 分层落地验证
实际代码里，软逻辑是否真的抽成了配置/MD？
有没有本该是配置的东西被你硬编码进去了？

## Q3 | 解耦落地验证
实际代码里，这个模块是否真的独立可运行？
接口是否和动手前定义的一致？有没有偷偷依赖了其他模块的内部实现？

## Q4 | 可观测性验收
这个模块是否有完善的日志输出、错误提示？
非技术人员怎么看到效果？怎么知道它工作正常？

## Q5 | 安全边界
这个模块的安全边界在哪里？
用户能通过输入什么奇怪的东西来搞坏它吗？

## Q6 | 规范一致性对比
这次写的代码是否遵循了编码规范？
挑一个已有模块，把新旧接口放在一起对比给我看。

---

输出格式：逐条回答，每条标注 ✅ 通过 / ⚠️ 有瑕疵 / ❌ 不通过。
**有 ❌ 项必须修复后重新验收，不能直接交付。**
```

### 3.7 verification-loop（手动调用，验证循环）

位置：`~/.claude/skills/verification-loop/SKILL.md`

```yaml
---
name: verification-loop
description: 对最近的代码改动进行全面验证循环：构建、测试、lint、类型检查。
disable-model-invocation: true
---

验证循环（按顺序执行，任一步失败则修复后重试）：

## 步骤
1. **类型检查**：`npm run typecheck` 或 `npx tsc --noEmit`
2. **Lint**：`npm run lint`
3. **单元测试**：`npm test`
4. **构建**：`npm run build`

## 失败处理
- 如果某步失败，分析错误信息
- 修复问题
- 从失败的步骤重新开始验证
- 最多重试 3 轮

## 完成条件
所有 4 步全部通过 → 输出验证摘要
```

---

## Phase 4：Permissions + Sandbox 配置

### settings.json 权限部分

```json
{
  "permissions": {
    "allow": [
      "Read",
      "Glob",
      "Grep",
      "Bash(npm run *)",
      "Bash(npx *)",
      "Bash(git status*)",
      "Bash(git log*)",
      "Bash(git diff*)",
      "Bash(git branch*)"
    ],
    "deny": [
      "Bash(rm -rf *)",
      "Bash(curl * | bash)",
      "Bash(wget * | bash)"
    ]
  }
}
```

---

## Phase 5：自循环与高级自动化

### 5.1 Commit 自动链（CLAUDE.md 指令 + Hook 配合）

**CLAUDE.md 中写明（AI 判断部分）：**
```markdown
### Commit 工作流
当用户说"提交"：
1. 先确认改动范围（git diff --cached）
2. commit 会自动触发 build check（Hook 处理）
3. commit 成功后，根据改动大小：
   - 小改动（< 50 行）：直接完成
   - 中改动（50-200 行）：建议运行 /simplify
   - 大改动（> 200 行）：建议运行 /review-pr

当用户说"推上去"：
1. 先检查是否有 .claude/push-approved 标记
2. 没有 → 先运行 /review-pr
3. 有标记 → 执行 git push（Hook 验证标记）
4. push 成功后建议创建 PR
```

### 5.2 Session 生命周期（CLAUDE.md 指令）

```markdown
### Session 管理
- 任务完成后提醒用户是否需要 /clear
- 对话超过 10 轮工具调用后，提醒检查上下文占用
- 调研和编码分开：先调研总结，/clear 后再编码
```

### 5.3 无状态调用模式（Harness Engineering 核心）

```markdown
### 状态外置
- 任务进度写入 docs/exec-plans/active/（不依赖对话历史）
- 每次长任务开始前，先读取 exec-plan 获取状态
- 失败时建议 /clear 重新开始，而非在腐烂的上下文上续写
```

---

## Phase 6：Custom Agents（高级，按需）

位置：`~/.claude/agents/code-reviewer/CLAUDE.md`

```yaml
---
name: code-reviewer
description: 代码审查 agent，专注于质量和安全
tools: Read, Grep, Glob, Bash
model: sonnet
maxTurns: 10
---

你是代码审查专家。审查代码时关注：
1. 逻辑正确性
2. 安全风险
3. 性能问题
4. 代码可维护性

输出格式：按严重程度排序，给出具体的修复建议。
```

---

## 实施清单

### Week 1：Phase 1 + 2（地基 + 基础 Hook）
- [ ] 创建项目 CLAUDE.md（诚实标注机械执行 vs AI 判断）
- [ ] 创建 ARCHITECTURE.md
- [ ] 创建 docs/ 目录结构
- [ ] 创建 `~/.claude/hooks/` 目录
- [ ] 编写 session-start.sh
- [ ] 编写 pre-bash-guard.sh（统一守卫：.env检测 + commit check + push门禁）
- [ ] 编写 post-edit-format.sh
- [ ] 编写 pre-compact-inject.sh
- [ ] 配置 settings.json hooks 部分
- [ ] 测试每个 hook 工作正常

### Week 2：Phase 3（核心 Skills）
- [ ] 创建 coding-standards Skill（背景知识）
- [ ] 创建 simplify Skill（手动调用）
- [ ] 创建 review-pr Skill（手动调用 + push 标记）
- [ ] 测试 commit → /simplify → push 工作流

### Week 3：Phase 4 + 5（权限 + 自循环）
- [ ] 配置 permissions
- [ ] 完善 CLAUDE.md 中的自动链指令
- [ ] 创建 security-review Skill
- [ ] 创建 verification-loop Skill
- [ ] 端到端测试完整工作流

### Week 4+：Phase 6（持续迭代）
- [ ] 根据实际使用中的 Agent 错误，更新 CLAUDE.md
- [ ] 根据需要添加 Custom Agents
- [ ] 定期审计：哪些 hook 真正有用，哪些可以删除
- [ ] 标注"临时补偿约束" vs "永久架构约束"

---

## 关键注意事项

### Hook 性能预算
| Hook 类型 | 延迟 | 频率 | 建议 |
|-----------|------|------|------|
| command（sync） | 5-100ms | 每次工具调用 | PreToolUse 必须 < 5s |
| command（async） | ~0ms | 不阻塞 | PostToolUse 首选 |
| prompt | 500ms-2s | 慎用 | 不要放在高频事件上 |
| agent | 2-10s | 极少用 | 只用在 Stop 等低频事件 |

### Skill Context 预算
- 所有 Skill 描述总共占 ~2% 上下文（约 16,000 字符）
- 6-8 个 Skill 是合理范围
- 超出时用 `/context` 检查是否有 Skill 被排除
- 把不常用的 Skill 设为 `disable-model-invocation: true` 减少描述加载

### "可撕除"标注
在 CLAUDE.md 或 Skill 中标注临时约束：
```markdown
<!-- TEMPORARY: 此约束因为模型当前在 X 场景下会犯 Y 错误。
     当模型改进后应移除。最后审查: 2026-03-12 -->
```

### 社区最新关键发现（2026-03）

1. **Stop hook > PostToolUse hook 做格式化**
   - PostToolUse 每次编辑后格式化 → 每次产生 system reminder → 吃上下文
   - Stop hook 每轮回复后批量格式化 → 仅 1 次 → 上下文干净
   - 来源：[GitButler Blog](https://blog.gitbutler.com/automate-your-ai-workflows-with-claude-code-hooks/)

2. **SessionStart matcher 要包含 `compact`**
   - `"matcher": "startup"` 只在新会话注入
   - `"matcher": "startup|compact"` 在 compact 后也重新注入，长对话不丢上下文
   - 来源：社区实践 + 官方文档

3. **PreToolUse 不要阻塞 Edit/Write**
   - 在写文件时阻塞会打断 Claude 多步推理链，导致它丢失计划
   - 验证应放在 PostToolUse 或 Stop，不在写入时阻塞
   - 来源：[DataCamp Hooks Tutorial](https://www.datacamp.com/tutorial/claude-code-hooks)

4. **可靠性递减法则**
   - 单步 95% 准确率 × 20 步 = 36% 系统可靠率
   - 解决方案：每步自校验 + 护栏引擎（如 claude-code-harness 的 R01-R09 规则）
   - 来源：[claude-code-harness](https://github.com/Chachamaru127/claude-code-harness)

5. **Plugin 生态可以直接复用**
   - `claude-code-harness`：5 个动词 Skill（plan/execute/review/release/setup）+ TypeScript 护栏
   - `everything-claude-code`：完整的 instinct/memory/security 系统
   - 安装方式：`/plugin marketplace add <repo>` → `/plugin install <name>`

---

## 可移植部署架构

### 设计原则
本系统设计为**模板化可移植**：在 `C:\AI for better\` 下维护模板，
复制到任何项目后通过 setup 脚本自动适配。

### 目录结构

```
C:\AI for better\                    ← 模板仓库（你现在所在的地方）
├── HARNESS_ROADMAP.md               ← 本文档（路线图 + 知识库）
├── templates/
│   ├── hooks/                       ← Hook 脚本模板
│   │   ├── session-start.sh
│   │   ├── pre-bash-guard.sh
│   │   ├── stop-format.sh
│   │   └── pre-compact-inject.sh
│   ├── skills/                      ← Skill 模板
│   │   ├── coding-standards/SKILL.md
│   │   ├── simplify/SKILL.md
│   │   ├── review-pr/SKILL.md
│   │   ├── security-review/SKILL.md
│   │   └── verification-loop/SKILL.md
│   ├── agents/                      ← Agent 模板
│   │   └── code-reviewer/CLAUDE.md
│   ├── settings.template.json       ← settings.json 模板
│   ├── CLAUDE.template.md           ← 项目 CLAUDE.md 模板
│   └── ARCHITECTURE.template.md     ← 架构文档模板
├── setup/
│   ├── deploy.sh                    ← 一键部署脚本
│   └── detect-project.sh            ← 项目类型自动检测
└── docs/
    └── golden-principles.md         ← 黄金原则模板
```

### 部署流程（一键）

```bash
# 1. 复制模板到目标项目
cd /path/to/your-project
bash "/c/AI for better/setup/deploy.sh"

# deploy.sh 会自动：
# - 检测项目类型（Node/Python/Unity/Go...）
# - 复制对应的 hooks 和 skills
# - 生成适配的 settings.json
# - 创建项目 CLAUDE.md（用模板填充检测到的信息）
# - 在需要你做选择时暂停提问
```

### 用户决策点（只在这些地方需要你参与）

| 步骤 | 你需要做什么 | 默认值 |
|------|------------|--------|
| 项目名称 | 输入或确认 | 目录名 |
| 项目类型 | 确认自动检测结果 | 自动检测 |
| 是否启用 push 门禁 | 是/否 | 是 |
| 是否启用自动格式化 | 是/否 | 是 |
| 主分支名称 | 确认 | main |

其余全部自动完成。
