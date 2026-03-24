# 多仓库支持完整解决方案

> 来源：GTA 服装系统实战模拟 → 发现 4 CRITICAL + 4 HIGH 问题 → 审查 agent 发现 13 个缺口 → 本方案

## 核心问题

模板假设"一个项目 = 一个 git 仓库"。GTA 是 4 个独立仓库。

| 仓库 | Git 根 | 构建目录 | 语言 | 验证方式 |
|------|--------|---------|------|---------|
| client | C:\GTAaitest\freelifeclient | 同上 | C#/Unity | MCP / batchmode |
| server | C:\GTA\P1GoServer | P1GoServer/common | Go | shell (go test) |
| proto | C:\GTA\old_proto | 同上 | 自定义 | 间接（通过 client+server） |
| old_server | C:\GTA\server_old | — | Rust | 不触碰 |

## 实现策略

**Phase 1**: GTA 专用适配（最小可用）
**Phase 2**: 抽象为通用 manifest 系统（验证后）

## Phase 1: 需要创建/修改的文件

### 新增 (2 文件)

#### 1. `templates/reward-loop/project-manifest.template.yaml` ✅ 已创建
项目多仓库定义模板。包含：
- 每个仓库的 git_root / work_dir / commit_scope / verify / protected
- codegen 级联步骤
- 跨仓库一致性检查规则
- MCP 配置
- AI agent 提示注入模板

#### 2. `templates/reward-loop/manifest.py` — 待创建
统一仓库操作模块。所有工具通过此模块操作仓库，不再直接调 git。

核心 API:
```python
class ProjectManifest:
    @classmethod
    def load(cls, path) -> 'ProjectManifest':
        """加载 manifest。不存在时从单 project_dir 构造合成 manifest（向后兼容）。"""

    def save_state(self) -> dict:
        """记录所有仓库的 HEAD SHA。"""

    def create_branches(self, branch_name, repos=None):
        """在指定仓库创建分支。repos=None 时只在有 commit_scope 的仓库创建。"""

    def rollback(self, saved_state):
        """回滚所有仓库到 saved_state。用 git reset --hard + git clean -fd。"""

    def run_verify(self, repo_name, check_type='compile') -> VerifyResult:
        """执行验证。dispatch: shell → subprocess / mcp → 返回指令让 AI 执行 / skip。"""

    def run_codegen_cascade(self, changed_files) -> bool:
        """检查 changed_files 是否触发 codegen，是则执行级联步骤。"""

    def run_cross_checks(self) -> list:
        """执行跨仓库一致性检查（enum_sync 等）。"""

    def get_repo_for_file(self, abs_path) -> str:
        """文件路径 → 仓库名。AI agent 用这个决定 commit 到哪个仓库。"""

    def build_agent_prompt_context(self) -> str:
        """生成注入 AI prompt 的仓库映射和验证指令。"""
```

**关键设计决策**:
- MCP 验证不在 manifest.py 中直接执行（因为 Python 无法调 MCP 工具）
- manifest.py 的 `run_verify(method=mcp)` 返回一个 `VerifyResult(status="NEEDS_MCP", instruction="call mcp__coplay-mcp__check_compile_errors")`
- driver.py 收到 NEEDS_MCP 结果后，将指令注入到 claude -p 的 prompt 中让 AI agent 执行
- 如果 MCP 健康检查失败且 on_mcp_fail=block → 整轮标记 BLOCKED

### 修改 (6 文件)

#### 3. `templates/reward-loop/driver.py`

改动:
- 导入 manifest.py
- 接受 `--manifest <path>` 参数
- 每轮开始前: `manifest.save_state()`
- 创建分支: `manifest.create_branches(f"evolve/round-{round_num}")`
- AI 执行前: 将 `manifest.build_agent_prompt_context()` 注入 prompt
- 失败回滚: `manifest.rollback(saved_state)` 替代单仓库 `git checkout/branch -D`
- 成功合并: 在每个有变更的仓库中 squash merge
- 新增 Step 4.5: `manifest.run_codegen_cascade(changed_files)` — AI 执行后、guardrail 前
- MCP 健康检查: 启动时 + 每 N 轮重检

#### 4. `templates/reward-loop/prompt.py`

改动:
- 接受 manifest 对象
- `build_prompt()` 中注入仓库映射（来自 `manifest.build_agent_prompt_context()`）
- target_files 前缀仓库名: `server:clothing/slot.go` 而非裸路径
- 冻结边界 per-repo: 每个仓库独立列出 protected 路径

#### 5. `templates/reward-loop/guardrail.py`

改动:
- 接受 manifest 对象
- Per-repo diff: 对每个仓库分别执行 `git diff`
- Per-repo frozen check: 用仓库各自的 protected 列表
- Aggregate limits: 所有仓库的 files_changed/insertions/deletions 总和
- 新增: cross_repo checks (从 manifest 读取 enum_sync 规则)
- commit_scope 检查: AI 改动是否超出仓库的 commit_scope

#### 6. `templates/reward-loop/preflight.py`

改动:
- 接受 `--manifest <path>` 参数
- enum_sync: 从 manifest.cross_repo.enum_sync 读取跨仓库规则
- build_baseline: 对每个仓库分别执行 verify.compile 和 verify.test
- protected_dirs: 从 manifest per-repo protected 读取

#### 7. `templates/reward-loop/observe.py`

改动:
- Per-repo 状态报告: 每个仓库的最近提交、变更文件、测试状态
- MCP 状态: 上次检查结果 + 当前可用性

#### 8. `templates/skills/autoloop/SKILL.md`

新增章节:

```
## Multi-Repo Protocol（多仓库项目适用）

如果项目有 project-manifest.yaml:

### 仓库感知
- 读 manifest，了解每个仓库的路径、语言、验证方式
- 每次编辑文件时，确认文件属于哪个仓库
- commit 时 cd 到该仓库的 git_root 再操作

### 跨仓库验证
- 改了 Go 代码 → 从 server.work_dir 跑 go test
- 改了 C# 代码 → 用 MCP check_compile_errors（MCP 不可用时 STOP）
- 改了 proto → 执行 codegen cascade → 验证两端

### MCP 降级
- MCP 可用 → 正常验证 C# 编译
- MCP 不可用 + on_mcp_fail=block → 停止 C# 相关工作，只做 Go 端
- MCP 不可用 + on_mcp_fail=skip_with_warning → 继续但在 self-heal-log 中标记未验证
- 绝不静默跳过验证后声称"完成"

### Codegen Cascade
proto 文件变更后必须执行:
1. 同步 submodule (如有)
2. 运行 codegen 命令
3. 提交生成的代码到 client 和 server 仓库
4. 验证两端都能编译
```

## Phase 2: 泛化（Phase 1 在 GTA 上验证通过后）

- manifest.py 提取为独立包
- deploy.sh 集成: `analyze-project.py` 检测多仓库结构 → 自动生成 manifest
- 模板变量替换: manifest.yaml 中的 `{client.git_root}` 等占位符
- 更多 MCP 验证方式: Unity Test Runner、场景检查等

## 实现顺序（依赖关系）

```
manifest.py (核心，无依赖)
     │
     ├→ preflight.py (改：读 manifest 做跨仓库检查)
     ├→ driver.py (改：多仓库 branch/rollback/verify)
     │    ├→ prompt.py (改：注入仓库映射)
     │    ├→ guardrail.py (改：per-repo diff + cross-repo checks)
     │    └→ observe.py (改：per-repo 状态)
     └→ autoloop SKILL.md (改：Multi-Repo Protocol)
```

**manifest.py 必须先做**。其他改动都依赖它。

## 风险评估

| 风险 | 缓解 |
|------|------|
| manifest.py 的 rollback 在某个仓库失败 | 先检查 dirty state，失败时 force reset + 记录 |
| MCP 频繁断连导致大量 BLOCKED | recheck_every_n_rounds 限制检查频率；区分"暂时断"和"完全不可用" |
| codegen 命令不确定（generate.exe? go generate?） | manifest 预留 `cmd: null`，部署时由人填写 |
| 跨仓库 enum 归一化不准 | 用项目特定的 pattern，不用通用正则 |
| claude -p 无法原生跨目录操作 | prompt 中显式写明每个仓库的绝对路径和 cd 指令 |

## 对 GTA 服装系统的覆盖度预期

| 组件 | 部署前 | 部署后 |
|------|--------|--------|
| Go 服务端验证 | ❌ 路径错 | ✅ manifest 声明正确的 work_dir |
| C# 客户端验证 | ❌ 无命令行编译 | ✅ MCP 验证 + block-on-fail |
| Proto 一致性 | ❌ 非标准 protobuf | ✅ codegen cascade + cross_repo checks |
| 枚举同步 | ❌ 跨仓库 | ✅ manifest.cross_repo.enum_sync |
| 跨仓库回滚 | ❌ 只管一个仓库 | ✅ manifest.rollback(saved_state) |
| 增量检查点 | ✅ Go 可用 | ✅ Go + C#(MCP) 都可用 |
| Self-heal | 🟡 通用模式 | 🟡 需要补 GTA 专用 patterns（Phase 2） |
| Parallel build | ❌ 假设单仓库 | 🟡 需要改 parallel-driver（Phase 2） |
