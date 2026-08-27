PY := ./.venv/bin/python

.PHONY: help status validate matrix check probes llm setup spec gate-tests spike06 spike06-mutations

help:
	@echo "make setup     create venv and install deps"
	@echo "make status    coverage, ADR state, deliverable progress"
	@echo "make validate  check every facts.yaml against the schema"
	@echo "make matrix    regenerate synthesis/capability-matrix.md"
	@echo "make check     validate --strict + spec + matrix + status (must exit 0)"
	@echo "make spec      validate spec/ (vectors, rewind algorithm, references)"
	@echo "make gate-tests negative controls for the superseded-claims gate"
	@echo "make probes    print probe set summary"
	@echo "make llm       gateway health check"

setup:
	@command -v node >/dev/null || echo "WARNING: node missing — the canonicalisation oracle cannot run"
	python3 -m venv .venv
	$(PY) -m pip install -q pyyaml==6.0.2 grpcio-tools==1.83.0
	@test -f .env || cp .env.example .env
	@echo "ready. add LLM_API_KEY to .env"

status:
	@cd tools && ../$(PY) check_exit_criteria.py

validate:
	@cd tools && ../$(PY) validate_facts.py

matrix:
	@cd tools && ../$(PY) build_matrix.py

check:
	@git diff --check || (echo "trailing whitespace or conflict markers — see git diff --check"; exit 1)
	@$(PY) tools/test_validate_spec.py
	@$(MAKE) --no-print-directory spike06
	@cd tools && ../$(PY) validate_facts.py --strict && ../$(PY) validate_spec.py && ../$(PY) build_matrix.py && ../$(PY) check_exit_criteria.py

probes:
	@cd tools && ../$(PY) probes.py

llm:
	@$(PY) tools/llm.py

spec:
	@cd tools && ../$(PY) validate_spec.py

gate-tests:
	@$(PY) tools/test_validate_spec.py

# Spike 06's assertions (57 as of 2026-08-28; 18 -> 26 -> 47 -> 53 -> 57 across five rounds -- the
# figure is not read by any check, see OQ-060) were NOT executed by any repository target, so a green
# `make check` was being presented as evidence for them. It now runs them, pin first:
# the digest check must fail the session if the installed SDK is not the code the
# gates were written against.
spike06:
	@cd spikes/06-tool-interception && ../../$(PY) verify_pin.py
	@cd spikes/06-tool-interception && ../../$(PY) -m pytest test_gate.py -q

spike06-mutations:
	@cd spikes/06-tool-interception && ../../$(PY) mutate.py --check
