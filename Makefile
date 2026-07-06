PYTHON ?= python3

.PHONY: all test lint install uninstall clean

all: lint test

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m py_compile bin/oscmix-session bin/oscmix-launch
	shellcheck install.sh uninstall.sh

install:
	./install.sh

uninstall:
	./uninstall.sh

clean:
	rm -rf build tests/__pycache__ .pytest_cache
