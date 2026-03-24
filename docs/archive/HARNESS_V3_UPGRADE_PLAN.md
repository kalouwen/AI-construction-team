# Harness V3 升级方案

> 基于社区顶级项目对标（ECC 73K stars、Trail of Bits、rulebook-ai），补齐 Harness V2 的关键差距。
>
> **审批方式**：逐条批注（做/不做/要聊聊），未确认项下轮置顶。

---

## 当前位置

Harness V2 已有：6 hooks + 10 skills + 模板体系 + 配置驱动（guard-patterns.conf）

对标社区后发现 **4 个 P0 差距 + 4 个 P1 差距**，以下逐条列出方案。

---

## P0 — 必须补（核心差距）

### P0-1. Anti-rationalization Hook（防偷懒检测）

**现状**：AI 回复"剩下的你可以自己..."、"基本完成了"时没人拦，用户可能以为真做完了。

**改什么**：新增一个 Stop hook（AI 完成回复后触发），扫描回复内容中的偷懒模式。

**具体操作**：
- 新建 `~/.claude/hooks/anti-rationalization.sh`
- 检测关键词：`"你可以自己"`, `"剩下的"`, `"大致完成"`, `"基本上"`, `"差不多了"`, `"as an exercise"`, `"left to the reader"` 等
- 检测模式加入 `guard-patterns.conf` 新区块 `[rationalization-patterns]`（配置驱动，不硬编码）
- 匹配到 → 输出警告："⚠️ 检测到可能的未完成标记，请确认是否真的做完了"
- 不阻断（Stop hook 不能阻断），但强制提醒

**为什么做**：Trail of Bits 的实战验证，AI 确实会偷懒。我们的 post-review 灵魂6问可以兜底，但那是手动触发的，这个是自动的。

---

### P0-2. 敏感路径 Deny Rules

**现状**：settings.json 的 deny 只防危险命令（rm -rf、force push），没防敏感目录读取。

**改什么**：在全局 settings.json 的 deny 列表中增加敏感路径。

**具体操作**：
```json
"deny": [
  // ... 现有15条 ...
  "Read(~/.ssh/**)",
  "Read(~/.aws/**)",
  "Read(~/.kube/**)",
  "Read(~/.gnupg/**)",
  "Read(**/.env)",
  "Read(**/.env.local)",
  "Read(**/credentials.json)",
  "Read(**/*secret*)",
  "Bash(cat ~/.ssh/*)",
  "Bash(cat ~/.aws/*)"
]
```
- 同步更新 templates/settings.template.json
- deploy.sh 部署时自动带上

**为什么做**：Trail of Bits 安全基线。成本极低（加几行配置），收益明确（防止 AI 读取密钥/凭证）。

---

### P0-3. Hook Profiles（多档位）

**现状**：hooks 全开或全关，没法按场景调整。探索性编码时 hooks 太严影响效率，正式开发时又需要最严。

**改什么**：在 guard-patterns.conf 中增加 profile 机制，hooks 读取当前 profile 决定执行哪些检查。

**具体操作**：
- 在 guard-patterns.conf 顶部新增 `[profile]` 区块：
  ```
  [profile]
  # 当前激活档位：minimal | standard | strict
  active=standard
  ```
- 定义三档行为：
  | 档位 | 行为 |
  |------|------|
  | minimal | 只跑 pre-bash-guard（危险命令拦截），其余 hook 跳过 |
  | standard | 全部 hook 正常执行（当前默认行为） |
  | strict | 全部 hook + 更严格的检测模式（如 TODO 也算 CRITICAL） |
- 每个 hook 脚本开头读取 profile，不在自己的执行范围内就直接 exit 0
- 提供切换命令：用户说"切到 minimal"→ AI 改 conf 文件即可

**为什么做**：ECC 的核心设计。调研阶段不需要提交门禁，正式开发需要最严。一刀切不灵活。

---

### P0-4. Instincts 自动学习（简化版）

**现状**：知识靠手动写 memory，AI 不会从自己的工作中自动提取模式。

**改什么**：新增 Stop hook，每次 AI 完成回复后自动提取本轮发现的模式，存入 instincts 文件。

**具体操作**：
- 新建 `~/.claude/instincts/` 目录
- 新建 `~/.claude/hooks/instinct-extract.sh`（Stop hook）
- 逻辑：
  1. 读取 AI 本轮回复内容
  2. 用简单规则提取模式（正则匹配 "发现"、"注意"、"改为"、"不要" 等关键信号）
  3. 写入 `~/.claude/instincts/learned.md`（追加模式，带时间戳和来源项目）
  4. 文件超过 100 行时自动归档旧条目到 `~/.claude/instincts/archive/`
- session-start.sh 启动时自动注入最近 20 条 instincts 作为上下文
- 用户可以手动审查和清理 instincts 文件

**为什么做**：这是 Harness 和 ECC 最大的差距。ECC 用 confidence 评分 + 聚类进化，但那套太复杂。我们先做**最小可用版**：自动提取 → 自动注入 → 手动审查。验证有效后再做 confidence 评分和进化机制。

**注意**：这是简化版，不做 confidence 评分和自动进化。先跑起来验证价值，再迭代。

---

## P1 — 有价值，排在 P0 之后

### P1-1. Subagents 体系化

**现状**：templates/agents/ 只有一个 code-reviewer，没充分利用。

**改什么**：补充 3-5 个常用 subagent 定义。

**具体操作**：
- `~/.claude/agents/code-reviewer.md` — 代码审查（已有，优化）
- `~/.claude/agents/security-reviewer.md` — 安全扫描
- `~/.claude/agents/research.md` — 调研专用（限定只读工具，不能编辑）
- `~/.claude/agents/planner.md` — 方案设计（输出 MD，不直接改代码）
- `~/.claude/agents/test-writer.md` — 测试编写

每个 agent 定义：名称、描述、可用工具白名单、模型选择（haiku/sonnet/opus）。

**为什么做**：subagent 有独立上下文窗口，不污染主对话。调研用 research agent，审查用 reviewer agent，符合我们"一窗口一任务"的原则。

---

### P1-2. Session Persistence（会话持久化）

**现状**：session-start.sh 只注入信息，session 结束时什么都不保存。下次开窗口，之前的工作上下文全丢。

**改什么**：新增 Stop hook，session 结束时自动保存摘要。

**具体操作**：
- 新建 `~/.claude/hooks/session-save.sh`（Stop hook 或用户主动 /clear 时触发）
- 保存内容到 `项目/.claude/sessions/latest.md`：
  - 当前分支和最近 3 条 commit
  - 本次 session 修改的文件列表
  - 未完成的 TODO（如果有 plan 文件，记录进度）
- session-start.sh 启动时检查 `sessions/latest.md`，如果存在就注入

**为什么做**：解决跨窗口上下文丢失问题。目前靠 memory 手动记，这个是自动的。

---

### P1-3. Progressive Disclosure（渐进式加载）

**现状**：CLAUDE.template.md 已经比较精简（~40行），但没有显式的按需加载机制。

**改什么**：规范化 CLAUDE.md 的"索引 → 详情"模式。

**具体操作**：
- CLAUDE.md 严格控制在 **60 行以内**（HumanLayer 建议）
- 详细规则拆到 `.claude/rules/` 下，按域分文件：
  ```
  .claude/rules/
  ├── code-style.md      # paths: ["**/*.cs", "**/*.go"]
  ├── git-workflow.md     # paths: ["**"]
  ├── security.md         # paths: ["**"]
  └── unity-specific.md   # paths: ["**/*.unity", "**/*.prefab"]
  ```
- rules 用 YAML frontmatter 的 `paths` 字段，按文件类型自动加载（Claude Code 原生支持）
- CLAUDE.md 中用 `@path/to/file` 语法引用关键文件（Claude Code 原生支持）

**为什么做**：官方最佳实践 + 社区共识。CLAUDE.md 越短，AI 遵循率越高。长规则放 rules，需要时自动加载。

---

### P1-4. GitHub Actions CI 集成

**现状**：PR 审查靠手动触发 /review-pr，没有自动化。

**改什么**：提供 GitHub Actions workflow 模板，自动触发审查。

**具体操作**：
- 新建 `templates/github-actions/` 目录
- `pr-review.yml` — PR 创建/更新时自动跑 Claude Code 审查，结果评论在 PR 上
- `weekly-quality.yml` — 每周自动跑代码质量检查，生成报告
- `dependency-audit.yml` — 双周自动检查依赖安全

**为什么做**：把人工触发变成自动触发。但优先级低于 P0，因为需要 CI 环境支持。

---

## 实施顺序

```
第一批（P0，核心补齐）：
  P0-2 敏感路径 Deny Rules     ← 最简单，加几行配置，10分钟
  P0-1 Anti-rationalization    ← 新增1个hook + conf区块，30分钟
  P0-3 Hook Profiles           ← 改 conf + 每个hook加profile判断，1小时
  P0-4 Instincts 简化版        ← 新增1个hook + 目录，1小时

第二批（P1，锦上添花）：
  P1-3 Progressive Disclosure  ← 重构 CLAUDE.template.md + 新增 rules 模板
  P1-1 Subagents 体系化        ← 新增 4 个 agent 定义
  P1-2 Session Persistence     ← 新增 1 个 hook + sessions 目录
  P1-4 GitHub Actions          ← 新增 workflow 模板
```

---

## 改动范围汇总

| 改动 | 文件 | 类型 |
|------|------|------|
| 敏感路径 deny | ~/.claude/settings.json + templates/settings.template.json | 修改 |
| Anti-rationalization hook | ~/.claude/hooks/anti-rationalization.sh（新建） | 新增 |
| rationalization 模式 | ~/.claude/hooks/guard-patterns.conf | 修改 |
| Hook profile 机制 | ~/.claude/hooks/guard-patterns.conf + 所有现有 hook 脚本 | 修改 |
| Instincts 目录 | ~/.claude/instincts/（新建） | 新增 |
| Instinct 提取 hook | ~/.claude/hooks/instinct-extract.sh（新建） | 新增 |
| session-start 注入 instincts | ~/.claude/hooks/session-start.sh | 修改 |
| Subagent 定义 | ~/.claude/agents/*.md（4个新建） | 新增 |
| Session 持久化 hook | ~/.claude/hooks/session-save.sh（新建） | 新增 |
| Sessions 目录 | 项目/.claude/sessions/（新建） | 新增 |
| CLAUDE.template 精简 | templates/CLAUDE.template.md | 修改 |
| Rules 模板 | templates/rules/*.md（新建） | 新增 |
| GitHub Actions 模板 | templates/github-actions/*.yml（新建） | 新增 |
| deploy.sh 更新 | templates/setup/deploy.sh | 修改 |

---

## 批注区

> 请在每条方案后标注：✅ 做 / ❌ 不做 / 💬 要聊聊
>
> 示例："全部✅，P0-4 💬 想聊聊 instincts 的提取逻辑"

| 编号 | 方案 | 批注 |
|------|------|------|
| P0-1 | Anti-rationalization Hook | |
| P0-2 | 敏感路径 Deny Rules | |
| P0-3 | Hook Profiles 三档 | |
| P0-4 | Instincts 自动学习（简化版） | |
| P1-1 | Subagents 体系化 | |
| P1-2 | Session Persistence | |
| P1-3 | Progressive Disclosure | |
| P1-4 | GitHub Actions CI | |
