---
name: merge
description: 多仓库安全合并技能。处理子模块路径、proto 重新生成、第三方文件保护的正确操作顺序。
---

# Safe Multi-Repo Merge Skill

处理涉及多个仓库/子模块的合并操作，确保正确的操作顺序和安全保护。

## Pre-Merge Checklist

1. **Identify all affected repos** — 列出需要合并的仓库（root, submodules, proto）
2. **Check working tree clean** — 每个仓库 `git status` 确认无未提交变更
3. **Backup current state** — `git stash --include-untracked` 如有未保存工作

## Merge Steps（严格顺序）

### Step 1: Proto/Schema 先行
```
cd <proto_repo>
git pull / git merge <branch>
# 如有冲突 → 手动解决，不用 --theirs
# 运行 codegen → 验证生成文件
```

### Step 2: Server 合并
```
cd <server_repo>
git merge <branch>
# 解决冲突（优先保留功能代码，审慎处理配置）
# 编译验证: go build ./... 或对应命令
# 测试验证: go test ./...
```

### Step 3: Client 合并
```
cd <client_repo>  # 通常是子模块
git merge <branch>
# 解决冲突
# 编译验证
```

### Step 4: Root 仓库更新
```
cd <root>
git add <submodule_paths>
git commit -m "Update submodule refs after merge"
```

## Conflict Resolution Rules

| 文件类型 | 策略 |
|---------|------|
| `Assets/Scripts/3rd/` | **NEVER** use --theirs, 手动审查每一行 |
| Gley / Wwise scripts | **不动**，保留当前版本 |
| Proto generated files | 重新生成，不手动解决冲突 |
| Lock files (package-lock, go.sum) | 删除后重新生成 |
| 配置文件 (.meta, .asset) | 优先保留目标分支版本 |
| 业务代码 | 逐文件审查，理解两边意图后合并 |

## Post-Merge Verification

1. **Proto 一致性**: 生成文件与 .proto 定义匹配
2. **编译通过**: Server + Client 都编译通过
3. **测试通过**: 全量测试无回归
4. **子模块引用**: Root 仓库的子模块指针已更新
5. **Git status**: 所有仓库工作区干净

## Abort Criteria

遇到以下情况立即停止，不要继续：
- 第三方库文件冲突无法安全解决
- Proto codegen 结果与手写兼容层冲突
- 合并后编译失败且 3 次修复未果
- 子模块循环引用
