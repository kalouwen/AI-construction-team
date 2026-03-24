# __PROJECT_NAME__

## Autonomous Mode

When working autonomously (autoloop/auto-iterate), NEVER stop to ask questions or seek confirmation. Continue executing until the task is complete or a hard blocker is encountered. If unsure, make the best decision and document it.

When building on previous autoloop output, assume prior work may be broken. Always audit existing code before extending it — check for stub implementations marked as done, wrong proto types, and missing dependencies.

## Project Structure

__PROJECT_STRUCTURE_NOTE__

## Protected Files

__PROTECTED_FILES_NOTE__

## Code Generation Rules

After any proto/codegen step, verify generated files match expected output before proceeding. Never overwrite hand-written compatibility files. Check proto direction matches the target language.

## Build & Test
__BUILD_CMD__          # 构建
__TEST_CMD__           # 测试
__LINT_CMD__           # lint

## Architecture
见 @ARCHITECTURE.md

## Quick Reference
- 分支命名：feature/[desc], fix/[desc], refactor/[desc]
- commit：conventional commits（feat: / fix: / refactor: / docs:）
- 详细编码规范：@.claude/rules/code-style.md
- 安全规范：@.claude/rules/security.md
- Git 工作流：@.claude/rules/git-workflow.md

## What Hooks Handle（你不需要操心）
- 敏感文件泄露检测、危险命令拦截、路径保护
- 编辑后自检、提交前 build check、push 门禁
- 偷懒检测、自动格式化、instincts 提取
- Profile 档位：minimal / standard / strict

## What You Must Do
- 大任务动手前 /pre-review，完成后 /post-review
- 先搜索再编码，不盲改
- 不过度工程，只做被要求的事
- 安全敏感操作前主动提醒用户

## Local Knowledge Bases

__KNOWLEDGE_BASES_NOTE__

> 讨论以上话题时，**先搜本地知识库再回答**，不依赖训练数据。找不到再说明"本地未收录，以下基于训练数据（建议验证）"。

## Boundaries
- 不修改 .env、lock 文件、.git/
- 不在 production 代码写 console.log / print
- 不引入未审查的第三方依赖
- 大任务等用户确认再动手
