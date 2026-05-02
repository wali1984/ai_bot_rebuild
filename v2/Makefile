# AI BOT V2 — top-level Makefile
# Local-native targets only. No Docker. No legacy DB/Redis/exchange.
# `make ci` runs every required CI stage in the order declared by
# 07_TEST_AND_CI_PLAN.md §5; advisory stages are guarded with `-` so they
# do not break the gate while remaining visible.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c

V2_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

.PHONY: ci ci-required ci-advisory \
        ci-lint ci-type ci-import-cycle ci-schema-drift ci-orphan-path \
        ci-unit ci-integration ci-contract ci-property \
        ci-frontend-unit ci-e2e ci-secrets-scan ci-coverage ci-security-audit \
        help

help:
	@echo "AI BOT V2 — make targets:"
	@echo "  make ci                  Run the full CI matrix (required + advisory stages)"
	@echo "  make ci-required         Run required stages only (B-gate)"
	@echo "  make ci-lint             ruff (mandatory) + eslint (advisory)"
	@echo "  make ci-type             mypy --strict + tsc --noEmit"
	@echo "  make ci-import-cycle     grimp (backend) + madge (frontend, advisory)"
	@echo "  make ci-schema-drift     Alembic head vs SQLAlchemy metadata (advisory until C)"
	@echo "  make ci-orphan-path      Materialization sanity (advisory)"
	@echo "  make ci-unit             pytest backend/tests/unit"
	@echo "  make ci-integration      pytest backend/tests/integration (ephemeral PG)"
	@echo "  make ci-contract         pytest backend/tests/contract"
	@echo "  make ci-property         pytest backend/tests/property"
	@echo "  make ci-frontend-unit    vitest run (deferred to milestone F)"
	@echo "  make ci-e2e              playwright test"
	@echo "  make ci-secrets-scan     gitleaks (working tree, redacted)"

# Required + advisory stages combined. Required stages are 'hard'; advisory
# stages are prefixed with '-' so a non-zero exit does not abort the gate.
ci: ci-required ci-advisory
	@echo "[make/ci] OK"

ci-required: ci-lint ci-type ci-import-cycle ci-unit ci-integration ci-contract ci-frontend-unit ci-e2e ci-secrets-scan
	@echo "[make/ci-required] OK"

ci-advisory:
	-$(MAKE) ci-schema-drift
	-$(MAKE) ci-orphan-path
	-$(MAKE) ci-coverage
	-$(MAKE) ci-security-audit

ci-lint:
	bash $(V2_ROOT)/ops/ci/lint.sh

ci-type:
	bash $(V2_ROOT)/ops/ci/type_check.sh

ci-import-cycle:
	python $(V2_ROOT)/ops/ci/import_cycle_check.py

ci-schema-drift:
	python $(V2_ROOT)/ops/ci/schema_drift_check.py

ci-orphan-path:
	python $(V2_ROOT)/ops/ci/orphan_path_check.py

ci-unit:
	bash $(V2_ROOT)/ops/ci/test.sh unit

ci-integration:
	bash $(V2_ROOT)/ops/ci/test.sh integration

ci-contract:
	bash $(V2_ROOT)/ops/ci/test.sh contract

ci-property:
	bash $(V2_ROOT)/ops/ci/test.sh property

ci-frontend-unit:
	bash $(V2_ROOT)/ops/ci/test.sh frontend-unit

ci-e2e:
	bash $(V2_ROOT)/ops/ci/test.sh e2e

ci-secrets-scan:
	bash $(V2_ROOT)/ops/ci/secrets_scan.sh

ci-coverage:
	cd $(V2_ROOT) && pytest --cov=app --cov-report=term-missing backend/tests

ci-security-audit:
	cd $(V2_ROOT) && pip-audit --strict
	cd $(V2_ROOT)/frontend && npm audit --omit=dev
