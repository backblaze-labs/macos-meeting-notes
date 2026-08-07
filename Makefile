PYTHON ?= python

.PHONY: setup install build-native-audio run auth doctor install-macos-app reload-macos-app open-macos-app quit-macos-app install-launch-agent uninstall-launch-agent lint format test check check-structure check\:structure

setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install -e ".[dev]"
	.venv/bin/python -m meeting_memory setup

install:
	$(PYTHON) -m pip install -e ".[dev]"

build-native-audio:
	PYTHONPATH=src $(PYTHON) -m meeting_memory build-native-audio

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
