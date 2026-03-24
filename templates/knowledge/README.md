# 项目知识库模板

此目录包含项目知识库的标准结构。由 `/survey` 调研引擎自动生成到目标工程的 `.claude/knowledge/` 目录下。

## 标准结构

```
.claude/knowledge/
├── profile.json          ← 项目画像（技术栈、结构、依赖）
├── ai-readiness.json     ← AI 友好度评分
├── pain-points.md        ← 痛点清单
├── constraint-map.md     ← 约束映射表（部署模式产出）
└── modules/              ← 模块知识卡片
    ├── {module-name}.md  ← 每个核心模块一张卡片
    └── ...
```

## 生成方式

- `/survey` — 生成 profile.json、ai-readiness.json、modules/、pain-points.md
- `/mode-deploy` — 生成 constraint-map.md
- `/mode-learn` — 增量更新 modules/ 中的知识卡片
- `/mode-skills` — 创建 skill 时补充相关模块知识
