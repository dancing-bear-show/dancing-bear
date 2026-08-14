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

.PHONY: venv dev-venv install test clean distclean agentic agentic-md cov cov-html bin-wrappers bin-wrappers-check deadcode

venv:
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install -U pip
	$(PY) -m pip install -e .
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

test: venv
	$(RUNPY) -m unittest -v

# Fail loudly if imports resolve outside this checkout (see SRC comment above).
.PHONY: check-env
check-env: venv
	@$(RUNPY) -c "import pathlib, sys, core; \
	src = pathlib.Path('$(SRC)').resolve(); \
	got = pathlib.Path(core.__file__).resolve(); \
	sys.exit(0) if src in got.parents else (print(f'ERROR: core resolves to {got}, expected under {src}'), sys.exit(1))"
	@echo "OK: imports resolve to $(SRC)"

# Coverage targets install the [tui] extra: an optional dep that is missing at
# collection time reports its modules as 0% rather than as skipped, which reads
# identically to untested code. Match CI so the numbers mean the same thing.
cov: venv
	$(PY) -m pip install coverage || true
	$(PY) -m pip install -e ".[tui]" || true
	$(RUNPY) -m coverage run -m unittest -q || true
	$(PY) -m coverage combine || true
	$(PY) -m coverage report -m

cov-html: venv
	$(PY) -m pip install coverage || true
	$(PY) -m pip install -e ".[tui]" || true
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

deadcode: venv
	@$(PIP) install -q -e ".[dev]"
	@$(PY) -m vulture --config pyproject.toml
