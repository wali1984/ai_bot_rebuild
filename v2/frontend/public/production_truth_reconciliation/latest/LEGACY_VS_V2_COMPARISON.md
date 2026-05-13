# Legacy vs V2 Comparison

Generated: 2026-05-13T04:43:38.228869Z

V2 reduces several known legacy risks in paper/shadow and control-plane logic, but live replacement remains incomplete.

| Failure mode | Classification | Legacy evidence | V2 control | Remaining blocker |
| --- | --- | --- | --- | --- |
| CROSS margin | still_blocking_live | legacy bridge observed pos_after.margin_type=cross | V2 canary profile requires isolated and blocks cross margin live mode | No live canary until account/margin status verified |
| excessive leverage | still_blocking_live | legacy pos_before observed leverage 30 in bridge evidence | V2 canary cap is 1x and ADJUST_LEVERAGE disabled | Need read-only account leverage verification |
| missing signal_id | fixed_in_v2_runtime | legacy/live streams can have incomplete attribution | V2 risk gate requires signal_id | Runtime test needs durable audit history |
| missing confidence | fixed_in_v2_runtime | legacy execution/trainer attribution gaps observed | V2 risk gate requires confidence | Keep trainer parity evidence current |
| duplicate exchange_order_id accounting | visible_but_not_fixed | legacy duplicate/execution accounting risk recorded | V2 risk gate includes duplicate_signal_execution and untraceable_execution | Need durable dedupe ledger before live |
| stale/late signals | fixed_in_v2_tests_only | legacy late execution risk observed | V2 risk gate includes stale_signal | Need 6h/24h stale-block proof |
| ADJUST_LEVERAGE risk | fixed_in_v2_runtime | legacy config/action surface contains leverage adjustment risk | V2 profile disables ADJUST_LEVERAGE and ADJUST_LEVERAGE_AND_POSITION | Human approval must not override without explicit profile change |
| stream naming confusion | visible_but_not_fixed | legacy Redis streams remain read-only source with naming ambiguity | V2 bridge normalizes lineage into pred/fs/sig/risk/intent IDs | Website must show current IDs on all relevant pages |
| hidden config | not_migrated | legacy configuration surface is broad and partly hidden | Config Admin support page exists with danger classifications from website rebuild | Need actual effective/staged setting store, not only page/report |
| incomplete execution lineage | still_blocking_live | legacy exchange_order evidence lacks full V2 lineage | V2 paper runtime requires prediction/feature/signal/risk/intent chain | Live execution ledger not enabled |
| stop/hedge/unwind ambiguity | still_blocking_live | legacy hedge/DCA/repair behavior not fully migrated | V2 canary disables hedge/DCA and requires stop policy | Full strategy migration still pending |
