# Expected Move Model Review And False Block Calibration

Generated: `2026-05-15T17:31:17Z`

GO/NO-GO: `V2_EXPECTED_MOVE_MODEL_REVIEW_READY_KEEP_GATE_STRICT`

This review keeps the strict paper fill gate active. Shadow outcomes are analysis-only; they do not authorize fills, live/canary trading, or legacy shutdown.

## Summary

- Completed shadow observations reviewed: `259`
- No-trade correct: `164` (`63.3%`)
- False blocks: `95` (`36.7%`)
- Safe threshold candidates found: `0`
- Recommended gate action: `KEEP_GATE_STRICT`
- Positive paper edge proven: `false`

The sample shows the gate is preventing many bad trades, but the expected-move model is not precise enough to loosen. Low-threshold proxy policies can catch some later winners, but precision is poor. The current 8 bps strict replay candidates were not safe enough in this preliminary window.

## False-Block Audit

| Dimension | Top counts |
| --- | --- |
| Symbol | `{'BTCUSDT': 95}` |
| Side | `{'short': 61, 'long': 34}` |
| Timeframe | `{'MISSING_IN_PAPER_EVENT': 95}` |
| Confidence bucket | `{'0.75_plus': 56, '0.65_to_0.75': 17, '0.58_to_0.65': 16, 'below_0.58': 6}` |
| Block reason | `{'loss_cooldown_active': 124, 'expected_edge_below_costs': 96, 'confidence_below_canary_threshold': 66, 'same_symbol_same_direction_cooldown': 16, 'expected_move_model_review_required': 10, 'deny_canary_profile_tightening': 7, 'deny_low_confidence': 6, 'missing_expected_move_after_costs': 2, 'flip_churn_cooldown': 2}` |
| Expected edge bucket | `{'negative': 53, '0_to_4': 16, '4_to_6': 5, '6_to_8': 5, '8_to_10': 5, '15_plus': 4, '12_to_15': 3, '10_to_12': 3, 'MISSING': 1}` |
| Feature freshness | `{'CURRENT': 95}` |
| Trainer source | `{'LEGACY_HYBRID_TRAINER_REDIS_READONLY': 94, 'V2_PAPER_TRAINER_WRAPPER': 1}` |

## Expected-Move Calibration

| Metric | Value |
| --- | --- |
| Expected-move sample count | `256` |
| Mean predicted expected_move_after_cost_bps | `1.975241` |
| Mean realized net_after_cost_bps | `2.917369` |
| Mean prediction error bps | `-0.942128` |
| Mean absolute error bps | `32.772005` |
| RMSE bps | `52.066362` |
| Barely beat costs | `7` |
| Moderately beat costs | `20` |
| Strongly beat costs | `68` |

Interpretation: `SOURCE_LIMITED_MIXED: low predicted edge sometimes produced strong later moves, while high predicted edge buckets also produced false allows in replay; do not loosen gate from this sample.`

## Threshold Replay

Threshold replay is source-limited and analysis-only. It uses completed shadow outcomes joined to paper events, not real fills. It cannot approve paper fills by itself.

| Cooldown mode | Edge bps | Confidence | Allowed proxy | False allows | Precision | Net bps proxy | Classification |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `60m_observed_strict` | `6` | `0.75` | `8` | `5` | `0.375` | `89.072309` | `UNSAFE_LOW_PRECISION` |
| `60m_observed_strict` | `6` | `0.6` | `9` | `6` | `0.333` | `79.325606` | `UNSAFE_LOW_PRECISION` |
| `60m_observed_strict` | `6` | `0.65` | `9` | `6` | `0.333` | `79.325606` | `UNSAFE_LOW_PRECISION` |
| `60m_observed_strict` | `6` | `0.7` | `9` | `6` | `0.333` | `79.325606` | `UNSAFE_LOW_PRECISION` |
| `60m_observed_strict` | `4` | `0.75` | `19` | `13` | `0.316` | `189.143202` | `UNSAFE_LOW_PRECISION` |
| `60m_observed_strict` | `4` | `0.7` | `20` | `14` | `0.300` | `179.396499` | `UNSAFE_LOW_PRECISION` |
| `60m_observed_strict` | `4` | `0.6` | `21` | `15` | `0.286` | `152.638594` | `UNSAFE_LOW_PRECISION` |
| `60m_observed_strict` | `4` | `0.65` | `21` | `15` | `0.286` | `152.638594` | `UNSAFE_LOW_PRECISION` |
| `60m_observed_strict` | `12` | `0.75` | `1` | `1` | `0.000` | `-9.052745` | `UNSAFE_LOW_PRECISION` |
| `60m_observed_strict` | `15` | `0.75` | `1` | `1` | `0.000` | `-9.052745` | `UNSAFE_LOW_PRECISION` |


Decision: `NO_GLOBAL_OR_SELECTIVE_THRESHOLD_CHANGE: no strict observed-cooldown policy has enough after-cost precision and sample size to authorize fills.`

## Cooldown Review

- loss_cooldown false blocks: `62`
- same-symbol same-direction cooldown false blocks: `8`
- flip/churn cooldown false blocks: `1`
- recommendation: `DO_NOT_REMOVE_GLOBAL_COOLDOWN: source has false blocks under cooldown but lacks enough post-fill lifecycle evidence to safely relax globally.`

## Confidence Review

- confidence evidence present after event join: `259`
- false blocks by confidence bucket: `{'0.75_plus': 56, '0.65_to_0.75': 17, '0.58_to_0.65': 16, 'below_0.58': 6}`
- no-trade correct by confidence bucket: `{'0.75_plus': 99, '0.65_to_0.75': 26, '0.58_to_0.65': 25, 'below_0.58': 14}`
- recommendation: `CONFIDENCE_CANNOT_AUTHORIZE_FILL: confidence bucket is reviewed only with expected edge, freshness, trainer source, symbol scope, cooldown, and risk gates.`

## Required Controller Behavior

- Keep `expected_move_model_review_required` holding paper fills until the expected-move model improves from native, non-hindsight evidence.
- Do not lower thresholds globally.
- Do not remove cooldown globally.
- Do not let confidence alone authorize a fill.
- Continue shadow outcome collection to larger 24h and 7d samples.

## Safety

| Check | Value |
| --- | --- |
| live_gate | `blocked_human_only` |
| live_symbols | `[]` |
| approves live | `false` |
| approves canary | `false` |
| approves legacy shutdown | `false` |
| old Redis write allowed | `false` |
| exchange mutation allowed | `false` |

## Decision

`V2_EXPECTED_MOVE_MODEL_REVIEW_READY_KEEP_GATE_STRICT`
