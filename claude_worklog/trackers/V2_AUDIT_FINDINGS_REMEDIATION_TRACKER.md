# V2 Audit Findings Remediation Tracker

**Tracker packet:** `V2_AUDIT_FINDINGS_REMEDIATION_TRACKER_READY`
**Generated:** 2026-05-20
**Source audit:** [../../INDEPENDENT_FULL_AUDIT.md](../../INDEPENDENT_FULL_AUDIT.md)
**Structured form:** [V2_AUDIT_FINDINGS_REMEDIATION_TRACKER.json](V2_AUDIT_FINDINGS_REMEDIATION_TRACKER.json)

This tracker converts the independent audit into exact lanes with
owners, status, and next tasks. No finding is claimed fixed
without a corresponding `V2_*_READY` packet that ships, passes
Codex, and has a matching evidence pointer in this file.

**Tracker rules:**

1. The tracker is append-mostly. Findings are never deleted; if a
   finding turns out incorrect, mark it `WontFix` and link the
   superseding evidence.
2. A finding moves to `Done` only after its closing gate ships
   and Codex passes. Reverting requires a fresh audit observation.
3. Codex reviewers MUST read this tracker before any live-canary
   or production-equivalence approval.
4. The tracker is the source of truth for what V2 is missing. The
   independent audit is the source-of-truth snapshot; this tracker
   is the working document.

## Tracker schema

Each row has:
- **Lane** — the user-specified category (1–8).
- **ID** — `AUD-NNN`, immutable.
- **Owner** — who carries the lane forward (currently
  `Claude/Codex queue` for every Open finding; the operator can
  reassign).
- **Status** — `Open` · `InProgress` · `Done` · `WontFix`.
- **Priority** — P0 (production-replacement blocker) · P1
  (autonomy/parity) · P2 (alignment).
- **Next task** — the next concrete `V2_*_READY` packet to ship.
- **Evidence** — pointer to the audit section or completed packet.

## Lane 1 — Native ingestors missing

| ID | Title | Owner | Status | Pri | Next task |
| --- | --- | --- | --- | --- | --- |
| AUD-001 | 13 legacy live ingestors have no running V2 native equivalent. Binance WS, Binance liquidations stream, CoinAnk REST polling, CoinAnk global aggregator, KuCoin WS, CoinAPI REST, CoinAPI WS, technical-analysis pipeline, realtime_price_provider, feature_pipeline, AlphaVantage news, TokenMetrics, coinank pipeline monitor. | Claude/Codex queue | Open | P0 | `V2_NATIVE_INGESTOR_BINANCE_USDM_OHLCV_READY` (one ingestor at a time; resist suite-style mega-packets) |
| AUD-007 | Feature pipeline reads paper snapshots not live feeds. | Claude/Codex queue | Open (blocked by AUD-001) | P1 | `V2_FEATURE_PIPELINE_NATIVE_LIVE_READ_READY` after at least one live ingestor is healthy. |

## Lane 2 — Trainer / checkpoint missing

| ID | Title | Owner | Status | Pri | Next task |
| --- | --- | --- | --- | --- | --- |
| AUD-002 | `rl/hybrid_trainer.py` (57k LOC) has no V2 native loop. `rl_core/service.py` declares itself partially migrated, paper-only. | Claude/Codex queue | Open | P0 | `V2_RL_TRAINER_PORT_PHASE_1_READY` (env/reward/state-space port with parity tests against legacy) |
| AUD-004 | Trained PPO+MASA checkpoint is not loaded. Paper loop uses heuristic decisions instead of the AI model. | Claude/Codex queue | Open | P0 | `V2_RL_CHECKPOINT_PROMOTION_PIPELINE_READY` (checkpoint metadata → torch.load → inference) after AUD-002 |
| AUD-020 | Torch nightly vs stable mismatch — legacy `2.10.0.dev20250930+cu128`, V2 `2.10.0+cu128`. Checkpoint loading risk if nightly-only APIs are used. | Claude/Codex queue | Open | P2 | `V2_RL_CHECKPOINT_TORCH_PARITY_READY` (audit checkpoint for nightly-only ops; document or pin torch) |

## Lane 3 — Trader / stops / TP / hedge missing

| ID | Title | Owner | Status | Pri | Next task |
| --- | --- | --- | --- | --- | --- |
| AUD-003 | `trading/trader.py` (24k LOC) + 34 other trading files have no V2 live-capable port. V2 has paper canary only. | Claude/Codex queue | Open | P0 | `V2_LIVE_TRADER_NATIVE_LANE_PHASE_1_READY` (after live-canary first-real-order packet) |
| AUD-005 | Live-canary scaffold remains dry-run only. No real order has shipped. | Claude/Codex queue | Open by design | P0 | `V2_LIVE_CANARY_FIRST_REAL_ORDER_READY` (requires operator + Codex final approval; out of scope until then) |
| AUD-006 | Stealth stops, dynamic TP, hedge engines, smart entry gate, market regime detector, maker execution — missing. | Claude/Codex queue | Open | P1 | `V2_TRADER_COMPONENTS_NATIVE_LANE_PHASE_1_READY` (stealth stops first because that's the smallest module that touches order flow) |

## Lane 4 — Dependency parity

| ID | Title | Owner | Status | Pri | Next task |
| --- | --- | --- | --- | --- | --- |
| AUD-014 | 11+ critical pip packages absent in V2 venv: `torchaudio`, `torchvision`, `pytorch_triton`, `grpcio`, `pynvml`, `nvidia_ml_py`, `trio`, `trio_websocket`, `nest_asyncio`, `tzdata`, `retrying`. | Claude/Codex queue | Open | P2 | `V2_DEPENDENCY_MATRIX_AND_FREEZE_READY` (publish a single matrix with rationale per package before doing any install). **Do NOT install packages ad-hoc.** |
| AUD-015 | pandas 3.0.2 (V2) vs 2.3.3 (legacy). Pandas 3 has mandatory CoW + removed deprecated APIs. | Claude/Codex queue | Open | P2 | Bundled in AUD-014 matrix; decision likely pin to 2.3.3 or audit every DataFrame call. |
| AUD-016 | pydantic 2.9.2 (V2) vs 2.12.5 (legacy). Breaking changes 2.9→2.12. | Claude/Codex queue | Open | P2 | Bundled in AUD-014 matrix. |
| AUD-017 | redis-py 5.0.8 (V2) vs 7.1.0 (legacy). Async API differences. | Claude/Codex queue | Open | P2 | Bundled in AUD-014 matrix. |
| AUD-018 | fastapi 0.115.0 (V2) vs 0.128.0 (legacy). | Claude/Codex queue | Open | P2 | Bundled in AUD-014 matrix. |
| AUD-019 | uvicorn 0.30.6 (V2) vs 0.40.0 (legacy). | Claude/Codex queue | Open | P2 | Bundled in AUD-014 matrix. |

## Lane 5 — Telegram alerts

| ID | Title | Owner | Status | Pri | Next task |
| --- | --- | --- | --- | --- | --- |
| AUD-011 | Legacy `telegram_alerts.py` (2,243 lines) has no V2 equivalent. Operators receive no V2 alerts. | Claude/Codex queue | Open | P1 | `V2_TELEGRAM_ALERTS_NATIVE_READY` — read `.local_secrets/live_canary_credentials.env` for TELEGRAM_BOT_TOKEN, install as a systemd-managed minimal alert daemon that consumes `v2:live_canary:status` + `v2:live_canary:heartbeat` and emits to operator's existing chat ID. |

## Lane 6 — Watchdog / restart policy

| ID | Title | Owner | Status | Pri | Next task |
| --- | --- | --- | --- | --- | --- |
| AUD-010 | No auto-restart watchdog for V2 services. `v2_production_replacement_runtime_guard` monitors but does not restart. | Claude/Codex queue | Open | P1 | `V2_CONTROL_PLANE_WATCHDOG_AUTORESTART_READY` — convert hand-rolled monitor into systemd `Restart=on-failure` + `RestartSec=` per service. The public-website backend unit (shipped this lane) already uses `Restart=on-failure`; replicate to all dry-run / paper / observer units. |

## Lane 7 — Config parity

| ID | Title | Owner | Status | Pri | Next task |
| --- | --- | --- | --- | --- | --- |
| AUD-021 | Legacy `config.py` (6,006 lines) has no V2 equivalent. V2 `settings.py` is 26 lines. | Claude/Codex queue | Open | P2 | `V2_RUNTIME_CONFIG_PARITY_PHASE_1_READY` — port one section per packet (start with SYMBOLS / LEVERAGE / MARGIN_TYPE / RISK_PER_TRADE; these surface in the existing canary cap fields already). |

## Lane 8 — DB decision

| ID | Title | Owner | Status | Pri | Next task |
| --- | --- | --- | --- | --- | --- |
| AUD-012 | `pyproject.toml` declares SQLAlchemy + alembic but `DATABASE_URL` is blank, no migrations exist, no SQLite/Postgres provisioned. | Claude/Codex queue | Open | P1 | `V2_PERSISTENCE_DB_DECISION_READY` — pick SQLite (local-first) vs Postgres (multi-host) BEFORE writing migrations. Document constraints (write durability for live-canary ledger, schema versioning, backup). Do NOT install Postgres without operator confirmation. |

## Done (closed lanes)

| ID | Lane | Closing gate | Closed |
| --- | --- | --- | --- |
| AUD-008 | 2 / public website backend | `V2_PUBLIC_WEBSITE_BACKEND_ONLINE_READY` (Codex PASS) | 2026-05-20 |
| AUD-009 | 2 / public website backend | Same packet (REDIS_URL injected via systemd unit) | 2026-05-20 |
| AUD-013 | live-canary approval binding | Closed by `V2_LIVE_CANARY_PERMISSION_PROBE_FRESHNESS_AND_MIRROR_REMEDIATION_READY`. Probe transitioned to READY in both mirrors at `2026-05-20T19:53:49Z`; GATE_3 cleared from the dry-run executor's cascade. Approval parser + mirror-consistency invariant + probe-READY all satisfied. | 2026-05-20 |

## Tracker invariants

The tracker NEVER:

- Auto-installs pip packages (see AUD-014 matrix requirement).
- Auto-enables a credentialed systemd timer.
- Claims a finding closed without a `V2_*_READY` packet + Codex
  pass.
- Modifies `/home/wali/Desktop/AI BOT`.
- Touches the legacy Redis keyspace.
- Issues live-trading or canary approvals.
- Promises a date for any Open finding.

## Cross-references

- Source audit: [INDEPENDENT_FULL_AUDIT.md](../../INDEPENDENT_FULL_AUDIT.md)
- Prior tracker (markdown): [AUDIT_GAPS_TRACKER.md](AUDIT_GAPS_TRACKER.md)
- Prior tracker (JSON): [AUDIT_GAPS_TRACKER.json](AUDIT_GAPS_TRACKER.json)
- Lane 1 done: [v2_live_canary_dry_run_approval_binding_remediation/latest/](../final_readiness/v2_live_canary_dry_run_approval_binding_remediation/latest/)
- Lane 2 done: [v2_public_website_backend_online/latest/](../final_readiness/v2_public_website_backend_online/latest/)
- Tracker packet: [v2_audit_findings_remediation_tracker/latest/](../final_readiness/v2_audit_findings_remediation_tracker/latest/)
