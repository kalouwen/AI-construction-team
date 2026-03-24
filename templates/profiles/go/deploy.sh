# Profile: Go 项目
# 自动加载条件：LANGUAGE=go
# 特点：快速编译、go test 内置、无需外部 test runner

ENABLE_PUSH_GATE="y"
ENABLE_FORMAT="y"          # gofmt / goimports
ENABLE_BUILD_CHECK="y"     # go build 很快，适合每次 commit 前跑
ENABLE_GIT_HOOKS="y"
ENABLE_CONFIG_FILES="y"
ENABLE_ACTIONS="y"
ENABLE_COMMUNITY="n"
ENABLE_TEST_SIGNAL="y"
ENABLE_PERF_SIGNAL="n"
ENABLE_REWARD_LOOP="y"

PROFILE_PROTECTED_PATHS="vendor/|go\.sum"
PROFILE_FROZEN_TESTS="*_test.go|testdata/"
