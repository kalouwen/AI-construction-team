---
name: mode-learn
description: 学习模式——吸收信息，提炼规则，更新模板库和项目知识库。让框架越用越好。
user_invocable: true
---

# 学习模式

> **进度上报（必须执行）**：进入本模式后，立即用 Bash 工具写入活跃状态标记（将 `<目标工程路径>` 替换为实际路径，若为框架自身学习则用 AI for better 根目录）：
> ```bash
> mkdir -p "<目标工程路径>/.claude" && printf '{"mode":"learn","started_at":"%s","step":"启动学习"}' "$(date -Iseconds)" > "<目标工程路径>/.claude/active-mode.json"
> ```
> 每完成一个关键步骤（检查backlog/分类/提炼规则/更新模板/验证/标记digested），更新 step：
> ```bash
> printf '{"mode":"learn","started_at":"%s","step":"%s"}' "$(date -Iseconds)" "<当前步骤>" > "<目标工程路径>/.claude/active-mode.json"
> ```
> 模式结束时删除标记：`rm -f "<目标工程路径>/.claude/active-mode.json"`

你进入了 AI for better 的学习模式。你的核心任务是**吸收信息、提炼规则、更新知识体系**，让框架变得更完善、更通用。

## 信息来源（三类）

### 来源 A：用户主动输入
用户直接告诉你的经验、规则、教训、新工具信息。

### 来源 B：跨模式回流（backlog）
部署模式和 Skills 模式执行过程中记录的问题。存放在：
- `learning-backlog.jsonl`（AI for better 根目录）

进入学习模式时，**先检查 backlog 是否有未消化条目**。有则展示：
```
待消化的学习条目（{N}条）：
1. [P0][template_gap] Lua项目缺少pre-commit lint hook模板 — 来源: mode-deploy/GTA
2. [P1][knowledge_gap] 服装系统冲突规则未文档化 — 来源: mode-skills/GTA
```

### 来源 C：执行中发现
当前会话中处理 A 或 B 时，衍生出的新发现。

## 处理流程

### Step 1: 信息分类

每条信息分入以下类别：

| 类别 | 含义 | 目标归档位置 |
|------|------|-------------|
| `template_gap` | 模板库缺少某场景支持 | `templates/` 对应文件 |
| `template_fix` | 模板库已有内容需要修正 | `templates/` 对应文件 |
| `profile_gap` | 语言/框架 Profile 缺失或不全 | `templates/profiles/{lang}/` |
| `hook_gap` | 缺少某类守卫 hook | `templates/hooks/` |
| `knowledge_update` | 项目专属知识需要更新 | 目标工程 `.claude/knowledge/` |
| `best_practice` | 通用最佳实践 | `templates/docs/` 或 `templates/rules/` |
| `tool_discovery` | 发现了有用的新工具/插件 | 记录后建议 `/onboard-plugin` |

### Step 2: 提炼规则

从具体信息中提取可复用的规则：
1. **具体案例** → 抽象规则（去掉项目特有细节）
2. **单点修复** → 系统性改进（如果同类问题可能反复出现）
3. **隐含知识** → 显式规则（代码里暗含但没文档化的约定）

每条规则必须包含：
- **规则描述**：做什么 / 不做什么
- **适用范围**：什么项目/什么场景适用
- **执行方式**：用什么手段强制执行（hook? CI? lint规则?）
- **来源**：从哪个案例/项目提炼的

### Step 3: 归档

根据分类写入对应位置：

**通用模板更新**：
```
1. 读取当前模板文件
2. 找到需要修改的位置
3. 说明改什么、为什么改 → 等用户确认
4. 执行修改
5. 验证（shellcheck / 语法检查）
```

**项目专属知识更新**：
```
1. 确认目标工程路径
2. 读取现有 .claude/knowledge/ 下的对应文件
3. 增量更新（不全量覆盖）
4. 标注更新日期和来源
```

**新增文件**：
```
1. 说明为什么需要新文件（现有文件无法容纳）
2. 展示文件内容 → 等用户确认
3. 创建文件
4. 如果是 hook/脚本 → shellcheck 验证
```

### Step 4: 验证与确认

每次归档完成后：
- 模板文件 → `npx shellcheck` 或语法检查
- 知识文件 → 检查格式完整性
- 如果修改了 hook → 说明对已部署项目的影响

### Step 5: 更新 backlog

- 已消化的条目标记为 `"status": "digested"`，记录消化日期和产出
- 处理过程中新发现的问题 → 追加新条目

## backlog 条目格式

```json
{
  "id": "bl-20260320-001",
  "source": "mode-deploy",
  "project": "GTA",
  "type": "template_gap",
  "detail": "Lua项目缺少pre-commit lint hook模板",
  "priority": "P0",
  "created_at": "2026-03-20",
  "status": "pending",
  "digested_at": null,
  "digest_result": null
}
```

## 输出

每次学习完成后，展示变更摘要：

```
## 学习完成

### 本次消化
| 条目 | 类别 | 操作 | 影响范围 |
|------|------|------|---------|
| Lua lint hook 缺失 | template_gap | 新增 templates/hooks/lua-lint.sh | 所有 Lua 项目 |
| 服装冲突规则 | knowledge_update | 更新 GTA/.claude/knowledge/clothing.md | 仅 GTA |

### 模板库变更
- 新增: {文件列表}
- 修改: {文件列表}

### 待确认
- {需要用户决定的事项}

### 新发现（已写入 backlog）
- {处理过程中衍生的新问题}
```

## 重要规则

- **先消化 backlog 再处理新输入**：backlog 是之前实战中发现的问题，优先级更高
- **通用和专属必须分开**：不要把项目特有的规则写进通用模板
- **改模板前必须说明+确认**：模板影响所有未来部署，改动需谨慎
- **每条规则要有执行方式**：只写文字规则没有意义，必须说明怎么用代码强制执行
- **标注来源和置信度**：规则注明从哪来的，推断的标 [推断]
