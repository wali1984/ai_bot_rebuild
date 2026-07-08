# Test Master Audit — AI BOT V2
Generated: 2026-07-01T22:56:31Z

## Test Inventory Summary

| Category | Count | Location |
|----------|-------|---------|
| Backend Python tests (total) | 1,337 | v2/backend/tests/ |
| — Contract tests | ~2 | tests/contract/ |
| — Integration tests (API) | ~10 | tests/integration/api/ |
| — Integration tests (CLI) | ~100+ | tests/integration/cli/ |
| — Integration tests (services) | ~50+ | tests/integration/services/ |
| — Unit tests | ~1,100+ | tests/unit/ |
| Playwright E2E tests | 48 | v2/frontend/tests/e2e/ |
| **Total tests** | **~1,385** | |

## Backend Test Structure

### Contract Tests (`tests/contract/`)
- `test_middleware_order.py` — verifies MIDDLEWARE_ORDER matches expected stack
- `test_taxonomy_enumeration.py` — verifies error taxonomy enumeration is complete

### Integration Tests (`tests/integration/`)

**API Integration:**
- `test_auth_rbac_and_status.py` — auth + RBAC integration
- `v2/test_landing_routes.py` — V2 landing routes
- `v2/test_market_contract_routes.py` — market data contract routes
- `v2/test_pipeline_control_routes.py` — pipeline control routes
- `v2/test_trader_snapshot.py` — trader snapshot route

**CLI Integration (subset):**
- `test_v2_trade_management_paper_loop.py` — paper loop integration
- `test_v2_risk_gateway_live_loop.py` — risk gateway integration
- `test_v2_orchestrator_arbitration_loop.py` — orchestrator integration
- `test_v2_native_cuda_trainer_persistent_loop.py` — trainer integration
- `test_v2_feature_pipeline_native_loop.py` — feature pipeline integration
- `test_v2_binance_kline_wss_loop.py` — Binance kline ingestor
- `test_v2_liquidation_wss_loop.py` — liquidation WSS
- `test_v2_coinapi_wsds_loop.py` — CoinAPI WSDS
- `test_v2_kucoin_ingestor_worker.py` — KuCoin ingestor
- `test_v2_full_talib_ta_loop.py` — TA-Lib loop
- `test_paper_shadow_outcome_observer.py` — paper outcome observer
- `test_v2_adaptive_capital_productivity_status.py` — capital status
- ~80 more CLI integration tests

### Unit Tests (`tests/unit/`)
Organized by subsystem:
- `adapters/redis_v2/` — Redis adapter unit tests
- `adapters/trainer/` — Trainer adapter unit tests
- `composition/` — Composition layer unit tests (fail-closed gates, execution attribution, etc.)
- `cli/` — CLI unit tests
- `api/` — API route unit tests
- `aggregate_evidence_rollup_harness/` — Evidence rollup tests

### Property Tests (`tests/property/`)
- Property-based tests using hypothesis

## Playwright E2E Tests (48 specs)

| Spec | Purpose |
|------|---------|
| trade_terminal_redesign.spec.ts | Trade terminal UI |
| realtime_resource_frame_semantics.spec.ts | Realtime data frame contract |
| mission_control_readiness_banner.spec.ts | Mission control banner |
| static_admin_payload_realtime_contract.spec.ts | Admin payload contract |
| nervyx_branding.spec.ts | Brand/UI consistency |
| market_public_fallback.spec.ts | Market page fallback behavior |
| admin_information_architecture.spec.ts | Admin nav structure |
| runtime_alpha_dynamic_readiness_visibility.spec.ts | Runtime readiness display |
| legacy_admin_redirects.spec.ts | Legacy admin redirects |
| trader_nav_cleanliness.spec.ts | Trader navigation |
| (38 more specs) | ... |

## Last Known Test Status
- Backend unit tests: **3,493 passing** (from memory at 2026-06-27)
- Note: Test count in codebase (1,337 files) vs running count (3,493) may differ because each file can have multiple test functions

## What Tests Prove

| Subsystem | Test Coverage | What's Proven |
|-----------|--------------|---------------|
| Paper trader | Integration + unit | Paper loop runs, heartbeat published, safety invariants |
| Risk gateway | Integration + unit | Gateway runs, deny_default logic |
| Orchestrator | Integration + unit | Arbitration logic, deconflict rules |
| Feature pipeline | Integration | Pipeline runs, keys written |
| Trainer | Integration | Trainer loop runs, checkpoint loads |
| Ingestors | Integration (all major ingestors) | Services start, Redis keys written |
| API routes | Integration + E2E | Routes respond, auth enforced |
| Safety gates | Unit + contract | live_block_guard, middleware order |

## What Tests Do NOT Prove
- Actual model quality / win rate
- Real exchange order placement (intentional — no real orders allowed)
- LunarCrush/Nansen data quality (credential-gated)
- Trainer feedback quality (quarantine issue not tested)
- Paper PnL profitability

## Coverage Gaps
| Gap | Priority |
|-----|---------|
| Trainer feedback quarantine root cause | P0 |
| Paper feedback → trainer consumption | P0 |
| End-to-end signal → paper fill chain | P1 |
| Capital allocator with live-like sizing | P1 |
| AICoin integration (credential test) | P2 |
