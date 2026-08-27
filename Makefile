PYTHON ?= $(shell command -v python3.11 || command -v python3)
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

# Absolute path to THIS checkout's src/. Pinned explicitly because an inherited
# PYTHONPATH (from direnv in another checkout, or an activated venv belonging to
# the main repo) otherwise takes precedence over the editable install's .pth and
# silently resolves imports to that other tree. In a worktree that means tests
# pass against unmodified source — a false green. Always run tests via $(RUNPY).
SRC := $(CURDIR)/src
RUNPY := PYTHONPATH=$(SRC) $(PY)

.PHONY: venv dev-venv install test clean distclean agentic agentic-md cov cov-html bin-wrappers bin-wrappers-check deadcode typecheck

venv:
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install -U pip
	# [tui] pulls textual. `make test` depends on this target, and the telemetry
	# TUI tests import textual directly — a plain `-e .` makes them fail on a
	# fresh clone, and makes coverage silently report those modules as 0%.
	# [slides] pulls python-pptx for the same reason: tests/slides_tests imports
	# it directly, so omitting it fails 603 tests on a fresh clone.
	$(PY) -m pip install -e ".[tui,slides]"
	# Ensure wrappers are executable
	chmod +x bin/* 2>/dev/null || true

dev-venv:
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install -U pip setuptools wheel
	# Dev deps (pytest etc.)
	$(PY) -m pip install -r requirements-dev.txt || true
	# Install package editable with the dev extra. [dev] includes textual so the
	# telemetry TUI modules are importable locally and coverage matches CI —
	# a plain `-e .` leaves them unimportable and silently at 0%.
	$(PY) -m pip install -e ".[dev]"
	# Ensure wrappers are executable
	chmod +x bin/* || true

install: venv

test: venv check-tests
	$(RUNPY) -m unittest -v

# Lint with the same ruff build CI uses (qlty's pinned tool cache) rather than
# whatever `ruff` happens to be on PATH — there usually isn't one, and a bare
# `ruff check` then fails as "command not found" or, worse, runs a drifted
# version. bin/ruff-resolve.sh handles the lookup and explains the fix if the
# cache is cold. Note `qlty check` from a worktree under .claude/ scans zero
# files and reports "No issues", so it is not a substitute for this target.
.PHONY: lint
lint:
	@bin/ruff-resolve.sh check $(SRC) tests bin

.PHONY: lint-fix
lint-fix:
	@bin/ruff-resolve.sh check --fix $(SRC) tests bin

# A test directory without __init__.py is skipped silently by `unittest discover`,
# so its tests never run and the module it covers reports 0% as if untested. Same
# outcome when the __init__.py is gitignored: it passes locally and never reaches
# CI. Both have happened here — guard runs before the suite so the failure is loud.
.PHONY: check-tests
check-tests:
	@$(PYTHON) bin/check_test_discovery.py

# Fail loudly if imports resolve outside this checkout (see SRC comment above).
.PHONY: check-env
check-env: venv
	@$(RUNPY) -c "import pathlib, sys, core; \
	src = pathlib.Path('$(SRC)').resolve(); \
	got = pathlib.Path(core.__file__).resolve(); \
	sys.exit(0) if src in got.parents else (print(f'ERROR: core resolves to {got}, expected under {src}'), sys.exit(1))"
	@echo "OK: imports resolve to $(SRC)"
	@$(RUNPY) -c "import sys; \
[print(f'OK: PyYAML importable under {sys.executable}')] if [__import__('yaml')] else None" \
	2>/dev/null || (echo "ERROR: PyYAML not importable under $$($(RUNPY) -c 'import sys; print(sys.executable)') — run make venv" >&2; exit 1)

# The [tui] extra comes from the venv target above. An optional dep missing at
# collection time reports its modules as 0% rather than as skipped, which reads
# identically to untested code — so coverage must match CI's install.
cov: venv check-tests
	$(PY) -m pip install coverage || true
	$(RUNPY) -m coverage run -m unittest -q || true
	$(PY) -m coverage combine || true
	$(PY) -m coverage report -m

cov-html: venv
	$(PY) -m pip install coverage || true
	$(RUNPY) -m coverage run -m unittest -q || true
	$(PY) -m coverage combine || true
	$(PY) -m coverage html && echo "Open ./htmlcov/index.html"

clean:
	rm -rf $(VENV)

distclean: clean
	# Ephemeral outputs and caches
	rm -rf _out logs htmlcov .coverage .coverage.*
	# Python caches and test artifacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} + || true
	find . -type d -name .pytest_cache -prune -exec rm -rf {} + || true
	# Local tooling caches (safe to purge)
	rm -rf .mypy_cache .cache .direnv || true
	# Packaging metadata
	rm -rf *.egg-info personal_assistants.egg-info || true
	@echo "Distclean complete."

agentic:
	@echo "== Mail Assistant Agentic =="
	@./bin/mail-assistant --agentic || ./bin/mail_assistant --agentic || true
	@echo
	@echo "== Calendar Assistant Agentic =="
	@./bin/calendar --agentic || ./bin/calendar-assistant --agentic || true
	@echo
	@echo "== Maker Agentic =="
	@./bin/llm-maker agentic --stdout || true

agentic-md:
	@mkdir -p .llm
	@echo "Writing Mail Assistant capsules to .llm/…"
	@./bin/llm agentic --write .llm/AGENTIC.md || true
	@./bin/llm domain-map --write .llm/DOMAIN_MAP.md || true
	@echo "Writing Calendar Assistant capsules to .llm/…"
	@./bin/llm-calendar agentic --write .llm/AGENTIC_CALENDAR.md || true
	@./bin/llm-calendar domain-map --write .llm/DOMAIN_MAP_CALENDAR.md || true
	@echo "Writing Maker capsules to .llm/…"
	@./bin/llm-maker agentic --write .llm/AGENTIC_MAKER.md || true
	@./bin/llm-maker domain-map --write .llm/DOMAIN_MAP_MAKER.md || true
	@echo "Done. Files:"
	@ls -1 .llm/AGENTIC*.md .llm/DOMAIN_MAP*.md 2>/dev/null || true

bin-wrappers:
	@echo "Regenerating bin/ wrappers from _wrappers.yaml..."
	@$(PYTHON) bin/_gen_wrappers.py
	@echo "Done."

bin-wrappers-check:
	@$(PYTHON) bin/_gen_wrappers.py --check

# The .claude/hooks guard suites, for running them directly.
#
# `make test` and CI already cover these through tests/infra/test_guard_hooks.py,
# which shells out to the same scripts and is picked up by unittest discovery. This
# target exists for iterating on a hook without paying for the whole Python suite --
# it is a convenience, not the enforcement point. Adding a new *.test.sh needs no
# change here or in CI; the wrapper discovers the directory and fails if a suite on
# disk is not wired in.
.PHONY: hooks-test
hooks-test:
	@for s in .claude/hooks/tests/*.test.sh; do \
		echo "== $$s"; bash "$$s" || exit 1; \
	done

deadcode: venv
	@$(PIP) install -q -e ".[dev]"
	@$(PY) -m vulture --config pyproject.toml

# Report-only, like deadcode: prints findings and always exits 0. CI does not
# run mypy, so a non-zero exit here would fail local runs on a standard nobody
# enforces. Scope it with TYPECHECK_PATHS to focus on one package:
#   make typecheck TYPECHECK_PATHS=src/core
# (Deliberately not SRC — that is the absolute path pinned onto PYTHONPATH for
# test resolution, and overriding it would repoint imports at a partial tree.)
TYPECHECK_PATHS ?= src
.PHONY: typecheck
typecheck: venv
	@$(PIP) install -q -e ".[dev]"
	@$(PY) -m mypy $(TYPECHECK_PATHS) --ignore-missing-imports || true
