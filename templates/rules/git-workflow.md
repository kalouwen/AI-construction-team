---
description: Git 工作流规范，执行 git 命令时自动加载
paths:
  - "**"
---

# Git 工作流规范

## 分支
- `main` / `master`：生产分支，不直接提交
- `feature/[desc]`：新功能
- `fix/[desc]`：Bug 修复
- `refactor/[desc]`：重构

## Commit
- 格式：`type(scope): description`
- type：feat / fix / docs / style / refactor / perf / test / chore / ci / build / revert
- description：动词开头，说清"做了什么"
- 每个 commit 只做一件事

## PR
- 标题 < 70 字符
- 描述包含：改了什么、为什么改、怎么测
- push 前必须通过 /review-pr
