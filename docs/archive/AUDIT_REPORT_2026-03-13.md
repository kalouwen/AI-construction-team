# 项目扫描审计报告

**日期**：2026-03-13
**扫描范围**：GTA、small game、team agent kailuo
**目的**：发现问题 → 反哺优化 Harness

---

## 待批注区（未确认项）

> 每条格式：`[ ]` 待批注 / `[Y]` 做 / `[N]` 不做 / `[?]` 要聊聊
> 批注完告诉我，我来更新这个文档。

---

### 一、跨项目共性问题（最有 Harness 价值）

#### H1. settings 权限过宽 — 三个项目都有
- [Y ] **GTA**：允许 `Bash(rm *)`、`Bash(powershell *)`、`Bash(taskkill *)`，deny 只有2条
- [Y ] **small game**：`Bash(bash:*)`、`Bash(do:*)`、`Bash(node:*)` 等于无限制，**无 deny 列表**
- [ Y] **team agent kailuo**：完全没有 `.claude/` 目录，零防护
- **Harness 建议**：deploy.sh 部署时自动生成 deny 黑名单（危险命令 + 敏感文件），不依赖各项目手动配置

#### H2. 密钥/敏感信息检测不完整
- [Y] **GTA** hook 只检测 `password|secret|apikey|api_key`，遗漏 `token`、`AUTH_KEY`、AWS Key 等
- [y] **GTA** 配置文件内网 IP `10.10.10.33` 硬编码（MongoDB/Redis），`.mcp.json` 含内网地址 `10.10.8.102`
- [y] **small game** 无任何密钥检测机制
- [y] **team agent kailuo** `.env.example` 存在但无启动时验证 API key 是否设置
- **Harness 建议**：pre-bash-guard.sh 扩展敏感模式列表；新增 git staged 文件内容扫描（不只看命令字符串）

#### H3. 错误处理模式薄弱
- [y] **small game**：JSON.parse 无 catch、全局对象 `window.game` 无 null 检查
- [y] **team agent kailuo**：`_safe_read_json` 所有 fallback 失败后返回 None（静默失败）、JSON 解析错误被 `continue` 跳过无日志
- [y] **GTA**：post-edit-verify 自检规则仅警告不阻止
- **Harness 建议**：coding-standards skill 加入"错误处理必须显式"规则

#### H4. CLAUDE.md 规范不足
- [y] **small game**：仅3行，缺安全策略、代码风格、模块设计
- [y] **team agent kailuo**：有工作流定义但无权限管理（谁能改 prompt、谁能 rollback）
- [y] **GTA**：相对完善但跨项目指导仅高层概述
- **Harness 建议**：CLAUDE.template.md 增加必填章节检查清单

---

### 二、GTA 项目（/c/GTA）

#### G1. 🔴 配置文件硬编码内网地址
- [?] `P1GoServer/bin/config.toml`：MongoDB/Redis 用 `10.10.10.33`
- [?] `.mcp.json`：code-rag 服务 `10.10.8.102:8321`
- 建议：改用环境变量，`.toml` 加入 `.gitignore`，提供 `.toml.example`

#### G2. 🟠 目录守卫 Hook 覆盖不全
- [y] `pre-edit-guard.js` 只拦截 `.go` 自动生成文件，Unity `Config/Gen/*.cs` 未保护
- [y] P1GoServer 子项目没有自己的 hooks，完全依赖工作区级别

#### G3. 🟠 密钥检测正则不完整
- [y] `pre-commit-verify.js` 遗漏 `token`、`access_key`、云服务密钥格式
- 已在 H2 中提到，这里标记具体文件

#### G4. 🟡 编辑后自检仅警告不阻止
- [y] `post-edit-verify.js` 检测到 `Debug.Log` 等违规只输出 WARNING
- 建议：关键规则升级为 CRITICAL（阻止提交）

#### G5. 🔵 值得借鉴的三重保护（参考价值）
- 第一层：权限白名单（settings.json 180+ 项显式允许）
- 第二层：目录守卫（pre-edit-guard.js 保护框架/第三方/自动生成代码）
- 第三层：编辑后自检 + 提交门禁（post-edit-verify.js + pre-commit-verify.js）
- commit message 格式检查：`<type>(scope) description`
- **我们 Harness 目前缺第二层和第三层，待优化项已记录**

---

### 三、small game 项目（/c/small game）

#### S1. 🔴 多处 XSS 风险
- [y] `js/visual-effects.js`：`banner.innerHTML` 使用未转义的 `icon/title/body`
- [y] `js/main.js:425`：日志条目 `text` 和 `level` 未转义直接拼 innerHTML
- [y] `js/ui.js` 多处：NPC 信息面板 innerHTML 赋值
- 建议：提取全局 `escapeHtml()` 工具函数，所有 innerHTML 强制使用

#### S2. 🔴 settings 权限几乎无限制
- [y] `settings.local.json`：`Bash(bash:*)`、`Bash(node:*)`、`Bash(do:*)` 等于放开一切
- [y] `settings.json`：`Read(*)` 允许读取所有文件
- [y] 无 deny 列表
- 已在 H1 中提到，这里标记具体严重性

#### S3. 🟠 全局对象污染
- [y] 27个 JS 文件广泛使用 `window.game`、`window.npcManager` 等全局单例
- [y] 无模块导入体系，依赖关系不可追踪
- 建议：长期迁移 ES6 modules；短期加 null 检查

#### S4. 🟡 文件超长 + 魔法值
- [y] `events.js` 11748行（规则上限500行的23倍）
- [y] `config.js` 2525行、`social-chains.js` 4569行
- [y] 数百个硬编码数值散布各文件（冷却时间、概率、速度等）
- 建议：按领域拆分文件；常量集中到 config

#### S5. 🟡 缺少类型定义
- [y] 纯 JS 无 TypeScript，NPC 对象 200+ 属性无类型约束
- 建议：至少加 JSDoc 或 `.d.ts` 类型声明

---

### 四、team agent kailuo 项目（/c/team agent kailuo）

#### T1. 🔴 API 密钥无启动时验证
- [y] `src/config.py:100-102`：未检查 `ANTHROPIC_API_KEY` 环境变量是否存在
- 建议：启动时 `if not key: raise RuntimeError(...)`

#### T2. 🟠 完全没有 .claude/ 配置
- [y] 无 hooks、无 skills、无 settings.json
- [y] CLAUDE.md 有工作流但无权限管理规则
- 建议：用 deploy.sh 部署基础 Harness

#### T3. 🟡 JSON 解析逻辑三处重复
- [y] `critic_agent.py`、`meta_agent.py`、`explorer_agent.py` 都有去 markdown + 解析 JSON 的相同代码
- 建议：提取为 `response_parser.py` 共享函数

#### T4. 🟡 异常处理不完整
- [y] `state_manager.py:223-240`：所有 fallback 失败后返回 None（静默失败）
- [y] `critic_agent.py:54-64`：issue 解析失败用 `continue` 跳过无日志
- 建议：失败时显式 raise 或 log warning

#### T5. 🔵 模型名硬编码 + 依赖版本无上限
- [y] `config.py`：`claude-haiku-4-5-20251001` 硬编码，不能通过环境变量切换
- [y] `requirements.txt`：`pydantic>=2.0.0` 无上限，3.x 破坏性更新会炸
- 建议：模型名走环境变量；依赖加版本上限

---

## 已确认区（全部 Y，G1 标 N — 不改项目文件，由 Harness 覆盖）

全部通过，核心方向：**不动各项目文件，只迭代 Harness 自身，部署后自动覆盖这些问题。**

---

## Harness 优化待办汇总

从本次扫描提炼出的 Harness 改进点（等你批注完上面的问题后，再确定优先级）：

1. deploy.sh 自动生成 deny 黑名单（解决 H1）
2. pre-bash-guard.sh 扩展敏感模式 + git staged 内容扫描（解决 H2）
3. coding-standards 加入错误处理规则（解决 H3）
4. CLAUDE.template.md 增加必填章节检查（解决 H4）
5. 新增目录守卫 Hook 模板（参考 GTA G5 第二层）
6. 新增编辑后自检 Hook 模板（参考 GTA G5 第三层）
7. 新增 commit message 格式检查（参考 GTA G5）
