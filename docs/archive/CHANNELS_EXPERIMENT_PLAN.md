# Channels 实验推进计划

> 目标：验证 Claude Code Channels 的实际能力边界，评估是否可落地到 reward-loop 和可视化场景。
>
> 原则：**先跑通再优化，先单向再双向，先本地再远程**。

## 当前环境

| 项目 | 状态 |
|------|------|
| Claude Code | 2.1.80（Channels 最低版本，刚好满足） |
| Bun | **未安装**（fakechat/discord/telegram 依赖） |
| Node.js | 已安装（statusline.js 在用） |
| 已有可视化 | monitor.py (localhost:8420) + dashboard.py (静态HTML) |
| 认证方式 | claude.ai 登录（满足 Channels 要求） |
| MCP 经验 | coplay-mcp + playwright 已在用 |

## 实验分 4 个阶段

```
Phase 0  环境准备 + fakechat 冒烟测试
   ↓
Phase 1  自定义 webhook channel（单向推入）
   ↓
Phase 2  双向 channel（Claude 回推状态）
   ↓
Phase 3  可视化面板原型
```

每个 Phase 结束后有**明确的 Go/No-Go 判定点**，不通过就停。

---

## Phase 0：环境准备 + 冒烟测试（~30 分钟）

### 目标
确认 Channels 基础机制能跑通。

### 步骤

**0.1 安装 Bun**
```bash
# Windows 推荐方式
powershell -c "irm bun.sh/install.ps1 | iex"
# 验证
bun --version
```

**0.2 安装 fakechat 插件**
```bash
# 在 Claude Code 中
/plugin install fakechat@claude-plugins-official
```

**0.3 启动带 channel 的 Claude Code**
```bash
claude --channels plugin:fakechat@claude-plugins-official
```

**0.4 冒烟测试（5 个场景）**

| # | 测试 | 操作 | 观察什么 |
|---|------|------|---------|
| T1 | 基本推入 | 在 localhost:8787 发一条消息 | Claude 是否收到并响应 |
| T2 | 连发压力 | 快速发 5 条消息 | 是否排队？丢失？乱序？ |
| T3 | 执行中推入 | Claude 正在执行任务时发消息 | 中断还是排队？ |
| T4 | 权限卡点 | 触发需确认的操作，同时发 channel 消息 | 消息是否丢失 |
| T5 | context 消耗 | 反复发消息，观察 statusline 的上下文用量 | 每条消息约占多少 token |

### Go/No-Go
- T1 通过 → 继续
- T2 丢消息 → 记录丢失率，评估是否可接受
- T4 消息丢失 → **关键风险**，需要设计缓冲机制
- T5 每条消息 > 500 token → 高频场景需要严格控流

### 产出
- `experiments/channels/phase0-results.md`：5 个测试的实际结果

---

## Phase 1：自定义 webhook channel（单向）（~1-2 小时）

### 目标
验证"外部脚本向 Claude 推送事件"的核心能力。这是 reward-loop 集成的基础。

### 选型决策：Bun vs Node

fakechat 用 Bun，但我们的环境以 Node 为主。两个选择：

| 方案 | 优点 | 缺点 |
|------|------|------|
| **A: Bun** | 和官方示例一致 | 新增依赖，团队不熟悉 |
| **B: Node** | 已有环境，零新增依赖 | 需要确认 MCP SDK 在 Node 下的 channel 支持 |

**建议先用 Bun（和官方对齐），如果 Bun 环境有问题再退回 Node。**

### 步骤

**1.1 创建最小 webhook channel**

```
experiments/channels/webhook-channel.ts  (~50 行)
```

功能：
- 监听 `localhost:8788`
- 收到 HTTP POST → 注入 channel 事件给 Claude
- 带 `source`、`event_type`、`severity` 等 meta

**1.2 注册为 MCP server**

```json
// experiments/channels/.mcp.json
{
  "mcpServers": {
    "webhook": {
      "command": "bun",
      "args": ["run", "webhook-channel.ts"]
    }
  }
}
```

**1.3 模拟 reward-loop 事件**

手动用 curl 模拟 driver.py 的 3 种事件：

```bash
# 观测结果
curl -X POST localhost:8788 -H "Content-Type: application/json" \
  -d '{"type":"observe","round":1,"status":"3 tests failing, memory +15%"}'

# 判定结果
curl -X POST localhost:8788 -H "Content-Type: application/json" \
  -d '{"type":"verdict","round":1,"overall":"FAIL","reason":"memory regression"}'

# 熔断警告
curl -X POST localhost:8788 -H "Content-Type: application/json" \
  -d '{"type":"circuit_breaker","action":"PAUSE","consecutive_failures":3}'
```

**1.4 验证 Claude 的响应质量**

关键问题：
- Claude 看到 observe 事件后，是否能正确理解状态并建议下一步？
- Claude 看到 verdict FAIL 后，是否能分析原因并调整策略？
- Claude 看到 circuit_breaker 后，是否会停止自动操作？

### Go/No-Go
- Claude 能正确理解事件语义 → 继续
- Claude 把事件当普通聊天处理、不理解结构 → 需要调整 instructions
- 自定义 channel 注册失败或启动不稳定 → 评估是否等 API 稳定

### 产出
- `experiments/channels/webhook-channel.ts`：可用的 webhook channel
- `experiments/channels/phase1-results.md`：响应质量评估

---

## Phase 2：双向 channel（Claude 回推）（~2-3 小时）

### 目标
验证 Claude 能否可靠地通过 channel 往外推送状态。这是可视化的基础。

### 步骤

**2.1 给 webhook channel 加 reply tool**

新增工具：
```
update_status(data)  — Claude 调用此 tool 汇报工作状态
report_result(data)  — Claude 调用此 tool 提交任务结果
```

**2.2 测试 Claude 主动调 tool 的可靠性**

这是整个计划的**最大不确定性**。需要验证：

| 测试 | 方法 | 关注点 |
|------|------|--------|
| 指令遵从 | instructions 里写"每完成一步调 update_status" | Claude 是否每次都调？还是经常忘？ |
| 频率上限 | 让 Claude 执行 10 步任务，要求每步汇报 | 10 次 tool 调用是否都成功？ |
| 内容质量 | 检查 Claude 推出的状态数据 | 结构化？还是自由文本？ |
| 异常恢复 | tool 调用失败后 Claude 是否继续工作 | 不能因为汇报失败就停止正事 |

**2.3 和 hooks 对比**

同时开启 PostToolUse hook（已有）和 channel reply tool，对比：

| 维度 | Hooks | Channel reply tool |
|------|-------|-------------------|
| 触发确定性 | 100%（每次 tool 调用必触发） | 取决于 Claude 是否调用 |
| 数据丰富度 | 固定格式（tool_name + input） | Claude 自由组织，可含推理过程 |
| 延迟 | 同步，无延迟 | 取决于 Claude 决策时机 |
| 可定制性 | 低（hook 脚本固定输出） | 高（Claude 可以选择性汇报） |

### Go/No-Go
- Claude 调 tool 的遵从率 > 80% → 可视化可行，继续 Phase 3
- 遵从率 50-80% → 需要 hooks 补充，混合架构
- 遵从率 < 50% → 放弃 channel 可视化，回到纯 hooks 方案

### 产出
- `experiments/channels/phase2-results.md`：遵从率数据 + hooks 对比结论
- 双向 channel 代码

---

## Phase 3：可视化面板原型（~3-4 小时）

### 前提
Phase 2 的 Go 判定通过。

### 目标
一个浏览器面板，实时展示 Claude 的工作状态。

### 架构设计（三个方案，根据 Phase 2 结果选）

**方案 A：纯 Channel 驱动**（Phase 2 遵从率 > 80%）
```
Claude ──调 update_status tool──→ Channel Server ──WebSocket──→ 浏览器
                                       ↑
                                  HTTP Server (面板页面)
```
优点：数据最丰富（含 Claude 的推理过程）
缺点：依赖 Claude 主动调 tool

**方案 B：Hooks + Channel 混合**（Phase 2 遵从率 50-80%）
```
Hooks（确定性）──写 events.jsonl──→ Dashboard Server ──WebSocket──→ 浏览器
                                         ↑
Channel（交互性）──Claude 可回应面板操作──→
```
优点：数据完整性有 hooks 保底，交互性有 channel 补充
缺点：两套数据源需要合并

**方案 C：扩展现有 monitor.py**（Channel 可视化不可行时的兜底）
```
Hooks ──写 events.jsonl──→ monitor.py 增强版 ──HTTP 轮询──→ 浏览器
```
优点：零新依赖，基于已验证的代码
缺点：无交互性，Claude 不知道面板的存在

### 面板功能设计

无论哪个方案，面板应展示：

```
┌─────────────────────────────────────────────────┐
│  AI for better — Live Dashboard                 │
├──────────┬──────────────────────────────────────┤
│ 状态栏   │ ● 运行中  Round 3/20  已用 12m       │
├──────────┼──────────────────────────────────────┤
│          │ [2m ago] observe: 3 tests failing     │
│ 时间线   │ [1m ago] AI: fixing test_login.py     │
│          │ [30s]   verdict: PASS                 │
│          │ [now]   merging to main...            │
├──────────┼──────────────────────────────────────┤
│ 信号仪表 │ ✅ security  ✅ quality               │
│          │ ⚠️ test (2F) 🔴 perf (-8%)           │
├──────────┼──────────────────────────────────────┤
│ 操作区   │ [暂停] [跳过本轮] [人工审查]          │
│(仅方案AB)│ [发送指令给 Claude: _________ ]       │
└──────────┴──────────────────────────────────────┘
```

### Go/No-Go
- 面板能实时更新且数据准确 → 可落地，写入正式模板
- 面板有延迟但可用 → 可落地，标注限制
- 面板数据频繁缺失 → 退回方案 C（扩展 monitor.py）

### 产出
- `experiments/channels/dashboard/`：可用的面板原型
- `experiments/channels/phase3-results.md`：最终评估

---

## 风险总览

| 风险 | 影响 | 概率 | 缓解 |
|------|------|------|------|
| **Bun 安装失败或不稳定** | Phase 0 卡住 | 低 | 退回 Node.js 实现 |
| **Channels API 变更**（Research Preview） | 所有代码需要改 | 中 | 代码放 experiments/，不进正式模板 |
| **Claude 2.1.80 是最低版本，功能可能不全** | 某些 channel 特性不可用 | 中 | 升级 Claude Code |
| **context 消耗过快** | 长时间运行不可行 | 中 | 控制事件频率 + compact 策略 |
| **Claude 不可靠地调 reply tool** | 可视化数据断断续续 | 中高 | 混合架构（hooks 兜底） |
| **权限提示卡住会话** | 无人值守不可行 | 高 | 白名单提前配好，或接受有人值守 |
| **fakechat 插件启动失败** | Phase 0 卡住 | 低 | 手写最小 channel |

---

## 对正式模板的影响评估

### 如果实验成功，需要改的文件

| 文件 | 变更类型 | 时机 |
|------|---------|------|
| `templates/reward-loop/driver.py` | 新增 `--channel` 模式 | Phase 1 验证通过后 |
| `templates/reward-loop/signals.yaml` | 新增 `channel` 配置段 | Phase 1 验证通过后 |
| `templates/reward-loop/monitor.py` | WebSocket 支持 + channel 事件源 | Phase 3 完成后 |
| `templates/skills/autoloop/SKILL.md` | 新增 channel 模式指令 | Phase 2 验证通过后 |
| **新增** `templates/channels/` | channel 模板目录 | Phase 3 完成后 |

### 如果实验失败，回收价值

即使 Channels 不可落地，实验过程也能产出：
- MCP server 开发经验（对未来自定义工具有用）
- hooks vs channel 的量化对比数据
- 可视化面板的 UI 设计（可用于扩展 monitor.py）

---

## 时间线

| 阶段 | 预计耗时 | 依赖 |
|------|---------|------|
| Phase 0 | 30 分钟 | 安装 Bun |
| Phase 1 | 1-2 小时 | Phase 0 通过 |
| Phase 2 | 2-3 小时 | Phase 1 通过 |
| Phase 3 | 3-4 小时 | Phase 2 通过 |
| **总计** | **7-10 小时** | 分多个会话完成 |

> 每个 Phase 结束后建议 `/clear` 开新会话，避免实验过程的上下文残留影响判断。
