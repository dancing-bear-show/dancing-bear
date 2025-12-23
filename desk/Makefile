PYTHON?=python3
VENV=.venv

.PHONY: venv install dev test lint clean

venv:
	$(PYTHON) -m venv $(VENV)
	. $(VENV)/bin/activate && pip install -U pip
	. $(VENV)/bin/activate && pip install -e .

install:
	$(PYTHON) -m pip install -e .

dev: venv
	. $(VENV)/bin/activate && pip install -e .[yaml]

test:
	$(PYTHON) -m unittest discover -s tests -v

clean:
	rm -rf $(VENV) build dist *.egg-info __pycache__ **/__pycache__
