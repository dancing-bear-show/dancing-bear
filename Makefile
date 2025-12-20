PYTHON ?= $(shell command -v python3.11 || command -v python3)
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: venv dev-venv install test clean distclean agentic agentic-md cov cov-html

venv:
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install -U pip
	$(PY) -m pip install -e .
	# Ensure wrapper is executable for direct runs
	chmod +x bin/mail_assistant bin/mail-assistant bin/mail-assistant-auth bin/assistant || true
	chmod +x bin/phone bin/phone-assistant || true
	chmod +x bin/wifi bin/wifi-assistant || true
	chmod +x bin/apple-music-assistant bin/apple-music-user-token || true
	# Cars-style convenience wrappers
	chmod +x bin/gmail-auth bin/gmail-labels-export bin/gmail-labels-sync || true
	chmod +x bin/gmail-filters-export bin/gmail-filters-sync bin/gmail-filters-impact bin/gmail-filters-sweep || true
	# Outlook wrappers
	chmod +x bin/outlook-auth-device-code bin/outlook-auth-poll bin/outlook-auth-ensure bin/outlook-auth-validate || true
	chmod +x bin/outlook-rules-list bin/outlook-rules-export bin/outlook-rules-plan bin/outlook-rules-sweep bin/outlook-rules-sync bin/outlook-rules-delete || true
	chmod +x bin/outlook-categories-list bin/outlook-categories-export bin/outlook-categories-sync || true
	chmod +x bin/outlook-folders-sync bin/outlook-calendar-add bin/outlook-calendar-add-recurring bin/outlook-calendar-add-from-config || true
	# iOS/Phone wrappers
	chmod +x bin/ios-install-profile bin/ios-setup-device || true
	chmod +x bin/ios-export bin/ios-plan bin/ios-checklist bin/ios-profile-build || true
	chmod +x bin/ios-manifest-create bin/ios-manifest-build-profile bin/ios-manifest-from-device bin/ios-manifest-install || true
	chmod +x bin/ios-analyze bin/ios-auto-folders bin/ios-unused bin/ios-prune || true

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
	@./bin/calendar-assistant --agentic || true
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
