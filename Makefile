PYTHON ?= $(shell command -v python3.11 || command -v python3)
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: venv dev-venv install test clean distclean agentic agentic-md cov cov-html bin-wrappers bin-wrappers-check

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
	# Install package editable
	$(PY) -m pip install -e .
	# Ensure wrappers are executable
	chmod +x bin/* || true

install: venv

test: venv
	$(PY) -m unittest -v

cov: venv
	$(PY) -m pip install coverage || true
	PYTHONPATH=. $(PY) -m coverage run -m unittest -q || true
	$(PY) -m coverage combine || true
	$(PY) -m coverage report -m

cov-html: venv
	$(PY) -m pip install coverage || true
	PYTHONPATH=. $(PY) -m coverage run -m unittest -q || true
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
