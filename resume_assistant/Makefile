VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: venv deps test sample-docx clean distclean deepclean tidy-data tidy-out tidy-temp exp-export purge-temp

venv:
	python3 -m venv $(VENV)

deps: venv
	$(PIP) install -q python-docx pyyaml pdfminer.six

test: deps
	$(PY) -m unittest discover -s ./tests -p 'test_*.py' -v

sample-docx: deps
	mkdir -p out
	$(PY) -m resume_assistant extract \
	  --linkedin examples/linkedin.sample.txt \
	  --resume examples/resume.sample.txt \
	  --profile sample
	$(PY) -m resume_assistant render \
	  --data out/sample/data.json \
	  --template config/template.example.yaml \
	  --seed 'keywords=Go AWS Kubernetes' \
	  --profile sample

# Tidy helpers
TIDY_PREFIX ?= brian_sherwin
TIDY_SUFFIXES ?= .json,.docx
TIDY_KEEP ?= 3

tidy-data:
	$(PY) -m resume_assistant files tidy --dir _data --prefix $(TIDY_PREFIX) --suffixes $(TIDY_SUFFIXES) --keep $(TIDY_KEEP)

tidy-out:
	$(PY) -m resume_assistant files tidy --dir out --prefix $(TIDY_PREFIX) --suffixes $(TIDY_SUFFIXES) --keep $(TIDY_KEEP)

tidy-temp:
	# Use CLI tidy with purge-temp only (no archive/delete moves)
	$(PY) -m resume_assistant files tidy --dir _data --suffixes .nomatch --keep 999999 --purge-temp
	$(PY) -m resume_assistant files tidy --dir out --suffixes .nomatch --keep 999999 --purge-temp

exp-export: deps
	$(PY) -m resume_assistant experience export \
	  --data out/$(TIDY_PREFIX)/data.json \
	  --out config/experience.$(TIDY_PREFIX).yaml \
	  --max-bullets 8

clean:
	# Python caches and test artifacts
	rm -rf out .pytest_cache .mypy_cache .coverage htmlcov build dist *.egg-info
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete
	# Common OS/editor temp files and DOCX lock files
	find . -name '.DS_Store' -delete
	find . -type f -name '~$$*' -delete

distclean: clean
	rm -rf out _out

deepclean: distclean
	rm -rf $(VENV)

# Remove only OS/editor temp files and DOCX lock files
purge-temp:
	find . -name '.DS_Store' -delete
	find . -type f -name '~$$*.docx' -delete
