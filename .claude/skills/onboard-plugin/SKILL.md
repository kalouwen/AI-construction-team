---
name: onboard-plugin
description: 插件发现→评估→文档抓取→知识库建立→接入工作流，一条龙
user-invocable: true
---

# /onboard-plugin - 插件知识库一条龙

用户输入 `/onboard-plugin <需求描述或插件名>`，执行以下流水线：

## 阶段 1：需求 → 候选插件（如已指定插件名则跳过）

1. 明确需求：用一句话复述"你要解决的问题是 X"
2. WebSearch 搜索：`Unity Asset Store <需求关键词>`、`<需求> Unity plugin recommended reddit`、`<需求> Unity best asset 2025 2026`
3. 筛选 3-5 个候选插件，输出对比表：

| 插件 | 功能匹配度 | Unity版本兼容 | 维护状态 | 价格 | DOTS支持 | 社区评价 |
|------|-----------|-------------|---------|------|---------|---------|

4. 给出推荐 + 理由，**等用户确认**再继续

## 阶段 2：文档抓取

1. WebSearch 找到插件官方文档 URL
2. 用 WebFetch 抓取文档页面（优先找 llms.txt 或 docs 页面）
3. 如果有多页文档，逐页抓取转为 Markdown
4. 保存到 `C:/a daily difference/<PluginName>/docs/`
5. 添加 YAML frontmatter（title, source, version）

## 阶段 3：源码梳理（如用户已购买/有源码）

1. 用户提供 .unitypackage 或源码路径
2. 识别核心脚本，分析架构（入口类、单例、组件关系）
3. 保存到 `C:/a daily difference/<PluginName>/SourceCode/`
4. 生成架构图（文字版）

## 阶段 4：知识库建立

创建标准目录结构：
```
C:/a daily difference/<PluginName>/
├── CLAUDE.md          # AI速查摘要（<300行）：架构、核心API、常见坑、使用模式
├── README.md          # 用户可读说明
├── docs/              # Markdown 文档
└── SourceCode/        # 源码（如有）
```

CLAUDE.md 必须包含：
- 插件是什么、解决什么问题（1段）
- 核心架构（组件关系图）
- 关键 API 速查表
- 常见坑和解决方案
- 与现有项目的集成点

## 阶段 5：接入工作流

1. 更新 `C:/AI for better/CLAUDE.md` 知识库表，加一行
2. 更新 memory `reference_local_knowledge_bases.md`，加对应条目
3. 告知用户：下次聊到相关话题会自动查询

## 输出格式

每个阶段完成后给用户简短状态更新。全部完成后输出：

```
✅ 插件知识库已建立
- 路径: C:/a daily difference/<PluginName>/
- 文档: X 篇
- 源码: X 个脚本
- 已接入自动查询

下次提到 <相关关键词> 我会自动查这个库。
```
