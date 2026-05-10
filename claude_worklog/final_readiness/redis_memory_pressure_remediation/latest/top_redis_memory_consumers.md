# Top Redis Memory Consumers

| key | type | memory_mb | stream_length | ttl_seconds | namespace | criticality | likely_producer | likely_consumer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| liquidations:events | stream | 12729.181 | 70928746 | -1 | market_liquidation_history | feature/audit-history | unknown producer - review before mutation | unknown consumer - review before mutation |
| signals:trading:primary | stream | 449.212 | 50000 | -1 | live_signal_transport | live-critical | legacy orchestrator/trainer signal path | legacy trader/orchestrator consumers |
| wma:proposals | stream | 86.774 | 50000 | -1 | live_signal_transport | live-critical | legacy orchestrator/trainer signal path | legacy trader/orchestrator consumers |
| features:coinank:indicators:1000FLOKIUSDT:Binance:spot:series | string | 80.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:liquidations:1000FLOKIUSDT:Binance:spot:series | string | 40.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| wma:exec_events | stream | 35.826 | 100010 | -1 | live_execution_feedback | live-critical/audit | unknown producer - review before mutation | unknown consumer - review before mutation |
| wma:decisions | stream | 22.269 | 50007 | -1 | live_execution_feedback | live-critical/audit | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:fundflow:1000FLOKIUSDT:Binance:1h:series | string | 20.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:fundflow:1000FLOKIUSDT:Binance:1d:series | string | 20.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:fundflow:1000FLOKIUSDT:Binance:4h:series | string | 20.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| signals:ensemble:diagnostic | stream | 10.649 | 10015 | -1 | monitor_telemetry | monitoring | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:advanced:1000PEPEUSDT:Binance:spot:series | string | 10.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:8h:series | string | 8.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:4h:series | string | 8.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:15m:series | string | 8.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:1d:series | string | 8.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:instruments:1000FLOKIUSDT:Binance:30m:series | string | 7.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:liquidations:1000FLOKIUSDT:Binance:1d:series | string | 7.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:instruments:1000FLOKIUSDT:Binance:15m:series | string | 7.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:instruments:1000FLOKIUSDT:Binance:1m:series | string | 7.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:instruments:1000FLOKIUSDT:Binance:8h:series | string | 7.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:instruments:1000FLOKIUSDT:Binance:1d:series | string | 7.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:instruments:1000FLOKIUSDT:Binance:1h:series | string | 7.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:instruments:1000FLOKIUSDT:Binance:4h:series | string | 7.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:instruments:1000FLOKIUSDT:Binance:5m:series | string | 7.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:1m:series | string | 6.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:1h:series | string | 6.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:5m:series | string | 6.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:liquidations:1000FLOKIUSDT:Binance:30m:series | string | 6.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:30m:series | string | 6.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:liquidations:1000FLOKIUSDT:Binance:4h:series | string | 6.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:liquidations:1000FLOKIUSDT:Binance:1h:series | string | 6.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:liquidations:1000FLOKIUSDT:Binance:5m:series | string | 6.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| executed_signals | stream | 5.897 | 1909 | -1 | live_execution_feedback | live-critical/audit | legacy trader/execution feedback | audit, reward, trainer feedback, dashboard |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:spot:series | string | 1.5 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:advanced:1000SHIBUSDT:Binance:spot:series | string | 1.5 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:advanced:ASTERUSDT:Binance:spot:series | string | 1.5 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:funding:1000FLOKIUSDT:Binance:spot:series | string | 1.5 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:advanced:WIFUSDT:Binance:spot:series | string | 1.25 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:advanced:1000BONKUSDT:Binance:spot:series | string | 1.25 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:long_short:1000FLOKIUSDT:Binance:1h:series | string | 1.25 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:long_short:1000FLOKIUSDT:Binance:5m:series | string | 1.25 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| coinank:fundingRate_current:last | string | 1.25 | None | 568 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| raw:coinank:fundingRate_current:global | string | 1.25 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:advanced:ASTERUSDT:Binance:1h:series | string | 1.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:advanced:XRPUSDT:Binance:1h:series | string | 1.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:advanced:UNIUSDT:Binance:spot:series | string | 1.0 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:advanced:LINKUSDT:Binance:1h:series | string | 0.875 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:advanced:ETHUSDT:Binance:spot:series | string | 0.875 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:advanced:LINKUSDT:Binance:spot:series | string | 0.875 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:advanced:BTCUSDT:Binance:spot:series | string | 0.875 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:advanced:BTCUSDT:Binance:1h:series | string | 0.875 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:advanced:DOGEUSDT:Binance:spot:series | string | 0.875 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:advanced:AVNTUSDT:Binance:1h:series | string | 0.875 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:market_order_flow:1000FLOKIUSDT:Binance:1h:series | string | 0.75 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:market_order_flow:1000FLOKIUSDT:Binance:5m:series | string | 0.75 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:market_order_flow:1000FLOKIUSDT:Binance:15m:series | string | 0.75 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:market_order_flow:1000FLOKIUSDT:Binance:4h:series | string | 0.75 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:open_interest:1000SHIBUSDT:Binance:15m:series | string | 0.75 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |
| features:coinank:market_order_flow:1000FLOKIUSDT:Binance:8h:series | string | 0.75 | None | -1 | feature_cache | cache | unknown producer - review before mutation | unknown consumer - review before mutation |

Showing 60 of 100 rows. Full data is in JSON.
