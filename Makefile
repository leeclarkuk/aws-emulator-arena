PORT ?= 9297
export PORT

.PHONY: arena test serve install-emulator

arena:
	bash scripts/run.sh $(ARGS)

test:
	python3 -m pytest -q tests

serve:
	python3 -m http.server 8765 --directory site

install-emulator:
	bash scripts/install-emulator.sh
