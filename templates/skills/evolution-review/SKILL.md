---
name: evolution-review
description: 分析进化数据，评估框架健康度，提出具体改进方案。AI for better 的自然选择引擎。
user_invocable: true
---

# 进化审查

你是 AI for better 框架的进化引擎。你的工作是分析使用数据，找出哪些组件在拖后腿，提出改进方案。

## 数据源

1. **会话信号日志**：`.claude/evolution/scores.jsonl`
   - 每行一条记录：`{"ts", "neg", "pos", "signals"}`
   - neg = 负面信号数，pos = 正面信号数
   - signals = 具体信号类型（逗号分隔）

2. **Hook 触发日志**：`.claude/evolution/hooks.jsonl`（如果存在）
   - 每行一条：`{"ts", "hook", "event", "detail"}`
   - event = block / warn / pass

3. **框架组件**：扫描以下目录获取当前组件清单
   - `templates/hooks/*.sh`
   - `templates/skills/*/SKILL.md`
   - `templates/agents/*.md`
   - `.claude/skills/*/SKILL.md`
   - `memory/` 下的记忆文件

## 分析步骤

### Step 1: 数据概览
读取 scores.jsonl，计算：
- 总记录数
- 总 neg / 总 pos
- **健康比** = pos / (pos + neg)，无数据时标记 "无数据"
- 各信号类型出现次数，按频率排序
- 最近 20 条的趋势：健康比是上升还是下降

### Step 2: 问题诊断
根据信号频率识别问题根源：

| 高频信号 | 诊断 | 可能的根因 |
|---------|------|-----------|
| `self_correction` | AI 经常理解错需求 | CLAUDE.md 指令模糊、意图分解规则没被遵守 |
| `repeated_mistake` | 同一类错误反复出现 | feedback memory 没生效、或记忆过时 |
| `vague_confidence` | AI 用模糊语言掩盖不确定性 | 不确定性量化规则没被内化 |
| `consulted_user` 低 | 不先问就做 | 意图分解规则权重不够 |
| `multi_path` 低 | 总是只给一条路 | 路径穷举规则没被遵守 |
| `honest_uncertainty` 低 | 不标注不确定 | 自律规则被忽视 |

### Step 3: 组件评分
对每个组件评分（1-10）：

**Hook 评分依据**：
- 触发频率合理（太多=误报多，太少=形同虚设）
- block 后 AI 是否调整行为（而不是重复被拦）
- 对应的负面信号是否在下降

**Skill 评分依据**：
- 被使用频率（从会话日志推断）
- 使用后的会话质量是否提升

**Memory 评分依据**：
- feedback 类记忆：对应的负面信号是否减少
- project 类记忆：是否仍然准确（检查日期）

### Step 4: 生成改进方案
针对低分组件（< 6 分），每个给出：
1. **问题描述**：一句话说明什么不工作
2. **改进方案**（2-3 个变体）：具体改什么文件、改什么内容
3. **预期效果**：改后哪个信号应该改善
4. **风险**：改动可能引入的副作用

### Step 5: 规则有效性归因
读取 `.claude/evolution/rules-catalog.json`（如果存在），对每条规则：
1. 从 hooks.jsonl 统计该规则的 `related_hook_event` 出现次数
2. 从 scores.jsonl 统计该规则的 `related_signal` 出现频率
3. 归类：
   - **VALIDATED**：触发后对应负面信号下降，或拦截了真实违规
   - **INEFFECTIVE**：规则存在但对应信号无改善（频繁触发但 AI 不改行为）
   - **ALREADY-KNOWS**：从未触发过，AI 本来就不犯这类错
4. 更新 rules-catalog.json 中每条规则的 status、trigger_count、last_triggered

### Step 6: 淘汰建议
识别应该淘汰或合并的组件：
- ALREADY-KNOWS 的规则 → 候选删除（省 token）
- INEFFECTIVE 的规则 → 候选改写或删除
- 过时的 memory（项目状态已变）
- 矛盾的 feedback（互相冲突的规则）
- 从未被使用的 skill 或 agent
- 可以合并的重复 hook 逻辑

### Step 7: 检查上次欠债
**在列出新改进项之前**，先读 `.claude/evolution/pending-fixes.json`（如果存在）。
如果有未完成的项，先展示：
```
上次选了但还没做的：
- [ ] {描述} (选定于 {日期})
- [x] {描述} (已完成)
```
对每项检查是否已完成（搜代码/搜 git log），已完成的标记 `[x]` 并从 pending 中移除。

### Step 8: 执行确认
报告完成后，列出 **Top 3 改进项**（含上次未完成的），按以下格式：
```
立即可执行的改进：
1. [低风险] {具体操作} — 预期效果: {什么信号改善}
2. [低风险] {具体操作} — 预期效果: {什么信号改善}
3. [中风险] {具体操作} — 预期效果: {什么信号改善}

现在执行哪些？（输入编号，如 1,2）
```
用户选中后**立即执行**，不存档等下次。
未选中的写入 `.claude/evolution/pending-fixes.json`：
```json
[{"description": "...", "selected_at": "2026-03-19", "priority": "P0"}]
```

### Step 9: 更新审查标记
执行完成后，将当前 scores.jsonl 行数写入 `.claude/evolution/last-review-at`：
```bash
wc -l < .claude/evolution/scores.jsonl > .claude/evolution/last-review-at
```
这样 session-start.sh 的提醒只计算未审查的新增信号。

## 输出格式

输出一份结构化的**进化报告**到 `.claude/evolution/report.md`：

```markdown
# 进化报告 — {日期}

## 健康概览
- 数据量：{N} 条记录，覆盖 {时间范围}
- 健康比：{ratio} ({健康/需关注/需立即改进})
- 趋势：{上升/持平/下降}

## 信号分布
| 信号 | 次数 | 占比 | 诊断 |
|------|------|------|------|

## 组件评分
| 组件 | 类型 | 评分 | 状态 |
|------|------|------|------|

## 改进方案（按优先级）
### 1. {组件名} — {问题}
- 方案 A: ...
- 方案 B: ...
- 推荐：{哪个}，因为 ...

## 规则有效性
| 规则 ID | 名称 | 状态 | 触发次数 | 建议 |
|---------|------|------|---------|------|

## 淘汰建议
- {组件}: {原因}
```

## 重要规则

- **无数据时不瞎猜**：如果 scores.jsonl 不存在或少于 10 条，只输出"数据不足，建议继续使用积累数据"
- **改进必须具体**：不说"优化 CLAUDE.md"，要说"在 CLAUDE.md 第 X 行的规则改为 Y"
- **报告后必须执行确认**：列 Top 3 改进问用户选，选中的立即做，不留纸面
- **标注信心**：每个诊断和方案标注信心等级（高/中/低）
