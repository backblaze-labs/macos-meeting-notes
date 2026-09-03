PYTHON ?= .venv/bin/python
SETUP_PYTHON ?=
PYTHON_CANDIDATES ?= python3.11 python3.12 python3.13 python3.14 python3

ARCH ?= $(shell uname -m)
SIGN_IDENTITY ?= -

.PHONY: setup install build-native-audio build-distribution verify-distribution run auth doctor install-macos-app reload-macos-app open-macos-app quit-macos-app install-launch-agent uninstall-launch-agent lint format test check check-structure check\:structure

setup:
	@set -e; \
	if [ -x .venv/bin/python ]; then \
	  if ! .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then \
	    echo "The existing .venv runs $$(.venv/bin/python --version), but Meeting Memory needs Python 3.11 or later."; \
	    echo "Remove it and rerun setup:  rm -rf .venv && make setup"; \
	    exit 1; \
	  fi; \
	else \
	  py="$(SETUP_PYTHON)"; \
	  if [ -n "$$py" ]; then \
	    if ! command -v "$$py" >/dev/null 2>&1; then \
	      echo "SETUP_PYTHON=$$py was not found on PATH."; exit 1; \
	    fi; \
	    if ! "$$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then \
	      echo "SETUP_PYTHON=$$py is $$("$$py" --version 2>&1), but 3.11 or later is required."; exit 1; \
	    fi; \
	  fi; \
	  if [ -z "$$py" ]; then \
	    for candidate in $(PYTHON_CANDIDATES); do \
	      if command -v "$$candidate" >/dev/null 2>&1 && \
	         "$$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then \
	        py="$$candidate"; break; \
	      fi; \
	    done; \
	  fi; \
	  if [ -z "$$py" ]; then \
	    echo "Meeting Memory needs Python 3.11 or later, and none was found."; \
	    echo "macOS ships Python 3.9 as /usr/bin/python3, which cannot run this app."; \
	    echo ""; \
	    echo "Install one, then rerun 'make setup':"; \
	    echo "    brew install python@3.11"; \
	    echo ""; \
	    echo "Note: that formula does not replace 'python3'. If 'make setup' still"; \
	    echo "fails afterwards, point it at the interpreter directly:"; \
	    echo "    make SETUP_PYTHON=python3.11 setup"; \
	    exit 1; \
	  fi; \
	  echo "Creating .venv with $$py ($$("$$py" --version 2>&1))"; \
	  "$$py" -m venv .venv; \
	fi
	.venv/bin/python -m pip install -e ".[dev]"
	.venv/bin/python -m meeting_memory setup

install:
	$(PYTHON) -m pip install -e ".[dev]"

build-native-audio:
	PYTHONPATH=src $(PYTHON) -m meeting_memory build-native-audio

build-distribution:
	$(PYTHON) scripts/build_distribution.py --arch $(ARCH) --identity "$(SIGN_IDENTITY)"

verify-distribution:
	$(PYTHON) scripts/verify_distribution.py --app "dist/$(ARCH)/Meeting Memory.app" --arch $(ARCH) --signature adhoc

run: build-native-audio
	PYTHONPATH=src MEETING_MEMORY_CAPTURE_HELPER=$(CURDIR)/.build/MeetingMemoryCapture $(PYTHON) -m meeting_memory

auth:
	PYTHONPATH=src $(PYTHON) -m meeting_memory auth

doctor:
	PYTHONPATH=src $(PYTHON) -m meeting_memory.doctor

install-macos-app:
	PYTHONPATH=src $(PYTHON) -m meeting_memory install-macos-app

reload-macos-app:
	PYTHONPATH=src $(PYTHON) -m meeting_memory reload-macos-app

open-macos-app:
	PYTHONPATH=src $(PYTHON) -m meeting_memory open-macos-app

quit-macos-app:
	PYTHONPATH=src $(PYTHON) -m meeting_memory quit-macos-app

install-launch-agent:
	PYTHONPATH=src $(PYTHON) -m meeting_memory install-launch-agent

uninstall-launch-agent:
	PYTHONPATH=src $(PYTHON) -m meeting_memory uninstall-launch-agent

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

test:
	PYTHONPATH=src $(PYTHON) -m pytest

check-structure:
	PYTHONPATH=src $(PYTHON) -m pytest tests/test_structure.py

check\:structure: check-structure

check: lint test check-structure
