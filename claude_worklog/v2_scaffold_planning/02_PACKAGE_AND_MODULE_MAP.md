# 02 — Package and Module Map

## 1. Top-level layout
The scaffold materializes a single tree rooted at `v2/`. No code is written outside this tree by the scaffold task. Legacy paths remain untouched.

```
v2/
  pyproject.toml
  package.json
  tsconfig.json
  alembic.ini
  README.md (planning-only stub; replaced by milestone B validation artifact)
  backend/
    app/
      __init__.py
      main.py                # FastAPI factory; no startup side effects beyond registering routers
      settings.py            # pydantic-settings; env-driven; no secrets resolved at import
      logging.py             # JSON structured logging; no I/O at import
      api/
        __init__.py
        v1/
          __init__.py
          health.py
          mission_control.py
          universe.py
          discovery.py
          selection.py
          exchanges.py
          ingestors.py
          features.py
          predictions.py
          signals.py
          decisions.py
          risk.py
          intents.py
          paper.py
          replay.py
          fleet.py
          monitor.py
          evidence.py
          audit.py
          governance.py
          claude_admin.py
          codex_review.py
          ollama_assistant.py
          live_readiness.py
          live_mode.py        # all routes default-deny; L5 approval required
        middleware/
          request_id.py
          idempotency.py
          rbac.py
          approval.py
          lineage_validator.py
          live_block_guard.py
          db_error_translator.py
          rate_limit.py
          ip_allowlist.py
          step_up_mfa.py
        errors/
          envelope.py
          taxonomy.py         # all error classes including lineage.*, feature_snapshot.*, confidence.*, schema.*, rbac.*, approval.*
        schemas/
          lineage.py
          feature_snapshot.py
          prediction.py
          signal.py
          decision.py
          risk_decision.py
          execution_intent.py
          paper_trade.py
          envelope.py         # request/response envelope models
      domain/
        __init__.py
        lineage/
          ids.py              # uuidv7 generators; never imports DB
          chain.py            # canonical chain definition
          validators.py       # pure functions; no I/O
        features/
          snapshot.py
          completeness.py
          source_grounding.py
          manifest.py
        predictions/
        signals/
        decisions/
        risk/
          policy_bundle.py
          phases.py
          kill_switch.py
          live_readiness_state.py
        execution/
          intent.py
          paper.py
        universe/
          version.py
          members.py
          scoring.py
        hot_reload/
          rollout.py
          state_machine.py
          quorum.py
          rollback.py
        governance/
          levels.py           # L0-L5 taxonomy
          approvals.py
          audit_chain.py
        connectors/
          base.py             # abstract; no exchange SDK imports here
          capabilities.py
          health.py
        traders/
          fleet.py
          trader.py
        monitor/
          dimensions.py
          packets.py
          rejection.py
        replay/
          deterministic.py
      adapters/
        __init__.py
        db/
          engine.py           # SQLAlchemy engine factory; lazy
          session.py
          repositories/
            feature_snapshots.py
            predictions.py
            signals.py
            decisions.py
            risk_decisions.py
            execution_intents.py
            audit_events.py
            evidence_packets.py
            universe_versions.py
            symbol_overrides.py
            governance_approvals.py
            sessions.py
            accounts.py
        redis_v2/
          client.py           # writes only to ${V2_REDIS_PREFIX}; reads legacy keys read-only
          streams.py
          retention.py
        trainer/
          subprocess_adapter.py   # subprocess boundary; no module imports
          modes.py              # read_only / status / export
          audit_emitter.py
        orchestrator/
          adapter.py
        exchanges/
          binance/
          bybit/
          okx/
          generic_ccxt/        # optional fallback; disabled by default
        ollama/
          client.py
          prompt_loader.py
        codex/
          review_client.py
        claude_admin/
          client.py
        evidence/
          packet_writer.py
          packet_reader.py
      services/
        feature_assembly.py
        prediction_ingest.py
        signal_publisher.py
        orchestrator_decision.py
        risk_gateway.py
        execution_router.py
        replay_runner.py
        paper_loop.py
        discovery_runner.py
        selection_runner.py
        hot_reload_orchestrator.py
        monitor_runner.py
        audit_writer.py
      jobs/
        scheduler.py           # APScheduler / arq; no live exchange calls
        tasks/
          packet_emitter.py
          retention_sweeper.py
          freshness_check.py
      cli/
        v2ctl.py               # diagnostics-only CLI; no live actions
    migrations/
      env.py
      alembic_revision_template.mako
      versions/                # populated in milestone C
    tests/
      unit/
      integration/
      contract/
      property/
      fixtures/
  frontend/
    package.json
    vite.config.ts
    tsconfig.json
    src/
      main.tsx
      app.tsx
      router.tsx               # React Router or TanStack Router; lazy-loads pages
      theme/
        light.ts
        dark.ts
      auth/
        session.ts
        rbac.ts
        step_up.ts
      api/
        client.ts              # fetch wrapper; injects X-Request-Id, X-Idempotency-Key
        envelope.ts
        errors.ts
      lineage/
        block.tsx              # canonical lineage block renderer
      pages/                   # 26 pages enumerated in 05_ENTERPRISE_GUI_SCAFFOLD_PLAN.md
        mission_control/
        market_universe/
        passive_discovery/
        adaptive_selection/
        exchange_manager/
        ingestor_manager/
        feature_flow_map/
        feature_freshness/
        trainer_control/
        trainer_prediction_monitor/
        signal_explainability/
        symbols/
        signals/
        executions/
        positions/
        risk_control/
        config_admin/
        strategy_admin/
        trainer_admin/
        orchestrator_admin/
        execution_admin/
        paper_trading/
        replay/
        audit_ledger/
        system_health/
        live_readiness/
        claude_admin_ai/
        ollama_assistant/
        codex_review_center/
        build_validation_status/
        mobile_pwa_readiness/
        public/
          landing/
          status/
          login/
      components/
        layout/
        nav/
        tables/
        forms/
        approvals/
        banners/                # default-deny LIVE TRADING: BLOCKED banner
        evidence/
        explainability/
      stores/                   # zustand or redux-toolkit; no auto-fetch at import
      pwa/
        manifest.ts
        service_worker.ts       # cache-only; no background trade actions
      mobile/
        bridge.ts               # placeholder for future RN/SwiftUI bridge contracts
      tests/
        unit/
        e2e/                    # Playwright; no real exchange calls
  ops/
    ci/
      lint.sh
      type_check.sh
      test.sh
      import_cycle_check.py
      schema_drift_check.py
    docker/                     # OPTIONAL; deferred per CLAUDE.md
    k8s/                        # OPTIONAL; deferred
  docs/
    INDEX.md                    # links to architecture + planning artifacts
```

## 2. Module boundary rules
- `app/api/**` MUST NOT import `app/adapters/**` directly except via `app/services/**` or via dependency-injection providers exported from `app/adapters/__init__.py`. Routers receive services through FastAPI `Depends`; they never instantiate engines or clients.
- `app/domain/**` is pure: no `requests`, no `redis`, no `sqlalchemy`, no filesystem I/O. Domain modules are deterministic given input. This guarantees replay determinism.
- `app/adapters/**` is the only place that performs I/O. Each adapter exposes a narrow interface consumable by `app/services/**`. Adapters MUST NOT import from `app/api/**`.
- `app/services/**` orchestrate domain + adapters. Services are the unit at which transactions, retries, and audit emission are anchored.
- `frontend/src/pages/**` MUST NOT import from `frontend/src/api/client.ts` directly; pages call hooks under `frontend/src/api/hooks/<resource>.ts` (created in milestone E) so the API surface remains uniform.
- `frontend/src/auth/rbac.ts` is the only authority for menu visibility. Pages MUST NOT inline role checks.

## 3. Forbidden imports (enforced in CI)
- `app/api/**` -> `app/adapters/db/**` (must go through services)
- `app/domain/**` -> `app/adapters/**`
- `app/domain/**` -> `redis|sqlalchemy|httpx|requests|psycopg|asyncpg|ccxt`
- `app/adapters/trainer/**` -> any module under `legacy_reference/**` or `../AI BOT/**`
- any module -> `dotenv` outside `app/settings.py`
- `frontend/src/pages/**` -> `frontend/src/api/client.ts`

The CI script `ops/ci/import_cycle_check.py` runs `grimp` (Python) and `madge` (TypeScript) and fails on cycles or forbidden edges. This script is shipped in milestone B and is the gate for `B_SCAFFOLD_VALIDATION.md`.

## 4. Runtime boundary contracts
- Trainer adapter: subprocess only. `subprocess.run([os.environ["LEGACY_TRAINER_PYTHON"], path, "--mode", mode, ...], check=False, timeout=...)`. Output captured, audited, never `eval`d. No imports of legacy trainer modules into the FastAPI process.
- Orchestrator adapter: same subprocess discipline initially; may be promoted to in-process only after a separate dependency-safety review (out of scope for milestone B).
- Redis V2 client: every key passes through `key(prefix=settings.V2_REDIS_PREFIX, parts=...)`. Direct string concatenation rejected by lint rule.
- Exchange connectors: scaffold provides abstract `ConnectorBase` only; concrete connectors are stubbed and disabled. No exchange SDK imports happen at module-load time. Live order calls raise `LiveBlockedError` until milestone O.

## 5. Configuration / secrets boundary
- `app/settings.py` reads env via `pydantic-settings`. It MUST NOT call `dotenv_values()`. Secrets are resolved by the secrets lease boundary defined in `15_PUBLIC_HOSTING_SECURITY_AND_RBAC_ARCHITECTURE.md` and injected via env at process start.
- No secret value is logged. The structured logger redacts known secret keys.
- `V2_MODE=paper|read_only` is the default. `V2_MODE=live` is rejected by `app/main.py` startup unless the L5 approval token is present and validated.

## 6. Test layout
- `backend/tests/unit/` — pure-domain tests; no I/O.
- `backend/tests/integration/` — service-level tests against an ephemeral Postgres (`testcontainers` or local `pg_ctl`); never against the legacy DB.
- `backend/tests/contract/` — API test vectors from `05_API_CONTRACTS.md` §13; one file per error class.
- `backend/tests/property/` — hypothesis-based lineage invariants.
- `frontend/src/tests/unit/` — component tests.
- `frontend/src/tests/e2e/` — Playwright; runs against the FastAPI app started in test mode with synthetic fixtures only.

## 7. Build artifacts produced in milestone B
- Empty packages with `__init__.py` files at every level shown above.
- `pyproject.toml` and `package.json` declaring exact versions of dependencies (no `^` or `*` ranges in production deps).
- `alembic.ini` configured but with zero versions.
- CI workflow file under `ops/ci/` that runs lint, type-check, import-cycle, schema-drift, and test placeholders.
- A `B_SCAFFOLD_VALIDATION.md` referencing each path and the proof of lint/type-check passing.

## 8. Status
PACKAGE AND MODULE MAP: PLANNED. Materialization belongs to milestone B and is gated by the L2 governance check defined in `17_IMPLEMENTATION_SEQUENCE_AND_MILESTONES.md` §5.B and §7.