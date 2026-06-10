PYTHON ?= python

.PHONY: install run auth doctor lint format test check check-structure check\:structure

install:
	$(PYTHON) -m pip install -e ".[dev]"

run:
	PYTHONPATH=src $(PYTHON) -m meeting_memory

auth:
	PYTHONPATH=src $(PYTHON) -m meeting_memory auth

doctor:
	PYTHONPATH=src $(PYTHON) -m meeting_memory.doctor

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
