# Copilot / Codex Work Instructions — Aligning V2 with the DL-Crypto Systematic Review

**Author:** Claude Code (review pass, 2026-07-12)
**Source paper:** Ataei et al., *"Applications of Deep Learning to Cryptocurrency Trading: A Systematic Analysis"* (TechRxiv preprint, 3 Feb 2026 — **not peer reviewed**).
**Scope:** what to change, what NOT to change, and how to do it without breaking working paper/shadow runtime or violating CLAUDE.md.
**Status of live trading:** BLOCKED (must stay blocked). Every item here is paper/shadow only.

---

## 0. How to read the paper (read this first)

The paper is a **meta-review of ~75 price-prediction / RL papers**, not an experimental result on our data. Treat it exactly as CLAUDE.md treats Ollama output: **navigation aid, not evidence.** Two consequences:

- **Do NOT chase its headline numbers** (e.g. "PPO agent 341% profit", "114% in a month"). The paper *itself* warns these come from simulated/idealized backtests that "ignore transaction costs", use "finite data samples", and "may not generalize to live trading." The authors repeatedly flag crypto as **near-random-walk** where DL gives only **incremental** gains. Our edge gates already reflect this reality (memory: ~94% of blocks are correct; the fix is a better model, not looser gates).
- **The value is methodological alignment**, verified out-of-sample on *our* archive — not reproducing anyone's return figure.

The paper's robust, transferable conclusions (ranked by how much they apply to an **RL trading agent** like ours, not a price-regressor):

| Paper finding | Applies to us? | Our current state |
|---|---|---|
| Sequential models (LSTM/GRU/Bi-LSTM) + temporal attention capture time dependence, beat flat models | **YES — biggest gap** | Model is a **flat per-step MLP, no time axis** (verified). Legacy had LSTM+attention. |
| Risk-adjusted RL objectives (Sortino/CVaR) beat raw-return; lower drawdown | **YES** | Sortino/CVaR/Sharpe exist only in *eval* services, **not** in reward or promotion (verified). |
| Ensembles (avg/bag/stack) reduce variance, improve robustness | **YES** | Single model + CPU fallback. No ensemble. |
| External data (sentiment, on-chain, macro) improves prediction | **MOSTLY DONE** | 318 features incl. LunarCrush/Santiment/Nansen/Moralis/whale-walls (verified). |
| XAI / feature attribution for trust | **PARTLY DONE** | Signal Explainability + calibration exist; no per-feature attribution. |
| Evaluate with cost-aware, risk-adjusted, realistic backtests | **DONE** | Reward is cost-aware; edge-proof/replay backtest runner exist. |

**Net:** most of the paper's data recommendations we already satisfy. The two genuine, high-value, paper-supported gaps are **(1) temporal state encoding** and **(2) risk-adjusted training/promotion objective.** Everything else is refinement.

---

## 1. Non-negotiable guardrails (violating any = stop)

1. **Never mutate the protected trainer venv.** No `pip install`, no torch/CUDA upgrade. Everything below is buildable with **core torch already present**: `nn.GRU`, `nn.LSTM`, `nn.Conv1d`, `nn.TransformerEncoder`, `nn.MultiheadAttention`. If a task seems to need a new dependency, it is the wrong task.
2. **Never replace the working path.** Follow the existing pattern in `hybrid_cuda_trainer/model.py`: every new capability is **env-gated, OFF by default, and the disabled path must be byte-for-byte identical** to today's residual-MLP. See how `V2_TRAINER_ATTENTION_ENCODER` is wired (arch-identity string + graceful fresh-init) — copy that discipline exactly.
3. **Architecture changes start a fresh checkpoint lineage.** Encode any new arch flag into the `arch_identity` hash (model.py:86) so old blobs don't silently load into a new shape. The checkpoint manager already treats shape/arch change as graceful fresh init — keep it that way.
4. **Never loosen an edge gate to raise win-rate.** `preemptive_edge_control` and the confidence gates are calibrated. Improvements come from a better model producing better inputs, not from relaxing `loss_probability.py` / `decision.py` thresholds.
5. **Live stays BLOCKED.** No live symbols, no order paths, no leverage/margin mutation. Paper/shadow only. `reward_stack_status()` must keep `live_gate: blocked_human_only`.
6. **Promotion is out-of-sample or it doesn't happen.** No new model path may be promoted on in-sample metrics. Gate on the existing `edge_proof` / `replay_backtest_runner` with a train/val/test split. In-sample edge that collapses out-of-sample is the exact failure the dropout bump was fighting (model.py:56-58).
7. **Coordinate with the two active Codex agents.** Agent 1 works trainer/win-rate and touches `v2_trade_management_paper_loop.py`; Agent 2 works frontend/iOS. Keep temporal/ensemble work inside `native_trainer/hybrid_cuda_trainer/**` and `app/cli/v2_trainer_offline_*` to avoid collisions. Do not edit the paper-loop or frontend as part of these tasks.
8. **Every change is reversible via a single env flag** and leaves a worklog entry with the raw before/after edge-proof numbers.

---

## 2. Prioritized work items

Each item lists: rationale, **data alignment** (why our existing data supports it — no new collection), safety/gating, files, and acceptance criteria.

### WI-1 — Temporal state encoder (offline-first, env-gated) — HIGHEST VALUE

**Rationale.** The paper's single most consistent finding across 75 studies: models with a time axis (GRU/LSTM/temporal-attention/TCN) beat flat models on non-linear, sequential crypto data. Our active model has **no time dimension** — it sees one snapshot per decision. Legacy had an LSTM+attention backbone. This is the largest paper-supported gap and directly matches the memory note that the fix direction is *"historical replay/backtest training to build a persistent brain."*

**Data alignment (critical — do this before any modeling).** We already store what's needed; we are **not** collecting new data:
- `data_loader.py` already reconstructs **closed multi-timeframe candle series** (`_closed_candle_series_from_raw`, snapshots over 1m/5m/15m/1h/4h) with decision-time lineage/masks.
- The ~1.7M-row replay archive is the training vehicle.
- **Task:** add a *windowing adapter* that emits, per decision, a `(seq_len, feature_dim)` tensor built from the last `seq_len` closed snapshots ending at (and inclusive of) the decision candle — reusing the exact same `FeatureTensorRecord` per step so masks/lineage are preserved. **No lookahead:** the window must end at the decision candle close, never past it (the loader already enforces closed-candle discipline — do not weaken it).
- Keep `seq_len` **modest (start 16, cap 32).** The trainer's documented failure mode is *data starvation* (GPU underutilized, rows starved). A long window multiplies rows-per-sample and will re-starve it. Short window + the offline batch trainer (98% GPU on the archive) is the safe combination.

**Model.** Start with **GRU** (paper: GRU often ties/beats LSTM and trains faster/cheaper), as an optional pre-encoder that consumes `(B, seq_len, feature_dim)` and outputs `(B, feature_dim')` feeding the existing `input_projection`. Mirror the attention-encoder wiring:
- `V2_TRAINER_TEMPORAL_ENCODER` ∈ `{off, gru, tcn}` (default `off`).
- `V2_TRAINER_TEMPORAL_SEQ_LEN` (default 16).
- When `off`, the forward path and tensor shapes are **identical to today** (still accepts flat vectors; single-row callers unaffected).
- Add `temporal=gru:seq16` to `arch_identity` so it forks checkpoint lineage.
- TCN (`nn.Conv1d` stack) is a fast second option; TFT/Transformer is explicitly **deferred** (heaviest, most starvation-prone — only after GRU proves out).

**Where it trains.** `app/cli/v2_trainer_offline_batch_train.py` on the archive, NOT the resident online loop first. The online loop stays on the current MLP until the temporal model wins out-of-sample in shadow.

**Files.** `hybrid_cuda_trainer/model.py` (encoder + flag), `hybrid_cuda_trainer/tensor_builder.py` or a new `sequence_window.py` (windowing adapter), `hybrid_cuda_trainer/data_loader.py` (emit sequences when flag on), `cli/v2_trainer_offline_batch_train.py` (build `(seq_len, feat)` examples), plus unit tests mirroring `test_hybrid_policy_model_action_selection.py`.

**Acceptance.** Out-of-sample edge-proof (val + held-out test) **≥ current MLP** on after-cost expectancy AND calibration not degraded AND gate-correctness not regressed; shadow-compare vs MLP for a full soak before any promotion; disabled-path test proves byte-identical behavior with flag off. If it does not beat the MLP out-of-sample, **leave the flag off and record the negative result** — a null result here is a valid, expected outcome given the near-random-walk caveat.

---

### WI-2 — Risk-adjusted training + promotion objective (Sortino / CVaR)

**Rationale.** The paper's DRL section: Sortino-optimized and CVaR-optimized agents beat buy-and-hold with **lower downside**, which is exactly CLAUDE.md's priority order (survival → liquidation avoidance → controlled drawdown, and "reject high-win-rate strategy if tail losses can erase gains"). Our reward (`hybrid_cuda_trainer/rewards.py`) is cost-aware per-step but has **no trajectory-level tail/downside term**, and checkpoint promotion does **not** consult Sortino/CVaR (verified). Yet those metrics already exist in `edge_proof/`, `adaptive_capital_allocator/`, `strategy_router/reporting.py`.

**Data alignment.** Nothing new — consume metrics already computed by existing evaluators over paper outcomes.

**Two sub-tasks, both additive/stricter (never loosen):**
1. **Promotion gate (do first, lowest risk):** in checkpoint promotion, add an *additional* pass condition on out-of-sample **Sortino ≥ threshold** and **CVaR(5%) tail-loss ≤ bound**. This can only make promotion stricter; a candidate that fails is not promoted. No reward change, no runtime change.
2. **Reward shaping (env-gated, second):** add a small, env-weighted trajectory downside-penalty term (Sortino/CVaR-style) to the reward stack, `V2_TRAINER_RISK_ADJUSTED_REWARD` default off. Validate in the offline trainer + shadow that it reduces tail loss without collapsing trade count to zero. Keep the existing per-step components unchanged when the flag is off.

**Files.** `rl_core/checkpoint_promotion.py` (gate), `hybrid_cuda_trainer/rewards.py` (optional term), reuse `edge_proof`/`adaptive_capital_allocator` metric functions. Tests for both.

**Acceptance.** Promotion gate: demonstrably blocks a synthetic high-win-rate/fat-tail checkpoint. Reward term: shadow run shows lower CVaR tail loss and non-degenerate trade frequency; flag-off path unchanged.

---

### WI-3 — Shadow ensemble → disagreement-as-uncertainty gate

**Rationale.** The paper is emphatic that ensembles (averaging/bagging/stacking) cut variance and improve robustness. We run a single model. The *safest* way to use an ensemble here is not to boost aggressiveness but to **detect disagreement as a tail-risk signal** — a natural fit with the existing `confidence_overstatement.py` block.

**Data alignment.** Train N (3–5) diverse seeds/architectures via the **offline** batch trainer on the same archive (already supported — `V2HybridPolicyModel(input_dim=...)` per run). No new data.

**Design (shadow only).**
- Ensemble mean of action probabilities = shadow signal; **variance/disagreement across members = uncertainty score.**
- Feed uncertainty into confidence *calibration only* (raise the effective confidence floor when models disagree). It may make the system **more** conservative, never less. It must **not** override `preemptive_edge_control` or the risk gateway.
- Live/online path keeps using the single promoted model until an ensemble is proven and explicitly promoted.

**Files.** New `hybrid_cuda_trainer/ensemble.py` (offline aggregation + disagreement), wire disagreement into `confidence.py` behind `V2_TRAINER_ENSEMBLE_UNCERTAINTY` (default off). Tests.

**Acceptance.** Shadow: high-disagreement decisions have measurably worse realized outcomes than low-disagreement ones (proving the signal is real); enabling the gate reduces bad trades without zeroing volume.

---

### WI-4 — Feature attribution / XAI export (additive, read-only)

**Rationale.** The paper's XAI theme (SHAP-style attribution) and — more practically — a **cheap way to verify WI-5**: are the alt-data features (sentiment/on-chain) we already pay for actually carrying weight, or are they dead inputs the model ignores?

**Design.** Add a periodic **permutation-importance** (or gradient×input) export over recent decisions, published to the Signal Explainability surface. Read-only; changes no decision. Reuses existing forward pass.

**Files.** New `hybrid_cuda_trainer/feature_attribution.py` + a publisher key under the existing explainability plumbing. No runtime decision changes.

**Acceptance.** Produces a ranked feature-importance table; no change to any decision, gate, or reward.

---

### WI-5 — Verify external data is *consumed*, not just present (diagnostic, not a build)

**Rationale.** The paper says external data (sentiment/on-chain/macro) improves models. We already ingest it (LunarCrush, Santiment, Nansen, Moralis, whale-walls, CoinGlass). The risk — consistent with memory notes on staleness/zero-masking — is that these features are **stale or zero-masked at decision time**, so the paper's benefit is unrealized. This is a **diagnostic task**, not new integration.

**Task.** Report, over recent decision rows: per-alt-data-feature non-null/non-stale rate and (via WI-4) its attribution weight. If a feature is chronically stale/zero, fix the *freshness pipeline* for it — do **not** add a new provider (memory: recommendation was CoinGlass only, not Moralis/Nansen expansion; macro/S&P/VIX/gold from the paper are **not** a fit for a 24/7 perp microstructure agent and are out of scope).

**Acceptance.** A freshness+attribution report for alt-data features; any fix is to freshness, gated and evidenced.

---

## 3. Explicit anti-patterns (do NOT do these)

- ❌ Add a standalone LSTM **price predictor** that runs beside the RL agent. The paper's price-regression results (RMSE on daily BTC) don't transfer to our RL/microstructure setting; a second predictor that doesn't feed the state is duplicated surface area and drift risk. Temporal modeling belongs **inside the policy's state encoder** (WI-1), not as a bolt-on forecaster.
- ❌ Import macro series (S&P/VIX/gold/Google Trends) from the paper. Wrong horizon and cadence for a 24/7 perp agent; out of scope.
- ❌ Loosen `loss_probability.py`, `decision.py`, or confidence floors to lift win-rate.
- ❌ Enable any new arch/ensemble/reward flag in the **online resident trainer** before it wins out-of-sample in the **offline + shadow** path.
- ❌ Add pip deps or touch the protected venv.
- ❌ Promote on in-sample metrics.
- ❌ Edit `v2_trade_management_paper_loop.py` or frontend/iOS as part of these tasks (active Codex agents own them).
- ❌ Treat any paper return figure as a target or acceptance threshold.

---

## 4. Recommended sequence

1. **WI-5 diagnostic** (hours) — cheap, tells us if alt-data is even alive before we invest in modeling.
2. **WI-2 promotion gate** (small, additive, immediate downside protection).
3. **WI-1 temporal encoder** (the big one; offline-first, GRU, seq_len 16, shadow-compare). Largest expected payoff, largest care required.
4. **WI-4 attribution** (supports WI-1/WI-3 evaluation).
5. **WI-3 ensemble uncertainty gate**.
6. **WI-2 reward term** last (only after temporal model is stable, to avoid confounding two changes).

Each step: one bounded change → offline edge-proof → shadow soak → worklog entry with raw before/after numbers → only then consider the next. Never stack two unproven changes at once (non-stationarity makes attribution impossible).

---

## 5. One-paragraph summary for the operator

The paper mostly *confirms what we already built* (rich external + on-chain + microstructure data, cost-aware reward, realistic backtesting). Its two real, safe, high-value gaps for us are: **(1)** our model has no time dimension — add an env-gated, offline-trained **GRU state encoder** over the closed-candle windows we already archive, and only promote it if it beats the flat MLP out-of-sample; and **(2)** our reward/promotion ignores tail risk — wire the **Sortino/CVaR** metrics we already compute into a *stricter* promotion gate (and optionally a small reward term). Ensembles-for-uncertainty and feature-attribution/XAI are worthwhile refinements. Everything stays paper/shadow, env-gated OFF by default, reversible, on core torch, with live BLOCKED — and we ignore the paper's headline profit numbers, which its own authors call non-generalizable.

#### IMP: BELOW TEXT IS AND  CAN ONLY BE TOUCHED AFTER ABOVE IS FULLY COMPLETED and VALIDATED
he status is stuck on the 05:34:14 cold-start cycle (~2 min, no new cycle) — cycles are slow because that one data build was 134s. Let me give you the honest, complete picture, because there's an important reframe here.

The win is holding — that was the priority
The trainer is durably learning now: WEIGHTS_UPDATING, REPLAY_AND_ONLINE_LEARNING, val improving, checkpoint promoted. The INFERENCE_ONLY deadlock that was blocking A-grade is fixed.

The GPU — honest diagnosis + a reframe
The 134s you saw is a one-time cold-start: my restart emptied the resident replay buffer, so the synchronous historical backfill ran to refill it (15,560 rows). The buffer is now full (16384), so that won't repeat — it's already not the steady state.
But the deeper truth I've been consistent about: the online loop is data-build-bound by design (it reads Redis/archive + builds features each cycle), so its GPU will always be low. That's not a bug to chase on the online loop.
The reframe that resolves this correctly: you don't need the online loop to saturate the GPU. The efficient architecture — which we now have — is exactly the legacy pattern:

Offline historical pretrain = 98% GPU, 46k rows/s → builds the brain fast (heavy GPU work).
H2L promotion → transfers that generalizing brain to the online loop.
Online loop = gentle refinement (low GPU is fine and expected — it's keeping the model current on fresh data, not doing the heavy lifting).
So the GPU is being used hard where it matters (the pretrain). If you want continuous heavy GPU training, the answer isn't to force the online loop to 98% — it's to run periodic offline pretrains (98% GPU) + H2L-promote on a schedule. Both tools now exist and self-gate.

What I'd do next 
Optional online speed-up (real but a careful loop change): extend the background prefetcher to build the whole next-cycle dataset while the GPU trains, so the online cycle stops blocking on the data build. It's genuine, but it touches the loop that just started durably learning — so I'd do it deliberately, validated, not under pressure.
Schedule periodic offline pretrain + auto H2L (safe, additive): a timer that re-pretrains (98% GPU) and promotes only when it beats live on the disjoint held-out set — keeps the brain improving with the GPU fully used, without touching the online loop.
