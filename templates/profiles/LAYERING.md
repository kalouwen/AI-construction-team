# 配置分层架构

## 三层模型

```
Layer 1: 通用基础          templates/reward-loop/         所有项目共享，可升级
Layer 2: 语言 Profile      templates/profiles/{lang}/     按语言预设，可选覆盖
Layer 3: 项目实例          target/.claude/project/         项目独有，永不被覆盖
```

## 合并规则

| 字段类型 | 合并方式 | 示例 |
|----------|---------|------|
| 列表（patterns, protected） | **追加** L1 + L2 + L3 | 通用 6 模式 + Unity 4 模式 + GTA 2 模式 = 12 模式 |
| 标量（method, on_mcp_fail） | **L3 > L2 > L1** 后者覆盖前者 | L1 默认 block → L2 Unity 保持 block → L3 GTA 改为 skip_with_warning |
| 字典（verify, settings） | **深度合并** 同键覆盖，新键追加 | L1 无 mcp_tool → L2 填 check_compile_errors → L3 不改 |

## 运行时合并示例

### friction-patterns.yaml

```yaml
# 最终合并结果（自动生成，不要手动编辑此文件）
# 来源: L1(templates/reward-loop) + L2(profiles/unity) + L3(.claude/project)

_layer_info:
  L1: "templates/reward-loop/friction-patterns.yaml"
  L2: "templates/profiles/unity/friction.yaml"
  L3: ".claude/project/friction.yaml"
  merged_at: "2026-03-20T12:00:00Z"

patterns:
  # --- L1: 通用 (6 patterns) ---
  - id: api-signature-mismatch      # from L1
  - id: missing-import-or-dependency # from L1
  - id: circular-dependency          # from L1
  - id: type-mismatch                # from L1
  - id: tool-not-found               # from L1
  - id: permission-or-lock           # from L1

  # --- L2: Unity Profile (4 patterns) ---
  - id: unity-missing-reference      # from L2
  - id: unity-serialization-error    # from L2
  - id: unity-mcp-disconnected       # from L2
  - id: unity-asmdef-circular        # from L2

  # --- L3: GTA 项目特有 (2 patterns) ---
  - id: gta-slot-enum-mismatch       # from L3
  - id: gta-custom-proto-stale       # from L3
```

### 同一个 pattern id 在多层出现时

- **L3 覆盖 L2 覆盖 L1**：项目可以修改通用模式的 fix_steps
- 用 `override_id: xxx` 声明覆盖而非追加
- 用 `disable_id: xxx` 声明禁用某个上层模式

## 目录结构

### 部署前（templates/）
```
templates/
├── reward-loop/
│   ├── friction-patterns.yaml      ← L1: 通用模式
│   ├── preflight.template.yaml     ← L1: 通用预检
│   ├── project-manifest.template.yaml ← L1: 清单模板
│   └── *.py                        ← L1: 工具脚本
├── profiles/
│   ├── LAYERING.md                 ← 本文件
│   ├── unity/
│   │   ├── deploy.sh               ← 部署开关
│   │   └── friction.yaml           ← L2: Unity 摩擦模式
│   ├── go/
│   │   ├── deploy.sh
│   │   └── friction.yaml           ← L2: Go 摩擦模式
│   ├── node/  ...
│   └── python/ ...
```

### 部署后（目标项目）
```
target_project/
├── .reward-loop/
│   ├── friction-patterns.yaml      ← 合并结果（L1+L2+L3）
│   ├── preflight.yaml              ← 合并结果
│   ├── project-manifest.yaml       ← L3 only（纯项目特有）
│   ├── driver.py, self-heal.py ... ← L1 复制（可升级）
│   └── _layer_sources.json         ← 记录每个文件的来源层
├── .claude/
│   └── project/                    ← L3: 项目专有覆盖
│       ├── friction.yaml           ← 只含项目独有的模式
│       ├── preflight.yaml          ← 只含项目独有的检查
│       └── manifest.yaml           ← → .reward-loop/project-manifest.yaml
```

## deploy.sh 合并流程

```bash
# 1. 检测语言
LANG=$(detect-project.sh)   # → "unity", "go", "node", "python"

# 2. 复制 L1（通用基础）
cp templates/reward-loop/*.py  target/.reward-loop/
cp templates/reward-loop/*.yaml target/.reward-loop/

# 3. 合并 L2（语言 Profile）
python merge-layers.py \
  --base templates/reward-loop/friction-patterns.yaml \
  --profile templates/profiles/$LANG/friction.yaml \
  --output target/.reward-loop/friction-patterns.yaml

# 4. 如果 L3 存在（项目已有定制），合并进去
if [ -f target/.claude/project/friction.yaml ]; then
  python merge-layers.py \
    --base target/.reward-loop/friction-patterns.yaml \
    --override target/.claude/project/friction.yaml \
    --output target/.reward-loop/friction-patterns.yaml
fi

# 5. 记录来源
echo '{"friction-patterns": {"L1": "...", "L2": "...", "L3": "..."}}' \
  > target/.reward-loop/_layer_sources.json
```

## 升级流程

```bash
# 只升级 L1 和 L2，不碰 L3
# 1. 更新 L1
cp templates/reward-loop/*.py target/.reward-loop/
# 2. 重新合并（L1 新版 + L2 + L3 不变）
python merge-layers.py --base L1 --profile L2 --override L3 --output merged
```

## 关键原则

1. **L3 永不被自动覆盖** — 项目定制是人工写的，只有人能改
2. **L1 可以安全升级** — 通用模式改进后重新合并，L3 覆盖仍然生效
3. **每个配置文件记录来源** — `_layer_info` 字段说明每条规则来自哪层
4. **profile 是可选的** — 没有对应语言的 profile 也能工作（直接 L1+L3）
5. **合并结果是可重现的** — 给定 L1+L2+L3，输出永远一样
