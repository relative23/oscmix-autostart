PYTHON ?= python3
SCRIPTS = bin/oscmix-session bin/oscmix-launch
PACKAGE = src/oscmix_autostart
SHELL_SCRIPTS = install.sh uninstall.sh
# Repeats for the flakiness gate. The suite binds real UDP sockets and
# runs background threads, so a single green run proves little.
REPEAT ?= 5

.PHONY: all check test lint typecheck deadcode coverage mutation flake \
	verify-hardware install uninstall clean

all: check

# Everything CI enforces, in the order that fails fastest.
check: lint typecheck deadcode test

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m py_compile $(SCRIPTS)
	$(PYTHON) -m ruff check .
	shellcheck $(SHELL_SCRIPTS)

# --strict on the package: it is the whole runtime, and nothing in it has
# an excuse for an untyped boundary. The bin/ shims stay on the relaxed
# setting because they exist to bootstrap sys.path before any import.
typecheck:
	$(PYTHON) -m mypy --strict $(PACKAGE)
	$(PYTHON) -m mypy --ignore-missing-imports --scripts-are-modules $(SCRIPTS)

deadcode:
	$(PYTHON) -m vulture $(PACKAGE) $(SCRIPTS) tests/ --min-confidence 80

# parallel mode plus a combine step: the integration tests measure the
# session subprocess too, and each process writes its own data file.
coverage:
	$(PYTHON) -m coverage erase
	$(PYTHON) -m coverage run -m pytest -q
	$(PYTHON) -m coverage combine
	$(PYTHON) -m coverage report

# The only check that measures audio rather than messages. Needs a
# connected interface, a running backend and a quiet bus; exits 77 and
# says why when any of those is missing, so it is safe to wire into CI.
verify-hardware:
	$(PYTHON) scripts/verify-hardware.py --evidence hardware-evidence.json

# Answers what coverage cannot: whether the assertions catch a wrong
# value or merely execute the line. Slow (~15 min), so it is not part of
# `check`; the baseline in quality/ turns the result into a ratchet.
mutation:
	$(PYTHON) -m mutmut run --max-children 4
	$(PYTHON) scripts/mutation-policy.py

# Runs the suite repeatedly: races in the UDP/threading fakes only show up
# across runs, and one such race was shipped before this gate existed.
flake:
	@for i in $$(seq 1 $(REPEAT)); do \
		echo "--- run $$i/$(REPEAT)"; \
		$(PYTHON) -m pytest -q || exit 1; \
	done

install:
	./install.sh

uninstall:
	./uninstall.sh

clean:
	rm -rf build tests/__pycache__ .pytest_cache .ruff_cache .mypy_cache \
		.coverage htmlcov mutants hardware-evidence.json
