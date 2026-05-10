# Redis Trim Dry-Run Plan

| key | type | current_memory_mb | stream_length | proposed_action | estimated_memory_reduction_mb | risk | required_approval |
| --- | --- | --- | --- | --- | --- | --- | --- |
| liquidations:events | stream | 12729.181 | 70928746 | DRY_RUN_OFFLOAD_THEN_XTRIM_MAXLEN_APPROX | 10183.344 | medium-high if offload is incomplete | human approval plus export/offload proof before XTRIM |
| signals:trading:primary | stream | 449.212 | 50000 | DRY_RUN_OFFLOAD_THEN_XTRIM_MAXLEN_APPROX | 359.37 | medium-high if offload is incomplete | human approval plus export/offload proof before XTRIM |
| wma:proposals | stream | 86.774 | 50000 | DRY_RUN_OFFLOAD_THEN_XTRIM_MAXLEN_APPROX | 69.419 | medium-high if offload is incomplete | human approval plus export/offload proof before XTRIM |
| features:coinank:indicators:1000FLOKIUSDT:Binance:spot:series | string | 80.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 40.0 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:liquidations:1000FLOKIUSDT:Binance:spot:series | string | 40.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 20.0 | medium | human approval for TTL policy; no immediate mutation |
| wma:exec_events | stream | 35.826 | 100010 | DRY_RUN_OFFLOAD_THEN_XTRIM_MAXLEN_APPROX | 28.661 | medium-high if offload is incomplete | human approval plus export/offload proof before XTRIM |
| wma:decisions | stream | 22.269 | 50007 | DRY_RUN_OFFLOAD_THEN_XTRIM_MAXLEN_APPROX | 17.815 | medium-high if offload is incomplete | human approval plus export/offload proof before XTRIM |
| features:coinank:fundflow:1000FLOKIUSDT:Binance:1h:series | string | 20.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 10.0 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:fundflow:1000FLOKIUSDT:Binance:1d:series | string | 20.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 10.0 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:fundflow:1000FLOKIUSDT:Binance:4h:series | string | 20.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 10.0 | medium | human approval for TTL policy; no immediate mutation |
| signals:ensemble:diagnostic | stream | 10.649 | 10015 | DRY_RUN_OFFLOAD_THEN_XTRIM_MAXLEN_APPROX | 0.016 | medium-high if offload is incomplete | human approval plus export/offload proof before XTRIM |
| features:coinank:advanced:1000PEPEUSDT:Binance:spot:series | string | 10.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 5.0 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:8h:series | string | 8.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 4.0 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:4h:series | string | 8.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 4.0 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:15m:series | string | 8.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 4.0 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:1d:series | string | 8.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 4.0 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:instruments:1000FLOKIUSDT:Binance:30m:series | string | 7.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.5 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:liquidations:1000FLOKIUSDT:Binance:1d:series | string | 7.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.5 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:instruments:1000FLOKIUSDT:Binance:15m:series | string | 7.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.5 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:instruments:1000FLOKIUSDT:Binance:1m:series | string | 7.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.5 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:instruments:1000FLOKIUSDT:Binance:8h:series | string | 7.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.5 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:instruments:1000FLOKIUSDT:Binance:1d:series | string | 7.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.5 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:instruments:1000FLOKIUSDT:Binance:1h:series | string | 7.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.5 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:instruments:1000FLOKIUSDT:Binance:4h:series | string | 7.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.5 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:instruments:1000FLOKIUSDT:Binance:5m:series | string | 7.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.5 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:1m:series | string | 6.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.0 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:1h:series | string | 6.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.0 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:5m:series | string | 6.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.0 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:liquidations:1000FLOKIUSDT:Binance:30m:series | string | 6.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.0 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:open_interest:1000FLOKIUSDT:Binance:30m:series | string | 6.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.0 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:liquidations:1000FLOKIUSDT:Binance:4h:series | string | 6.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.0 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:liquidations:1000FLOKIUSDT:Binance:1h:series | string | 6.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.0 | medium | human approval for TTL policy; no immediate mutation |
| features:coinank:liquidations:1000FLOKIUSDT:Binance:5m:series | string | 6.0 | 0 | DRY_RUN_SET_TTL_OR_MOVE_TO_FILE_DB | 3.0 | medium | human approval for TTL policy; no immediate mutation |
| executed_signals | stream | 5.897 | 1909 | DRY_RUN_OFFLOAD_THEN_XTRIM_MAXLEN_APPROX | 0.0 | medium-high if offload is incomplete | human approval plus export/offload proof before XTRIM |
