# Script Migration CoinAnk Update Report

| Item | Value |
|---|---|
| backlog updated | `True` |
| updated paths | `feature_pipeline.py, ingest/coinank_pipeline_monitor.py, ingest/liquidation_bridge.py, ingest/liquidation_levels_engine.py, ingest/live_coinank.py, ingest/live_coinank_global_aggregator.py` |
| recommended action live_coinank.py | `wrap_readonly_then_port_to_v2` |
| recommended action coinank_pipeline_monitor.py | `preserve_monitor_then_port_to_v2_monitor_center` |
