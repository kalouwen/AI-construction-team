# Profile: Unity 游戏项目
# 自动加载条件：FRAMEWORK=unity
# 特点：无 npm/pip，性能信号优先，CI 需要特殊 runner 不自动配

ENABLE_PUSH_GATE="y"
ENABLE_FORMAT="n"          # Unity 没有 prettier/black
ENABLE_BUILD_CHECK="n"     # Unity build 太慢，不适合每次 commit 前跑
ENABLE_GIT_HOOKS="y"
ENABLE_CONFIG_FILES="y"
ENABLE_ACTIONS="n"         # Unity CI 需要 self-hosted runner，不自动配
ENABLE_COMMUNITY="n"
ENABLE_TEST_SIGNAL="y"
ENABLE_PERF_SIGNAL="y"     # 游戏项目必须监控性能
ENABLE_REWARD_LOOP="y"

# 额外保护路径（追加到 guard-patterns.conf）
PROFILE_PROTECTED_PATHS="Library/|Packages/|ProjectSettings/|UserSettings/"

# signals.yaml 冻结边界（Unity 测试文件命名规范）
PROFILE_FROZEN_TESTS="*.Test.cs|*Tests.cs|Assets/Tests/|EditMode/|PlayMode/"
