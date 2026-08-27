# Documentation and quality targets for the mhsim package.
# All targets use the repo-local virtual environment; run them from the repo root.

PY := .venv/bin/python
VERSION := $(shell $(PY) -c "import importlib.metadata as m; print(m.version('mhsim'))")

.PHONY: help install lint docstrings test docs docs-serve schema api-check check

help:  ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Editable install with the docs and dev extras.
	$(PY) -m pip install -e ".[docs,dev]"

lint:  ## Docstring style and completeness (ruff pydocstyle rules).
	.venv/bin/ruff check mhsim/ --select D

docstrings:  ## Docstring coverage against the floor in pyproject.toml.
	.venv/bin/interrogate -v mhsim/

test:  ## Unit tests plus the doctests embedded in mhsim/.
	$(PY) -m pytest

docs:  ## Build the documentation site into site/ (warnings are errors).
	.venv/bin/mkdocs build --clean --strict

docs-serve:  ## Serve the documentation site locally with live reload.
	.venv/bin/mkdocs serve

schema:  ## Dump the Griffe API schema for the current version into api/.
	@mkdir -p api
	.venv/bin/griffe dump mhsim -o api/mhsim-$(VERSION).json
	@echo "wrote api/mhsim-$(VERSION).json"

api-check:  ## Report public API breakages against the last tag (or REF=<ref>).
	.venv/bin/griffe check mhsim $(if $(REF),-a $(REF),) -f oneline

check: lint docstrings test docs  ## Everything that must pass before a commit.
	@echo "All checks passed."
