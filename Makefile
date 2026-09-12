# make verify —— AGENTS.md §2 验证门禁的机械执法层（闭环验证的唯一入口）
# 用法：按目标项目 AGENTS.md §2 登记的命令填充以下变量，然后执行 `make verify`
# §2 登记"无"的项：对应变量填 skip（留空 = 未配置，报错退出，防误配静默放行）
# 增量格式检查（大仓推荐）：make verify CHANGED="$(git diff --name-only)"，仅对改动文件执行 fmt-check
FMT_CHECK_CMD ?= skip
LINT_CMD ?= skip
# 本地优先用项目自带的 .venv（系统 python 常缺依赖）；CI 会显式覆盖此变量
PY ?= $(shell if [ -x .venv/Scripts/python.exe ]; then echo .venv/Scripts/python.exe; \
	elif [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python; fi)
TEST_CMD ?= $(PY) -m pytest code/tests/ -q
BUILD_CMD ?= skip
CHANGED ?=

.PHONY: verify fmt-check lint test build
verify: fmt-check lint test build

fmt-check:
	@if [ -z "$(FMT_CHECK_CMD)" ]; then echo "FMT_CHECK_CMD 未配置（见 enforcement/README.md）"; exit 1; fi
	@if [ "$(FMT_CHECK_CMD)" = "skip" ]; then echo "skip: fmt-check（§2 登记“无”）"; \
	elif [ -n "$(CHANGED)" ]; then $(FMT_CHECK_CMD) $(CHANGED); \
	else $(FMT_CHECK_CMD); fi

lint:
	@if [ -z "$(LINT_CMD)" ]; then echo "LINT_CMD 未配置（见 enforcement/README.md）"; exit 1; fi
	@if [ "$(LINT_CMD)" = "skip" ]; then echo "skip: lint（§2 登记“无”）"; else $(LINT_CMD); fi

test:
	@if [ -z "$(TEST_CMD)" ]; then echo "TEST_CMD 未配置（见 enforcement/README.md）"; exit 1; fi
	@if [ "$(TEST_CMD)" = "skip" ]; then echo "skip: test（§2 登记“无”）"; else $(TEST_CMD); fi

build:
	@if [ "$(BUILD_CMD)" = "skip" ]; then echo "skip: no build configured"; else $(BUILD_CMD); fi
