---
description: 代码风格规范，编辑代码文件时自动加载
paths:
  - "**/*.cs"
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.js"
  - "**/*.py"
  - "**/*.go"
  - "**/*.rs"
---

# 代码风格规范

## 命名
- 类/接口：PascalCase
- 方法/函数：PascalCase（C#）、camelCase（TS/JS）、snake_case（Python/Go/Rust）
- 变量：camelCase（C#/TS/JS）、snake_case（Python/Go/Rust）
- 常量：UPPER_SNAKE_CASE
- 布尔值：is/has/can/should 前缀

## 结构
- 函数 < 50 行，超过就拆
- 参数 < 4 个，超过用对象/结构体
- 嵌套 < 3 层，超过提前 return
- 单一职责：一个函数做一件事

## 导入顺序
1. 外部包（npm/pip 等）
2. 内部模块（绝对路径）
3. 相对路径导入
4. 类型导入（单独分组）

## 错误处理
- async 操作必须有 try/catch
- 用结构化日志，不用 console.log（生产环境）
- 返回有意义的错误信息，包含上下文
- 不要吞掉错误（空 catch 块）

## 注释
- 只在逻辑不自明处加注释
- 不注释"做了什么"，注释"为什么这样做"
- 不留 commented-out code

## 禁止事项
- 不在业务层硬编码配置值 → 抽成配置
- 不用 any 类型（除非注释说明原因）
- 不在循环里做异步操作 → 用 Promise.all / asyncio.gather
- 不直接操作 DOM → 用框架方法
- 不 commit console.log / print 调试语句
