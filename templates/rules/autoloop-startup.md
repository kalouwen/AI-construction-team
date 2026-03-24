# Autoloop Session Startup Protocol

> 所有自动循环会话（autoloop/auto-iterate）启动时必须执行以下三步，在任何新工作之前完成。

## 1. Pre-Flight Audit（2 分钟，不可跳过）

Before building anything new, audit all files modified in the last session:
- Check for stub implementations marked as complete
- Check proto type mismatches between Go server and C# client
- Check missing dependencies (imports, packages, references)
- Check commented-out code that should be real implementation
- List EVERY issue found → fix all before proceeding

## 2. MCP Connection Check（如项目使用 MCP）

Check all MCP server connections and confirm they respond.
If any are disconnected → log which ones → mark MCP-dependent features as blocked.
Do NOT attempt MCP work with broken connections.

## 3. Phase Gate（每个 feature/phase 完成后，硬门禁）

Work in phases. After EACH phase:
1. Compile BOTH server and client
2. Run ALL tests
3. Fix any failures before moving to the next phase

**NEVER proceed to phase N+1 with failing tests in phase N.**
