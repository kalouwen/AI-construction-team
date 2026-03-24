# Profile: Python 项目
# 自动加载条件：LANGUAGE=python
# 特点：pre-commit 框架、pytest、全套 CI

ENABLE_PUSH_GATE="y"
ENABLE_FORMAT="y"
ENABLE_BUILD_CHECK="n"
ENABLE_GIT_HOOKS="y"       # → pre-commit 框架（随仓库传递）
ENABLE_CONFIG_FILES="y"
ENABLE_ACTIONS="y"
ENABLE_COMMUNITY="y"
ENABLE_TEST_SIGNAL="y"
ENABLE_PERF_SIGNAL="n"
ENABLE_REWARD_LOOP="y"

PROFILE_PROTECTED_PATHS="\.venv/|venv/|__pycache__/|\.pytest_cache/|dist/"
PROFILE_FROZEN_TESTS="test_*.py|*_test.py|tests/|conftest.py"
