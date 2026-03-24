---
name: docs
description: 在本地知识库中搜索技术文档（Unity/RCC/BD/ClaudeCode）
user-invocable: true
---

# /docs - 知识库统一查询

用户输入 `/docs <查询内容>`，你需要：

1. **识别目标知识库**：根据查询内容自动判断应搜哪个库
   - Unity API/组件/编辑器功能 → UnityDocuments
   - 车辆/驾驶/物理/RCC → RealisticCarController
   - 行为树/NPC/AI行为/BD → BehaviorDesignerPro
   - Claude Code 功能/配置 → ClaudeCodeDocs
   - 不确定 → 多库并行搜索

2. **执行搜索**：派出 `doc-search` agent 搜索，或直接用 Grep/Read 快速查找

3. **返回结果**：
   - 结论先行，一句话回答核心问题
   - 附上来源文件路径（可点击）
   - 如有代码示例，直接给出
   - 如果没找到，明确说"本地知识库未收录，以下基于训练数据（建议验证）"

## 用法示例

```
/docs Transform.position 怎么用
/docs RCC 手刹漂移参数
/docs 行为树条件中断
/docs Claude Code hooks 配置
/docs NavMesh + 行为树巡逻    ← 跨库查询
```

## 知识库路径

| 库 | 路径 |
|----|------|
| Unity | `C:/AI Tools/UnityDocuments/docs/` |
| RCC | `C:/AI Tools/RealisticCarController/` |
| BD | `C:/AI Tools/BehaviorDesignerPro/` |
| CCD | `C:/AI Tools/ClaudeCodeDocs/docs/` |
