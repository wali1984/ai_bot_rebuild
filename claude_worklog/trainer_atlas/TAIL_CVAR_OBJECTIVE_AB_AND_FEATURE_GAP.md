# Tail-CVaR Objective A/B + Feature-Gap Reconciliation (2026-07-13)

## Tail-CVaR objective: does NOT break the -0.275 composite ceiling (REFUTED)

Env-gated `V2_TRAINER_TAIL_CVAR_WEIGHT` adds a differentiable penalty on the worst-tail
of the policy's expected directional return `(P(long)-P(short))*move/100`. A/B on the SAME
3200 held-out slice (temporal model, batch 512):

| metric    | baseline (w=0) | w=3.0    | w=0.5   |
|-----------|---------------:|---------:|--------:|
| Sortino   | 0.3467         | 0.1753   | 0.4177  |
| CVaR (bps)| -621.6         | -940.3   | -698.1  |
| composite | -0.2749        | -0.7650  | -0.2804 |

- w=3.0: everything WORSE (over-focused on tail rows, destabilised training).
- w=0.5: Sortino UP (+0.07) but CVaR WORSE (-76) -> composite FLAT.
- Verdict: the penalty does NOT reduce CVaR. Root cause: the surrogate penalises the
  policy-PROBABILITY-weighted tail, but realised CVaR is over ARGMAX trades. Reducing the
  prob-weighted tail just makes the policy more confidently directional (Sortino up)
  without clipping the realised argmax tail (CVaR unchanged/worse). Formulation mismatch.
- Kept the code (env-gated, DEFAULT OFF, byte-identical) as a Sortino lever (w~0.5 gives
  +20% Sortino), but it is NOT the composite-ceiling fix. Reports:
  temporal_cvar_report.json (w=3.0), temporal_cvar05_report.json (w=0.5, best_epoch 3).
- A correct tail objective would need a differentiable ARGMAX-tail surrogate
  (Gumbel-softmax / straight-through) -- deferred; features is the higher-value lever.

## Feature-gap reconciliation: the "97.5% loss" figure is STALE

The 2026-07-08 CoinAnk audit's "97.5% feature loss (562->14)" measured an OLD
`v2:unified_features` 14-field vector. The CURRENT trainer does NOT use that -- it uses a
hardcoded 312-entry `FEATURE_SPEC` in `tensor_builder.py:17-337` (model_vector = 312*4 =
1248, asserted at runtime.py:833).

Correct current picture:
- V2 now: **312 base features** (~303 unique -- 9 duplicate names: santiment_*,
  public_intel_score, whale_wall_score, lunarcrush_score waste vector slots).
- Legacy: 562 fields = 160 TA + 140 CoinAnk + 80 microstructure + 60 regime/toxicity +
  122 derived.
- Real gap: 312 vs 562 (~44% fewer), concentrated in **TA (160 legacy vs ~11 explicit in
  V2)** and **microstructure (80 vs ~19)**. Many of V2's 312 are chronically EMPTY when
  optional alt-data providers (santiment/moralis/confluence/nansen/lunarcrush/aicoin/
  whale_walls, ~80 features) aren't publishing.

## Next lever: EXPAND THE TA FEATURE BLOCK (biggest controllable gap)

TA indicators are computable from OHLCV (no external provider), so this is the most
controllable, self-contained edge lever. Insertion (per feature-map investigation):
1. Append `(name, source)` entries to `FEATURE_SPEC` (append-only for lineage).
2. Populate values in the tensor_builder build body (or via `v2:features:ta` / latest).
3. Ensure the source Redis key is loaded in `data_loader.py` (~790-919).
4. input_dim is dynamic (runtime.py:488-490) -- BUT changing the count changes
   `arch_identity` (model.py:108) -> NEW checkpoint lineage -> full offline retrain.
Quick win first: de-duplicate the 9 redundant feature names.

## RESULT: TA feature expansion WORKS — best composite yet (2026-07-13)

Wired 155 TA-Lib indicators (98 continuous + 57 candlesticks) from v2:features:ta_full
into FEATURE_SPEC as taf_* features (312->458, model_vector 1248->1832; commit dd10b777ff).
Retrained temporal offline on the expanded input (fresh 1832-dim lineage, batch 512, 30
epochs early-stop, best_epoch 12). Same eval methodology + same underlying market data:

| metric    | incumbent | temporal (1248) | temporal + TA (1832) |
|-----------|----------:|----------------:|---------------------:|
| Sortino   | 0.140     | 0.347           | **0.4511**           |
| CVaR (bps)| -647.9    | -621.6          | **-543.8**           |
| composite | -0.508    | -0.275          | **-0.0927**          |
| trades    | 3136      | 1991            | 2130                 |

Report: claude_worklog/trainer_atlas/temporal_feat_report.json. Checkpoint:
.local_models/v2_native_rl_masa_ppo_temporal_feat.

- Unlike the tail-CVaR objective (Sortino up / CVaR down), richer TA input improved BOTH
  Sortino AND CVaR -> composite -0.275 -> -0.093 (+0.182, ~66% of the way to positive).
- The levers COMPOUND: incumbent -0.508 -> +temporal -0.275 -> +TA-features -0.093.
- Composite still slightly negative but CLOSE. Next levers to cross zero: (a) wire the
  OTHER big gap -- microstructure (80 legacy vs ~19 V2); (b) more feature families;
  (c) the ta_full data was verified present for all 155 features in the replay archive.
- CONFIRMED: features are the highest-value edge lever (matches the user's "both" plan).

## Safety
Offline training + read-only eval only. No deploy, no promotion, no order, no service
restart. Deployment remains BLOCKED (blocked_human_only).
