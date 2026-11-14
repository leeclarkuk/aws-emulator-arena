PORT ?= 9297
export PORT

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: arena test serve install-emulator

arena:
	bash scripts/run.sh $(ARGS)

$(PY):
	python3 -m venv $(VENV)

$(VENV)/.dev-stamp: requirements-dev.txt requirements.txt $(PY)
	$(PIP) install -q -r requirements-dev.txt
	@touch $@

test: $(VENV)/.dev-stamp
	$(PY) -m pytest -q tests

serve:
	python3 -m http.server 8765 --directory site

install-emulator:
	bash scripts/install-emulator.sh
