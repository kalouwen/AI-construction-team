# 进化报告 — 2026-03-24（第 2 代）

## 健康概览
- 数据量：92 条记录，覆盖 2026-03-16 ~ 2026-03-24（9天）
- 健康比：**75.4%**（pos=92, neg=30）
- 趋势：**上升**（前20条 72.4% → 后20条 81.5%）
- 评级：**健康**（>70% 为健康线）

## vs Gen 1 对比
| 维度 | Gen 1 (03-16) | Gen 2 (03-24) | 变化 |
|------|--------------|--------------|------|
| 信号数据 | 零（采集失效） | 92 条 | **P0 已修复** |
| 健康比 | 无数据 | 75.4% | 首次有基线 |
| 趋势 | 不可知 | 上升 | 正向 |
| 模板库 | 无实战验证 | CCGS学习+8项改进 | 显著增长 |

## 信号分布

| 信号 | 次数 | 占比 | 类型 | 诊断 |
|------|------|------|------|------|
| completed | 56 | 61% | 正面 | 基线正常 |
| multi_path | 23 | 25% | 正面 | 路径穷举规则生效 |
| repeated_mistake | 11 | 12% | **负面** | 最大问题源，见下 |
| consulted_user | 8 | 9% | 正面 | 先问再做意识在建立 |
| honest_uncertainty | 5 | 5% | 正面 | 不确定性标注偏低 |
| vague_confidence | 5 | 5% | 负面 | 集中在早期，已改善 |
| self_correction | 3 | 3% | 负面 | 低频，不构成问题 |

## 问题诊断

### 1. repeated_mistake 是唯一持续的负面信号（信心：高）

日密度稳定在 12-15%，没有改善趋势：
- 03-17: 13% (2/15)
- 03-18: 15% (2/13)
- 03-19: 12% (3/26)
- 03-20: 13% (4/31)
- 03-24: 0% (0/6) — 样本太少不计

特征：11 次 repeated_mistake 全部 neg=2（强信号），且经常紧跟着 completed（说明错误被修复了但同类错误会在别处再现）。3月20日出现了连续两条 repeated_mistake（08:03 + 08:04），说明是同一会话中的重复犯错。

**根因分析**：repeated_mistake 表示 AI 在同一会话中重复犯同类错误。可能原因：
- feedback memory 没被读取或没生效
- 错误类型在 memory 中没有覆盖
- AI 理解了规则但在执行中遗忘（长会话上下文衰减）

### 2. vague_confidence 已自然消退（信心：高）

5 次中 3 次在 03-17 早期，之后只出现 2 次（03-19、03-20 各 1 次）。不确定性量化规则已内化，不需额外干预。

### 3. honest_uncertainty 和 consulted_user 偏低（信心：中）

5% 和 9% 的出现率说明 AI 主动标注不确定和主动问用户的频率不高。但这可能是因为大部分任务确实不需要（都是框架自身的改动，AI 对此比较确定）。**暂不判为问题，标记观察。**

## 组件评分

### Hooks（14 个）

| Hook | 评分 | 状态 | 理由 |
|------|------|------|------|
| evolution-score.sh | **7/10** | VALIDATED | Gen 1 为 2 分（零输出），现在稳定产出数据，P0 已修复 |
| pre-bash-guard.sh | 7/10 | VALIDATED | 无 hooks.jsonl 无法精确评，从零 security 事故推断生效 |
| pre-edit-guard.sh | 7/10 | VALIDATED | 同上 |
| anti-rationalization.sh | 6/10 | UNKNOWN | 无触发数据，可能生效也可能从未触发 |
| instinct-extract.sh | 5/10 | INEFFECTIVE | Gen 0/1 均诊断为断头路，至今未修复 |
| session-start.sh | 7/10 | VALIDATED | 会话启动正常工作 |
| pre-compact-inject.sh | 7/10 | VALIDATED | compact 后恢复正常 |
| detect-gaps.sh | N/A | 新增 | 今天刚加，无数据 |
| log-agent.sh | N/A | 新增 | 今天刚加，无数据 |
| session-save.sh | 5/10 | UNKNOWN | 无触发数据 |
| stop-format.sh | 6/10 | UNKNOWN | 无触发数据 |
| post-edit-verify.sh | 6/10 | UNKNOWN | 无触发数据 |
| post-codegen-verify.sh | 6/10 | UNKNOWN | 无触发数据 |
| parse-config.sh | 7/10 | VALIDATED | 被其他 hook source，基础设施 |

### Skills（10 个模板 + 8 个活跃）

| Skill | 评分 | 状态 | 理由 |
|------|------|------|------|
| survey | 8/10 | VALIDATED | 多次实战使用，今日加了 Step 0 预扫描 |
| mode-deploy | 7/10 | VALIDATED | GTA 部署实战验证过 |
| mode-learn | 8/10 | VALIDATED | 本次会话正在使用，工作流完整 |
| mode-plan | 7/10 | VALIDATED | 实战使用过 |
| mode-skills | 6/10 | UNKNOWN | 使用频率不明 |
| evolution-review | 7/10 | VALIDATED | 正在使用，Gen 1 建议的"执行确认"已内置 |
| check | 6/10 | UNKNOWN | 使用频率不明 |
| build | 5/10 | UNKNOWN | 未见实战使用记录 |
| merge | 5/10 | UNKNOWN | 未见实战使用记录 |
| reverse-document | N/A | 新增 | 今日创建，未实战 |

### Agents（5 个模板 + 3 个活跃）

| Agent | 评分 | 状态 | 理由 |
|------|------|------|------|
| research | 8/10 | VALIDATED | 本次会话大量使用，输出质量高 |
| planner | 7/10 | VALIDATED | 实战使用过，今日升级（协作网络+域权+绝不做） |
| doc-search | 7/10 | VALIDATED | 本地知识库查询有效 |
| code-reviewer | 6/10 | UNKNOWN | 模板已升级但无使用数据 |
| security-reviewer | 5/10 | UNKNOWN | 模板已升级但无使用数据 |
| test-writer | 5/10 | UNKNOWN | 模板已升级但无使用数据 |

### Memory（40 个文件）

| 状态 | 数量 | 说明 |
|------|------|------|
| 活跃且准确 | ~30 | 认知框架、行为规则、核心框架 |
| 可能过期 | ~5 | project_team_agent（已标历史）、project_harness_plan、project_system_assessment（5天前） |
| 今日新增 | 1 | reference_ccgs.md |

## Gen 1 问题复查

| Gen 1 问题 | 状态 | 说明 |
|------------|------|------|
| P0: 进化信号采集失效 | **已修复** | 92 条数据，稳定产出 |
| P1: AI game 经验未回流 | **部分完成** | 今日从 CCGS 学习了 8 项改进。AI game 自身的模式（知识淘汰/变体竞争）仍未回流 |
| P2: instinct-extract 断头路 | **未修复** | 仍是断头路 |
| P3: doctor skill 目标漂移 | **已解决** | doctor skill 已删除 |
| P4: Memory 保鲜 | **部分完成** | team_agent 已标历史，AI game memory 已建立 |

## 进化系统 9 项 backlog 复查

| # | 问题 | 优先级 | 状态 | 说明 |
|---|------|--------|------|------|
| 1 | 信号博弈 | P0 | **未变** | evolution-score 仍用正则自报告，无结果导向信号 |
| 2 | 没有回滚 | P0 | **未变** | 无 before/after 对比 |
| 3 | 不能生长新规则 | P1 | **未变** | instinct → 规则桥梁不存在 |
| 4 | 没有升级路径 | P1 | **未变** | 无 upgrade.sh |
| 5 | 冷启动 | P1 | **未变** | 新项目无合理初始状态 |
| 6 | 进化无版本控制 | P2 | **未变** | rules-catalog.json 无历史 |
| 7 | 无健康检查 | P2 | **部分解决** | detect-gaps.sh 提供了知识缺口检测，但非进化系统健康检查 |
| 8 | 无跨项目学习 | P2 | **未变** | 各项目独立进化 |
| 9 | 并发安全 | P3 | **未变** | 无锁 |

## 改进方案（按优先级）

### 1. repeated_mistake 根因修复（信心：中）

**问题**：12-15% 的稳定负面信号率，无改善趋势。

**方案 A**：在 session-start.sh 中注入最近 5 条 feedback memory 摘要
- 当前 session-start 不注入 memory 内容，AI 需要主动去读
- 改为启动时自动输出 feedback 类 memory 的关键规则
- 预期：减少"知道规则但执行时遗忘"的情况
- 风险：低，增加 ~500 tokens 启动上下文

**方案 B**：在 evolution-score.sh 中记录 repeated_mistake 的具体内容
- 当前只记录信号类型，不记录具体是什么错误重复了
- 加 `detail` 字段，从 AI 回复中提取错误描述
- 预期：下次审查能精确定位是哪类错误在重复
- 风险：低，但正则提取可能不准

**推荐：A+B 组合。A 防止遗忘，B 积累诊断数据。**

### 2. instinct-extract 闭环（信心：高）

**问题**：Gen 0、Gen 1、Gen 2 连续三代诊断为断头路，一直没修。

**方案**：在 session-start.sh 末尾加入 instinct 注入：
```bash
INSTINCT_FILE="$HOME/.claude/instincts/learned.md"
if [ -f "$INSTINCT_FILE" ]; then
  echo "=== 近期经验 ==="
  tail -10 "$INSTINCT_FILE"
fi
```
- 预期：经验采集→注入→被使用，闭环完成
- 风险：极低，10 行代码

### 3. 信号博弈缓解（信心：中）

**问题**：P0 级 backlog，evolution-score 用正则自报告信号，AI 可以刷分。

**方案**：不改正则检测（它已经在工作），但增加一个**校验层**：
- 每次 evolution-review 时，抽查最近 10 条 `completed` 信号，检查对应的工具调用是否真的完成了任务
- 如果发现"标记 completed 但实际未完成"的模式，记录为 `false_positive` 并降权
- 预期：不能根治博弈，但能检测博弈是否在发生
- 风险：低，只是审查流程改进

## 淘汰建议

| 组件 | 建议 | 原因 |
|------|------|------|
| instinct-extract.sh | **不淘汰，修闭环** | 采集端正常，缺消费端。修 session-start 即可 |
| build skill | **观察** | 无使用数据，但面向目标工程不是框架自身，保留 |
| merge skill | **观察** | 同上 |
| project_system_assessment.md | **需更新** | 5 天前的评估，今日有重大变更（8项改进） |
| project_harness_plan.md | **需确认** | 不确定是否仍活跃 |

---

*Gen 2 报告。vs Gen 1：P0 信号采集已修复（重大进展），首次有量化健康基线 75.4%，趋势上升。主要问题从"系统不工作"变为"repeated_mistake 持续 12-15%"。进化 backlog 9 项中 0 项完全解决（停滞），instinct 闭环连续三代未修。*
