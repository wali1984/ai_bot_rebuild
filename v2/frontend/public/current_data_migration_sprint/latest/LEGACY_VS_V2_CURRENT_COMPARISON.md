# Legacy Vs V2 Current Comparison

| legacy failure mode | legacy evidence | V2 control | classification | GUI route |
|---|---|---|---|---|
| CROSS margin | legacy live stack previously allowed/required review | risk gateway can block cross margin; live remains disabled | fixed_in_v2_tests_only | Live Readiness / Risk Control |
| excessive leverage | legacy stack had leverage risk | ADJUST_LEVERAGE disabled; leverage cap remains human approval | fixed_in_v2_tests_only | Live Readiness |
| missing signal_id | legacy observed events can miss lineage | execution_attribution_normalizer blocks missing signal_id | fixed_in_v2_runtime | /admin/executions |
| missing confidence | legacy signal confidence may be missing | paper wrapper exposes confidence; risk gateway required blocks list includes missing_confidence | visible_but_not_fixed | /admin/signals |
| duplicate exchange_order_id accounting | legacy exchange_order_id evidence exists read-only | execution_attribution_normalizer detects duplicates from seen order IDs | fixed_in_v2_runtime | /admin/executions |
| stale/late signals | legacy events can be delayed | normalizer and risk gateway stale checks visible | fixed_in_v2_runtime | /admin/risk-control |
| ADJUST_LEVERAGE risk | legacy risk mode can change leverage | dangerous controls disabled; V2 live gate blocked | fixed_in_v2_tests_only | /admin/live-readiness |
| incomplete execution lineage | legacy execution can lack prediction/feature IDs | current_signal_lineage_adapter + PageShell expose complete current lineage | fixed_in_v2_runtime | /admin/signal-explainability |
