# Profile: Node.js / TypeScript / JavaScript 项目
# 自动加载条件：LANGUAGE=node
# 特点：husky、全套 CI、格式化

ENABLE_PUSH_GATE="y"
ENABLE_FORMAT="y"
ENABLE_BUILD_CHECK="y"
ENABLE_GIT_HOOKS="y"       # → husky（随仓库传递）
ENABLE_CONFIG_FILES="y"
ENABLE_ACTIONS="y"
ENABLE_COMMUNITY="y"
ENABLE_TEST_SIGNAL="y"
ENABLE_PERF_SIGNAL="n"     # Web 性能监控另有专门工具
ENABLE_REWARD_LOOP="n"     # 需要 perf_signal 才能启用

PROFILE_PROTECTED_PATHS="node_modules/|\.next/|dist/|build/"
PROFILE_FROZEN_TESTS="*.test.ts|*.test.js|*.spec.ts|*.spec.js|__tests__/"
