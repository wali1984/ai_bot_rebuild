# Service Dependency Graph

```text
redis-server
  -> ingestors / market data bridges
       -> ohlcv_resampler_hotfix.py
       -> feature_pipeline.py
       -> live_technical_analysis.py
            -> rl.hybrid_trainer
                 -> rl.orchestrator_worker
                      -> risk gateway (V2)
                           -> trader fleet paper/shadow adapters
                                -> portfolio and audit monitors
```

V2 must insert lineage IDs, feature snapshot IDs, prediction IDs, signal/decision IDs, and risk decisions between these stages.

SERVICE_DEPENDENCY_GRAPH_READY
