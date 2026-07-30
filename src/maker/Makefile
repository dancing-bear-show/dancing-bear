VENV := .venv
PY := $(VENV)/bin/python

.PHONY: venv clean

venv:
	python3 -m venv $(VENV)
	$(PY) -m pip install -U pip
	$(PY) -m pip install -r requirements.txt

clean:
	rm -rf $(VENV)

