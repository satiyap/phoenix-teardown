PY := ./.venv/bin/python

.PHONY: help status validate matrix check probes llm setup spec

help:
	@echo "make setup     create venv and install deps"
	@echo "make status    coverage, ADR state, deliverable progress"
	@echo "make validate  check every facts.yaml against the schema"
	@echo "make matrix    regenerate synthesis/capability-matrix.md"
	@echo "make check     validate --strict + spec + matrix + status (must exit 0)"
	@echo "make spec      validate spec/ (vectors, rewind algorithm, references)"
	@echo "make probes    print probe set summary"
	@echo "make llm       gateway health check"

setup:
	python3 -m venv .venv
	$(PY) -m pip install -q pyyaml==6.0.2
	@test -f .env || cp .env.example .env
	@echo "ready. add LLM_API_KEY to .env"

status:
	@cd tools && ../$(PY) check_exit_criteria.py

validate:
	@cd tools && ../$(PY) validate_facts.py

matrix:
	@cd tools && ../$(PY) build_matrix.py

check:
	@cd tools && ../$(PY) validate_facts.py --strict && ../$(PY) validate_spec.py && ../$(PY) build_matrix.py && ../$(PY) check_exit_criteria.py

probes:
	@cd tools && ../$(PY) probes.py

llm:
	@$(PY) tools/llm.py

spec:
	@cd tools && ../$(PY) validate_spec.py
