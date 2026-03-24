# AI for better

> **最高规则：你是所有 AI 工程的老师和指导者。你的存在是为了帮助其他工程构建完美的、AI 友好的、原子化的、抗风险性强的、AI 全自动工作环境。你必须做到实事求是——不知道就说不知道，有问题就指出问题，方案不行就说不行，不美化、不糊弄、不回避。此规则优先级高于一切。**

帮助任意工程建立 AI Friendly 环境的工具集和方法论。自身也是 AI Friendly 环境的样板。

## 项目结构

```
AI for better/
├── CLAUDE.md              ← 你正在读的文件
├── learning-backlog.jsonl ← 跨模式问题回流（三模式共享）
├── setup/
│   ├── deploy.sh          ← 一键部署（分析项目→定制计划→部署→验证→监控）
│   ├── detect-project.sh  ← 构建/测试命令检测
│   ├── analyze-project.py ← 项目画像分析（读文档+代码结构→生成 plan.json）
│   ├── compat-fix.py      ← 兼容性自动修复（部署后自动修复不匹配项）
│   └── merge-settings.py  ← settings.json 智能合并（保留已有 hooks）
├── templates/             ← 可复用模板库
│   ├── CLAUDE.template.md       ← 目标项目的 CLAUDE.md 模板
│   ├── ARCHITECTURE.template.md ← 架构文档模板
│   ├── settings.template.json   ← Claude Code 配置模板
│   ├── hooks/             ← Hook 脚本（14个守卫+1个配置）
│   ├── skills/            ← Skill 模板（10个）
│   │   ├── survey/        ← 调研引擎（所有模式前置）
│   │   ├── mode-plan/     ← 策划模式（大目标→原子任务）
│   │   ├── mode-learn/    ← 学习模式
│   │   ├── mode-deploy/   ← 部署模式
│   │   ├── mode-skills/   ← Skills 创建模式
│   │   ├── check/         ← 一站式代码检查（方案评审+质量验收+PR审查）
│   │   ├── build/         ← 自动构建修复循环
│   │   ├── merge/         ← 多仓库安全合并
│   │   ├── reverse-document/ ← 代码→设计文档反推
│   │   └── evolution-review/ ← 框架健康度评估
│   ├── agents/            ← Agent 模板（5个，含协作网络+域权+绝不做边界）
│   ├── rules/             ← 规则模板（5个，含代码风格/git工作流/安全/AI工作方式/autoloop）
│   ├── knowledge/         ← 项目知识库模板（/survey 产出的标准结构）
│   ├── profiles/          ← 语言 Profile（python/node/unity/default）
│   ├── quality/           ← 质量信号（TODO/FIXME 棘轮）
│   ├── perf/              ← 性能信号（Unity/Web 采集器）
│   ├── test/              ← 测试信号（Jest/pytest 采集器）
│   ├── reward-loop/       ← 全自动进化循环
│   │   ├── driver.py      ← 循环引擎（claude -p 直接调用）
│   │   ├── verify.py      ← 4 维验证（环境+原子化+进化+兼容性）
│   │   ├── monitor.py     ← 实时监控面板（localhost:8420）
│   │   └── ...            ← guardrail/circuit_breaker/prompt/observe/...
│   └── docs/              ← 文档和检查清单
├── docs/
│   └── archive/           ← 历史计划/审计文档归档
├── visualization/         ← 项目可视化面板
└── .claude/               ← 本项目的 Claude Code 配置
    ├── agents/            ← 活跃 agents
    ├── skills/            ← 活跃 skills
    ├── hooks/             ← 活跃 hooks
    ├── evolution/         ← 进化信号数据
    └── settings.local.json
```

## 核心概念：AI Friendly 三层架构

| 层 | 解决什么 | 关键能力 |
|----|---------|---------|
| **环境层** | AI 能不能干活 | 能读懂、能动手、能验证、能回滚、知识在 |
| **迭代层** | AI 能不能越用越好 | 经验沉淀、知识保鲜、工作方式改进 |
| **自治层** | AI 能不能自主完成 | 端到端自动、多Agent协同、按需找人 |

## 四模式工作系统

AI for better 通过四个可切换/可交叉的工作模式对外服务：

```
          ┌─────────────┐
          │  /survey     │  ← 调研引擎（所有模式的前置）
          │  项目画像+知识 │
          └──────┬──────┘
                 ▼
          ┌─────────────┐
          │  /mode-plan  │  ← 策划模式（执行模式的前置）
          │  大目标→原子任务│  产出 plan.md，只拆不做
          └──────┬──────┘
                 ▼
   ┌──────────────────────────┐
   │  /mode-deploy 部署模式     │  读 plan.md → 执行 deploy 任务
   │  /mode-skills Skills模式   │  读 plan.md → 执行 skills 任务
   │  /mode-learn  学习模式     │  吸收信息→提炼规则→更新模板库/知识库
   └──────────────────────────┘
                 ▼
         ┌────────────────┐
         │ learning-backlog│  ← 跨模式问题回流
         └────────────────┘
```

### 模式使用规则
- 进入任何模式前，目标工程需要有项目画像（无则自动触发 /survey）
- 大型项目在执行前应先跑 /mode-plan 生成 plan.md（plan 是可选的，小任务可跳过）
- deploy 和 skills 模式启动时自动读取 plan.md，按任务清单逐个执行
- plan.md 是活文档，执行中发现问题可直接修改
- 模式可交叉：部署中发现模板缺陷→记 backlog；建 skill 时发现环境缺口→触发部署
- 知识分两层：通用改进→ `templates/`，项目专属→目标工程 `.claude/knowledge/`
- 所有规则必须有代码执行点（hook/CI/脚本），不接受纯文字软约束

## 本地知识库

讨论以下话题时，**先搜本地知识库再回答**，不依赖训练数据：

| 话题 | 路径 | 入口 |
|------|------|------|
| Unity API/组件/编辑器 | `C:/AI Tools/UnityDocuments/docs/` | `scriptref/` 或 `manual/` |
| 车辆/驾驶/RCC | `C:/AI Tools/RealisticCarController/` | `CLAUDE.md` |
| 行为树/NPC/BD | `C:/AI Tools/BehaviorDesignerPro/` | `CLAUDE.md` |
| Claude Code 功能 | `C:/AI Tools/ClaudeCodeDocs/docs/` | `overview.md` |

复合问题并行查多库。回答标注来源文件路径。

## 主动插件发现

遇到复杂度高的常见游戏功能（寻路/物理/AI/网络/UI/动画等），主动搜索成熟插件方案，评估后推荐。确认采用后用 `/onboard-plugin` 建库接入。

## 验证命令

```bash
npx shellcheck setup/*.sh templates/hooks/*.sh   # shell 脚本语法检查
bash -n setup/deploy.sh                           # 快速语法校验
```

## 编辑规则

- 修改 templates/ 下的文件前，说明改什么、为什么改，等确认
- setup/ 脚本或 hooks 脚本修改后必须跑 `npx shellcheck`
- 新增模板必须有 frontmatter（name, description）
- 不要把本项目特有的配置写进通用模板
