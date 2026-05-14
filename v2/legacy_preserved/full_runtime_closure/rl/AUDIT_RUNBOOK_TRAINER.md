# AUDIT_RUNBOOK_TRAINER.md
**Project:** RL BOT PROD — Hybrid PPO + MASA Trainer (Live)  
**Purpose:** Provide an audit-ready, step-by-step runbook to configure, validate, and operate the trainer safely in a live environment.  
**Scope:** `hybrid_trainer.py` trainer runtime + multi-source, multi-timeframe unified feature ingestion + signal publishing (shadow and live-gated).

---

## 0) Non-Negotiables (Audit Controls)

### 0.1 Safety defaults
- **Default mode MUST be non-executing** (Shadow mode). No orders are placed unless an explicit “live execution” flag is set.
- All **risk gates** must be enforced **before** signal publishing (and again before execution if/when execution is enabled).
- Any failure in required dependencies (Redis, unified features coverage, price feed, GPU requirement, etc.) must be **fail-loud** for live modes.

### 0.2 Compatibility and non-breaking policy
- Do not break existing Redis key contracts or dashboards.
- All changes must be **feature-flagged** via environment variables / config flags.
- All new output fields must be additive and backwards-compatible.

### 0.3 “Config-less” requirement
- The trainer must not contain hard-coded assumptions about:
  - number of symbols
  - number of timeframes
  - observation vector length (beyond schema validation)
- Only these should be user-controlled at top level:
  - `SYMBOLS` list
  - `TIMEFRAMES` list (5 TFs target)
  - `LEARNING_TIMEFRAMES` exclusion list
  - a minimal set of global controls (training/publishing/safety flags)

---

## 1) Definitions and Glossary

### 1.1 Symbols and timeframes
- **Symbols:** List of traded markets (e.g., 13 symbols today; can change).
- **Timeframes:** Exactly **5** timeframes are used for training context (as per design requirement).
- **Learning-only timeframes:** Timeframes used for model learning but **excluded from publishing**.

### 1.2 Modes of operation
- **Shadow Mode:** inference + publishing only; no execution.
- **Training Mode:** continuous learning + checkpointing; may also publish signals (shadow).
- **Live Execution Mode:** orders may be placed; must be gated and approved after validation.

### 1.3 Canonical Redis key contracts
> These key contracts must remain stable. Any change must be additive.

**Inputs (must exist and update):**
- `unified_features:{symbol}:{tf}` (Redis HASH)
- `market:{symbol}:1m` OR `latest:binance:ohlcv:{symbol}:1m` (price fallback sources)
- `features:norm_stats:{symbol}:{tf}` (Redis HASH for rolling normalization stats)

**Operational status / outputs:**
- `status:trainer` (string with TTL)
- Heartbeat key(s) (if present): e.g., `heartbeat:Trainer`
- Metrics keys (expected by dashboards, if used): e.g., `rl:metrics:continuous`, `rl:episodes:total`

---

## 2) Preconditions and Environment Requirements

### 2.1 Hardware
- RTX 5080 GPU (CUDA enabled) for training performance targets.
- Sufficient CPU to run ingestion + correlator + trainer without resource starvation.
- Sufficient RAM to avoid swapping (swap-induced jitter breaks real-time assumptions).

### 2.2 Services
- Redis/Memurai reachable from trainer host.
- Ingestion services running and writing unified features.
- Feature correlator running and maintaining `unified_features:{symbol}:{tf}` keys.

### 2.3 Required environment variables / flags (minimum)
> Names may already exist; keep consistent with current repo patterns. Add only if missing.

- `TRAINER_MODE` = `shadow|train|live`
- `ENABLE_EXECUTION` = `0|1` (must default to `0`)
- `ENABLE_PREFLIGHT` = `1` (must default to `1`)
- `REQUIRE_CUDA` = `0|1` (for training, typically `1`)
- `ENABLE_AUTO_GPU_SCALE` = `0|1` (default `0`)
- `REWARD_LIQUIDATION_PENALTY` = `0|1` (default `1` for training)
- `PUBLISH_DEBUG_STREAM` = `0|1` (default `1`)
- `ALLOW_CHECKPOINT_OVERRIDE` = `0|1` (default `0`)

---

## 3) Configuration: What Must Be Set and Where

### 3.1 `config.py` minimal contract (must remain clean)
**Must define:**
- `SYMBOLS = [...]`
- `TIMEFRAMES = [...]`  (5 TFs)
- `LEARNING_TIMEFRAMES = [...]` (optional; excluded from publishing)
- Core trainer controls:
  - `CONTINUOUS`
  - `LOOP_TIMESTEPS`
  - `SAVE_EVERY_LOOPS`
  - `MIN_TRADING_CONFIDENCE`
  - PPO controls (batch/steps etc.) (global defaults only)
  - MASA controls:
    - `MASA_ENABLED`
    - `MASA_WEIGHT`
    - `MASA_UPDATE_FREQ` (slower / event-driven recommended)

**Must not define:**
- per-symbol overrides
- per-timeframe overrides
- hard-coded observation sizes (except schema validation entries)

### 3.2 Trainer runtime expectations (`hybrid_trainer.py`)
- Reads unified features from Redis hashes per symbol/timeframe.
- Normalizes features via rolling stats (z-score + clipping).
- Uses safe timeouts for Redis and GPU ops.
- Excludes `LEARNING_TIMEFRAMES` from publishing.
- Publishes structured signal payloads and debug (filtered) payloads with reason codes.

---

## 4) Preflight Self-Check (Mandatory on Startup)

### 4.1 Why this exists
Preflight proves the system is *ready for live operation* and prevents silent “training on zeros” or “publishing nonsense.”

### 4.2 Preflight checks (must pass for training; must pass strictly for live)
1) **Redis connectivity**
   - Can connect, read, and write a test key.
2) **Unified features coverage**
   - For each configured `{symbol, tf}` check existence of `unified_features:{symbol}:{tf}`.
   - Compute coverage % and stale age (timestamp in hash if present).
   - Enforce threshold (example):
     - Shadow/Train: >= 70% coverage allowed (warning if below)
     - Live: >= 95% coverage required (hard fail if below)
3) **Price feed availability**
   - For each symbol, confirm either `market:{symbol}:1m` or `latest:binance:ohlcv:{symbol}:1m` is readable.
4) **Observation dimension sanity**
   - Build one observation vector for one symbol and confirm its length matches the trainer’s computed obs_dim.
   - If checkpoint is to be loaded: ensure checkpoint’s expected obs_dim matches runtime obs_dim.
5) **GPU requirement**
   - If `REQUIRE_CUDA=1`, ensure CUDA available and model can allocate a small tensor on GPU.
6) **Multiprocessing correctness**
   - Ensure correct start method (spawn) if required by CUDA/multiprocessing environment strategy.
7) **Mode gating**
   - If `TRAINER_MODE=live` and any above fails, exit with explicit reason.

### 4.3 Preflight audit output (must be logged and saved)
- Run timestamp, host, git commit/build id if available
- Symbols/timeframes lists detected
- Coverage % and stale ages summary
- obs_dim computed and checkpoint compatibility results
- CUDA status + device name
- Enabled flags summary

---

## 5) Signal Publishing Contract

### 5.1 Signal payload minimum fields
Every published signal must include:
- `timestamp`
- `symbol`
- `timeframe`
- `action`
- `confidence`
- `risk_summary` (must include at least margin utilization and exposure)
- `liquidation_proximity` (distance to liquidation or risk bucket)
- `constraints_applied` (list)
- `source_tag` (e.g., `hybrid_trainer`)
- `version` (schema version for payload)

### 5.2 Filtering and debug publishing
- Any signal not published due to gating must still be written to a debug stream with:
  - `filtered_reason_code` (e.g., LOW_CONFIDENCE, LEARNING_TIMEFRAME, RISK_GATE_MARGIN, DATA_STALE, etc.)
  - all fields above + any missingness flags

### 5.3 Confidence and cooldown
- Centralize `MIN_TRADING_CONFIDENCE` thresholds.
- Implement cooldowns per symbol/timeframe to avoid spamming signals in unstable conditions.
- Cooldown events must be logged and debug-published (reason: COOLDOWN_ACTIVE).

---

## 6) Risk Management Gates (Hard Constraints)

> These gates must block publishing (and execution if enabled). The model can learn aggressiveness, but the system cannot violate safety constraints.

### 6.1 Margin and liquidation safety
- Enforce a margin safety buffer; block new risk if utilization exceeds threshold.
- Liquidation proximity gates:
  - If distance to liquidation is below threshold, either:
    - reduce exposure (preferred), or
    - hedge, or
    - block new exposure and signal risk-off

### 6.2 Drawdown circuit breaker
- If equity drawdown exceeds threshold over rolling window:
  - block new risk
  - force reduce leverage / exposure
  - enter recovery mode

### 6.3 Portfolio concentration and correlation caps
- Prevent stacking correlated exposure across symbols (directional concentration).
- MASA risk overlay may downscale PPO outputs if portfolio concentration rises.

### 6.4 Slippage and liquidity gates
- If spread widens beyond threshold or order book depth drops:
  - reduce size and/or block execution
  - annotate signals with LIQUIDITY_RISK

---

## 7) PPO + MASA Configuration Rules (Dynamic, No Static Per-Asset Wiring)

### 7.1 PPO rules
- PPO must support:
  - GPU training
  - VecEnv (parallel envs)
  - deterministic seeding for reproducibility
- Auto-tune rollout parameters within safe bounds:
  - enforce `rollout_batch = n_envs * n_steps` within LOOP_TIMESTEPS bound
  - do not exceed memory limits
- Inference must be batch-capable for throughput.

### 7.2 MASA rules
- MASA must be:
  - enabled/disabled via a flag
  - weighted dynamically (not hard-coded constant blending)
  - updated on a slower cadence than PPO (event-driven recommended)
- MASA output must be interpreted as a **risk/portfolio overlay** that can scale or adjust PPO action.

### 7.3 Dynamic blending requirement
- Blending must adapt to regime signals and recent performance.
- Must expose telemetry:
  - current blend weight
  - recent performance metrics used to compute the blend

---

## 8) Liquidation Intelligence Layer (Compute, Store, Train)

### 8.1 Inputs (expected sources)
- Binance: position/margin states, liquidation feed (where available), OHLCV
- CoinAnk: aggregated liquidation/positioning metrics
- KuCoin: supplemental metrics if enabled

### 8.2 Outputs (to Redis)
- Per symbol/timeframe liquidation features, e.g.:
  - long cluster distance
  - short cluster distance
  - liquidation intensity
  - margin stress index
- Store in `unified_features:{symbol}:{tf}` as prefixed fields to preserve schema stability.

### 8.3 Training integration
- Observations must include liquidation features.
- Reward shaping must include:
  - heavy penalty for liquidation events
  - penalty for approaching liquidation thresholds
  - reward for proactive de-risking/hedging near pressure points

---

## 9) Testing Plan (Extensive Validation Before Live)

### 9.1 Phase 0 — Static correctness
**Goal:** Ensure code imports and basic execution paths run.

Checklist:
- Import tests: `python -c "import hybrid_trainer"`
- Lint/type checks (if enabled in repo)
- Ensure no duplicate log handlers
- Confirm feature flags default to safe settings

Evidence:
- Save console output and logs.

### 9.2 Phase 1 — Local Redis integration (seeded data)
**Goal:** Prove the trainer reads unified features correctly and publishes signals in shadow mode.

Steps:
1) Start local Redis
2) Seed:
   - `unified_features:BTCUSDT:1h` and at least one additional symbol
   - include representative `ccxt_*`, `coinank_*`, `tm_*` fields
3) Seed price keys:
   - `market:{symbol}:1m` or `latest:binance:ohlcv:{symbol}:1m`
4) Run trainer with `TRAINER_MODE=shadow` and `ENABLE_PREFLIGHT=1`

Validate:
- Preflight passes
- No NaNs in observation vectors
- LEARNING_TIMEFRAMES excluded from publishing
- Debug stream includes filtered reasons

Evidence:
- Preflight report log
- Sample published signal payloads (shadow stream)
- Sample filtered signal payloads with reason codes

### 9.3 Phase 2 — GPU inference throughput test
**Goal:** Ensure GPU batch inference is stable and fast; no timeouts.

Steps:
- Enable batch inference path
- Run 10,000 inference cycles (no execution)
- Monitor:
  - GPU memory stability
  - RSS memory stability
  - absence of GPU timeouts

Evidence:
- Memory usage graphs/logs
- Trainer logs showing inference cycles complete without errors

### 9.4 Phase 3 — Training loop and checkpointing
**Goal:** Prove continuous training runs, checkpoints, resumes safely.

Steps:
- Run in training mode with a small loop interval in a safe environment
- Confirm:
  - checkpoints written every SAVE_EVERY_LOOPS
  - trainer resumes from latest checkpoint
  - incompatible checkpoints are rejected unless explicit override

Evidence:
- Checkpoint directory listing
- Resume logs showing compatibility verification
- Redis metrics keys updates

### 9.5 Phase 4 — Shadow live mode (real feeds, no execution)
**Goal:** Confirm live ingestion integration without execution risk.

Steps:
- Connect to Binance in non-executing mode
- Ensure portfolio sync is non-blocking; failure triggers fallback not hang
- Confirm unified features coverage thresholds in real conditions

Evidence:
- Preflight report showing coverage across all symbols/timeframes
- Signal stream samples with liquidation/risk fields populated

### 9.6 Phase 5 — Canary execution (post-audit only)
**Goal:** Minimal-risk live execution validation.

Rules:
- One symbol only
- Minimal notional size and leverage caps
- Strict slippage/spread gates
- Immediate rollback on anomalies

Evidence:
- Order logs including constraints evaluated
- Execution results vs expected

---

## 10) Monitoring and Operational Telemetry

### 10.1 Heartbeats and status
- `status:trainer` must be updated with TTL every loop
- Heartbeat key must be updated at fixed cadence
- Alert if heartbeat missing beyond threshold

### 10.2 Metrics (minimum)
- Training loop latency
- Inference latency
- Feature coverage %
- Data staleness by symbol/timeframe
- Signal publish count (accepted vs filtered)
- Error rate and last exception

### 10.3 Logging requirements
- Logs must include structured entries for:
  - preflight summary
  - each signal publish (accepted)
  - each signal filtered with reason codes
  - each training loop completion
  - each checkpoint save/load

---

## 11) Evidence Pack (What to Collect for Auditors)

Minimum artifacts for a 24-hour audit window:
1) Preflight report logs (startup)
2) Redis key coverage snapshot (all symbols/timeframes)
3) Sample unified feature rows (sanitized)
4) Sample signal payloads (accepted + filtered)
5) Trainer heartbeat/status timeline
6) Training checkpoints + manifest (config hash, schema version, obs_dim)
7) Error log excerpt (even if empty)
8) Any manual interventions (feature flags toggled) with timestamps

---

## 12) Rollback and Incident Procedure

### 12.1 Rollback triggers
- Preflight failure in live mode
- Data staleness above threshold
- Unexpected NaNs in observation vectors
- GPU timeout repeated
- Margin buffer breach or circuit breaker activation

### 12.2 Rollback actions (order)
1) Disable execution: `ENABLE_EXECUTION=0`
2) Switch to Shadow mode: `TRAINER_MODE=shadow`
3) Pin to last known-good checkpoint
4) Reduce environment parallelism if resource contention observed
5) Capture logs and Redis snapshot for investigation

### 12.3 Post-incident verification
- Confirm system stable in shadow mode
- Confirm preflight passes
- Re-enable training only after issue resolved
- Re-enable execution only after canary criteria met

---

## 13) Sign-Off Checklist (Go/No-Go)

### Go criteria for Shadow
- Preflight passes with required coverage threshold
- Signals publish correctly with complete payloads
- Filter reasons are present and sensible
- No stalls in Redis/GPU operations

### Go criteria for Training
- Stable training loop with checkpointing
- Resume works with compatibility checks
- Metrics and heartbeat stable

### Go criteria for Live Execution (post-audit only)
- Canary execution stable
- Risk gates proven effective
- Drawdown circuit breaker tested
- Slippage/liquidity gates tested
- Full evidence pack captured

---

## 14) Appendix: Standard Reason Codes (Filtered Signals)

- `LOW_CONFIDENCE`
- `LEARNING_TIMEFRAME`
- `DATA_STALE`
- `FEATURE_COVERAGE_LOW`
- `RISK_GATE_MARGIN`
- `RISK_GATE_LIQUIDATION_PROXIMITY`
- `RISK_GATE_DRAWDOWN`
- `RISK_GATE_CONCENTRATION`
- `LIQUIDITY_RISK`
- `COOLDOWN_ACTIVE`
- `MODEL_NOT_READY`
- `CHECKPOINT_INCOMPATIBLE`
- `DEPENDENCY_UNAVAILABLE`

---

**End of runbook.**
