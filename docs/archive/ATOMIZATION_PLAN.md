# AI for better — 原子化优化计划 v1.0

> 基于红蓝对抗分析，制定于 2026-03-18
> 对照文档：《原子化开发环境：让 AI 杠杆生效的开发方式》

---

## 分析方法

蓝队提出方案 → 红队攻击漏洞 → 综合裁定 → 写入计划。
每项都经过了对抗验证，不是拍脑袋的列表。

---

## P0：正在造成实际伤害（立即修）

> 这一层每一项今天都在产生错误信号或安全漏洞，不修会让整套体系的可信度下降。

---

### P0-1 质量棘轮是假的——只报告不阻断

**现状**
`weekly-quality.yml` 扫描 TODO/FIXME/大文件后，只生成报告上传为 artifact。没有任何 `exit 1`，哪怕代码质量翻倍变差，workflow 永远绿灯。这不是棘轮，这是日历提醒。

**大白话效果**
改之前：AI 每周生成一个没人看的报告，代码质量悄悄变差。
改之后：代码质量一旦退步，PR 自动卡住，强制修复才能合并。

**实现**
1. 引入 `.quality-baseline.json` 存储历史数字
2. 每次扫描与基准对比，数字增加时 `exit 1`
3. 合并后 CD 更新基准文件 commit 回 main
4. 基准文件加入 guardrail frozen 列表（防 AI 篡改）

**红队挑战** → AI 可直接修改基准文件绕过检测。
**应对** → 基准文件列为 frozen，只有 CI 流水线能更新，人工和 AI 均不可直接提交。

---

### P0-2 Guardrail 尺寸限制太宽松——20 个文件 500 行不叫原子化

**现状**
`signals.yaml` 默认值：`max_files_changed: 20, max_insertions: 500`。
AI 一轮改 20 个文件、写 500 行，完全通过护栏。
后果：judge 判 PASS 了，你不知道是哪 10 行起的作用。归因彻底断裂。

**大白话效果**
改之前：AI 一次改 20 个文件，你知道"这批改动让性能提升了 10%"，但不知道是哪个文件。
改之后：每次改动足够小，你能精确找到是哪 30 行产生了效果，可以复用这个经验。

**实现**
```yaml
guardrail:
  limits:
    max_files_changed: 5       # 原 20
    max_insertions: 100        # 原 500
    max_deletions: 80          # 原 300
    warn_files: 3              # 新增：3个文件以上开始警告
    warn_insertions: 60        # 新增
```
增加分级输出：warn 记录不阻断，超过 2 倍阈值升级为 block。

**红队挑战** → 重命名接口等任务天然要改很多文件，收紧会让 reward loop 频繁 block。
**应对** → `signals.yaml` 增加 `task_type` 字段（refactor/feature/bugfix/rename），`rename` 类型允许 `max_files: 30` 但 `max_insertions: 20`。分层约束，不一刀切。

---

### P0-3 Reward Loop 归因断裂——一轮多 commit，无法溯源

**现状**
`driver.py` 允许 AI 在一轮里做多次 commit，judge 判的是整个分支，合并时把所有 commit 一起并入。你只知道"这批改动 PASS 了"，不知道是哪一个 commit 起作用。

**大白话效果**
改之前：AI 做了 5 个小改动，你知道"这组改动让性能提升 10%"，但不知道是哪个。
改之后：每次进化对应一个 commit，`git show <sha>` 精确看到是什么带来了提升，可以学习和复用。

**实现**
将 `driver.py` 的 `--no-ff` merge 改为 squash merge：
```python
git("merge", "--squash", branch)
git("commit", "-m", f"evolve: round {round_num} — {description}")
```
`trajectory.jsonl` 每条记录补充 `commit_sha` 字段。

**红队挑战** → AI 有时做"先重构再实现"两步，squash 后中间过程丢失，下一轮 AI 看不到思考过程。
**应对** → 中间 commit 保留在分支上作为 AI 的工作记录，squash 只在合并到 base_branch 时发生。两者语义分离：分支上保留过程，main 上保留结果。

---

## P1：有但做错了的关键缺陷（本周内修）

> 这一层的问题不会立即崩溃，但会产生错误方向的激励：团队成员绕过门禁、AI 学到错误习惯、指标失去可信度。

---

### P1-1 Git Hooks 不随仓库传递——团队成员不受约束

**现状**
hooks 写入 `.git/hooks/`，不被 git 追踪。新成员 `git clone` 后直接开始工作，所有 pre-commit/commit-msg/pre-push 约束全不生效。AI 受约束，人类不受约束——产生双重标准。

**大白话效果**
改之前：工具只对手动运行过部署脚本的人生效，新同事完全绕过所有规则。
改之后：装完依赖就自动生效，所有人共享相同约束，没有漏网之鱼。

**实现**
- Node.js 项目：改用 husky，`.husky/` 进入版本控制，`package.json` 加 `"prepare": "husky"`
- Python 项目：改用 `pre-commit` 框架，`.pre-commit-config.yaml` 进入版本控制
- Unity/Go 项目：保留 `.git/hooks/`，但在 `Makefile` 的 `setup` target 中封装，README 明确指引

**红队挑战** → husky 只适用于 Node.js，不能强迫所有项目引入 Node 依赖。
**应对** → 三种语言三种方案，不强求统一工具，只要求"随仓库传递"这个结果。`detect-project.sh` 已经区分语言，按语言走不同安装路径。

---

### P1-2 CI 没有 Fail-Fast 顺序——便宜检查和贵的检查同时跑

**现状**
`ci.yml` 一次启动 4 个矩阵 runner + secret-scan。一个明显的 lint 错误，要等所有 runner 启动并安装依赖（2-3 分钟）才会报。lint 本身只需 10 秒。

**大白话效果**
改之前：一个拼写错误要等 3 分钟才知道，4 台服务器同时白烧。
改之后：10 秒就报错，矩阵测试根本不启动，省时省钱。

**实现**
```yaml
jobs:
  lint:
    steps:
      - run: __LINT_CMD__
      - run: __TYPECHECK_CMD__

  test:
    needs: [lint]   # lint 过了才启动矩阵
    ...
```
`deploy.sh` 替换 `__LINT_CMD__` 和 `__TYPECHECK_CMD__` 占位符，无 lint 命令时删除该 job。

**红队挑战** → 很多小项目没有独立 lint 命令，空占位符会让 lint job 失败或静默跳过。
**应对** → 检测 `lint_cmd` 是否为空，为空时整个 lint job 删除而不是留空，不影响已有流程。

---

### P1-3 PR 大小约束是 Checkbox——人工自觉，没有机械执行

**现状**
PR 模板中 `- [ ] PR < 200 lines changed` 依赖提交者诚实勾选，CI 对 PR 大小毫无感知。

**大白话效果**
改之前：PR 模板里有个格子让你自己勾"我的 PR 很小"，但没人检查。
改之后：PR 一开，机器自动量好尺寸，大了打标签，太大了锁门。

**实现**
`ci.yml` 增加 `size-check` job（和 lint 并行运行）：
```yaml
size-check:
  if: github.event_name == 'pull_request'
  steps:
    - name: Check PR size
      run: |
        LINES=$(git diff --stat origin/${{ github.base_ref }}...HEAD \
          | tail -1 | grep -oP '\d+ insertion' | grep -oP '\d+' || echo 0)
        if [ "$LINES" -gt 500 ]; then exit 1; fi
        if [ "$LINES" -gt 200 ]; then echo "::warning::PR is large ($LINES lines)"; fi
```
同时将 PR 模板中的 checkbox 改为说明文字——机器会量，用户无需手动申报。

**红队挑战** → `package-lock.json`、migration 文件等自动生成文件会把行数撑大，实际人工改动可能只有 20 行。
**应对** → 过滤已知自动生成文件（`*.lock`、`**/generated/**`），排除列表与 `labeler.yml` 共享同一份配置。

---

### P1-4 commitlint 只管格式，不管语义原子性

**现状**
`feat(auth): add login, update profile, fix dashboard` 格式完全合规，但包含 3 个不相关的改动，commitlint 照常放行。

**大白话效果**
改之前：commit 格式正确就放行，不管里面塞了几件事。
改之后：commitlint 能识别"你在一个 commit 里说了三件事"，提醒你拆开。

**实现**
`commitlint.config.js` 增加自定义规则，检测逗号分隔、多动词等多话题信号，级别设为 warn（不阻断，只提示），同时在 warn 消息中明确标准："如果这些改动可以独立回滚，就应该拆开"。

**红队挑战** → 正则误报率高，`feat: add login and logout` 是单话题，正则可能误判，让开发者觉得工具在讲废话。
**应对** → 保持 warn 级别，不设为 error。同时在 `rules-catalog.json` 中追踪该规则的触发次数和有效率，当 `ineffective` 时降级或关闭。工具提供信号，人类做最终判断。

---

## P2：完全缺失但影响较大（本月内建）

> 这一层的缺失不会让现有系统报错，但留下了"盲区"——AI 在这些场景下要么做无用功，要么无法自主完成任务。

---

### P2-1 Smart Scoping——文档/配置变更不触发完整测试矩阵

**现状**
任何改动——哪怕只修改一行 README——都触发 4 个矩阵 runner。修改文档不改变行为，跑测试纯属浪费。

**大白话效果**
改之前：改一个拼写错误，后台跑了 4 个服务器几分钟，白烧钱。
改之后：改文档几秒完事；改代码才跑完整流程。

**实现**
`ci.yml` 增加 `check-scope` job 使用 `dorny/paths-filter`（SHA 锁定），仅当代码文件变更时才触发测试矩阵：
```yaml
  test:
    needs: [lint, check-scope]
    if: needs.check-scope.outputs.code_changed == 'true'
```
`deploy.sh` 按语言类型生成对应的路径过滤列表。

**红队挑战** → `dorny/paths-filter` 是第三方 action，引入供应链风险。
**应对** → 锁定 commit hash（和现有 ci.yml 中 `actions/checkout` 一致的做法），`dependency-audit.yml` 增加 action 版本锁定检查。

---

### P2-2 文件大小强制限制——超过 500 行阻断提交

**现状**
"单文件不超过 500 行"写在文档里，没有任何自动执行机制，文件慢慢变大没人拦。

**大白话效果**
改之前：规定是写在文档里的，没有人执行，文件越来越大。
改之后：文件一旦超过 500 行，提交直接被拦，强制拆分。

**实现**
`git-hooks/pre-commit` 增加大小检查段，排除 `*.lock`、自动生成文件。排除列表存入 `guard-patterns.conf` 的新区块 `[large-file-exceptions]`，与 P1-3 的 size-check 共享。

**红队挑战** → protobuf 编译产物、ORM migration 文件经常超过 500 行但不应被拆分。
**应对** → 通过 `guard-patterns.conf` 例外列表解决，例外列表本身列为 frozen，防 AI 通过修改例外列表绕过大小限制。

---

### P2-3 Allowlist 模式——只允许修改指定文件

**现状**
`pre-edit-guard.sh` 是 blocklist 模式（指定文件不能改）。`autoresearch` 的关键设计是 allowlist（只有指定文件才能改）。对于高风险任务无法圈定范围。

**大白话效果**
改之前：只能告诉 AI "这些地方不能碰"，其他所有地方都能动。
改之后：可以告诉 AI "只能碰这些地方"，圈定范围后 AI 在范围外寸步不行。

**实现**
`guard-patterns.conf` 增加 `[edit-mode]` 配置项（默认 `blocklist`，可切换 `allowlist`）；`pre-edit-guard.sh` 读取模式，`allowlist` 时匹配到 `allowed-paths` 放行，否则阻断。`driver.py` 在特定任务类型时临时覆盖模式。

**红队挑战** → allowlist 对多文件重构任务过于限制，重命名接口需要改很多文件，会让 AI 能力大幅缩水。
**应对** → allowlist 是任务级别配置，不是全局配置。`driver.py` 根据任务类型（`autoresearch` 类）临时切换，其他任务保持 blocklist。

---

### P2-4 AI 产品实验追踪——prompt/model 变更的归因管理

**现状**
文章开篇核心问题：prompt 变化、model 变化、参数变化混在一起，结果变好时不知道归因给谁。`trajectory.jsonl` 只追踪代码变更，不追踪 AI 配置层面的变化。

**大白话效果**
改之前：你改了 prompt，测试通过率提升了，但不确定是 prompt 的功劳还是代码本身改好了。
改之后：每次进化记录"当时用的是哪个 prompt 模板"，可以直接对比两个版本的效果。

**实现**
`prompt.py` 在生成 prompt 时同时输出 `prompt_meta.json`（含 `template_hash`、`strategy_level`）；`driver.py` 的 trajectory 记录中增加 `prompt_hash` 字段；`observe.py` 增加最近 5 轮 prompt 版本变化分析；`circuit_breaker.py` PAUSE 信息中包含 prompt 版本时间线。

**红队挑战** → 每轮 prompt 内容不同（含当前代码状态），即使模板没变，hash 也每轮不同，区分意义不大。
**应对** → 分两层：`template_hash`（模板本身的 hash，只有改 `prompt.py` 代码时才变）和 `prompt_hash`（完整内容 hash，用于精确复现）。前者做版本归因，后者做调试。

---

## P3：结构性完善（下个季度）

> 这一层不影响当前使用，但系统扩展到多项目、多团队时会成为瓶颈。提前设计，不急于今天。

---

### P3-1 Release 流程——git tag 触发自动发版

git tag `v1.x.x` 时自动触发 CI，生成 Release Notes 发布到 GitHub Releases，`deploy.sh` 注入版本号。用户能知道"用的是哪个版本的 harness"，升级有 changelog 可查。

---

### P3-2 分支生命周期约束——超过 1 天自动预警

CI 定时检测超过 24 小时未合并的活跃分支，发 warning；超过 72 小时创建 issue 邀请处理。不强制阻断，但让"短命分支"成为默认习惯。

---

### P3-3 Branch Protection / Merge Queue（Layer 3）

新增 `setup/configure-branch-protection.sh`，调用 GitHub API 自动配置 branch protection rules（需要 PAT）。包含：status checks 必须通过、enforce admins、require PR review。这是文章明确列出的第 7 步，目前完全缺失。

---

## 我们已经做对的

这份计划专注于缺陷，但做对的部分同样需要记录，避免误读为"全部要推倒重来"。

**安全体系是业界前沿水平**
`pre-bash-guard.sh` 覆盖 6 个场景，配置驱动、不改脚本就能扩展新规则。`pre-edit-guard.sh` + `post-edit-verify.sh` 形成"改之前问权限，改之后验结果"的双重确认。

**Reward Hacking 防御设计精良**
`guardrail.py` 的三层检查（冻结边界/变更审计/作弊模式检测）覆盖了已知的主流 reward hacking 手法，`eval_modification` 和 `baseline_modification` 检测在业界极少见。

**进化系统的完整闭环是稀缺的**
`evolution-score.sh` → `instinct-extract.sh` → `session-start.sh` 注入经验，实现了"采集 → 提炼 → 回流"的完整闭环，大多数类似项目止步于采集。

**四层防御纵深已建立**
Layer 1（git hooks）、Layer 2（CI）、Layer 4（后台维护）全部覆盖。Layer 3 缺失但在 P3 计划中。

**部署体验足够好**
`detect-project.sh` 自动检测，模块化选项（每个功能可单独启用），两套系统（质量门禁 + 进化循环）通过统一 `deploy.sh` 部署。

---

## 执行路线图

```
第 1 天  P0-1  weekly-quality 加 .quality-baseline.json + exit 1
第 2 天  P0-2  guardrail 限制值收紧（5/100/80）+ task_type 分层
第 3 天  P0-3  driver.py 改 squash merge，trajectory 加 commit_sha
第 4-5天 P1-1  Node 项目改 husky，Python 项目加 pre-commit 框架
第 6 天  P1-2  ci.yml 加 lint job + needs 依赖
第 7 天  P1-3  ci.yml 加 size-check job，PR 模板改为说明文字
第 8 天  P1-4  commitlint.config.js 加多话题 warn 规则
第 2 周  P2-1  ci.yml 加 smart scoping
第 2 周  P2-2  pre-commit 加文件大小检查
第 3 周  P2-3  pre-edit-guard.sh 加 allowlist 模式
第 3 周  P2-4  prompt.py + driver.py 加 prompt 版本追踪
第 4 周+  P3   Release 流程 / 分支生命周期 / Branch Protection 脚本
```

---

*计划由红蓝对抗分析生成，每项均包含挑战和应对。执行前可按优先级逐项确认。*
