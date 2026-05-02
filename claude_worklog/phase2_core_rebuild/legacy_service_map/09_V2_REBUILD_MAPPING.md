# V2 Rebuild Mapping

| legacy category | V2 module lane | strategy |
|---|---|---|
| infra | runtime monitoring / audit | read-only evidence first |
| monitor | evidence packets + dashboard | preserve/replace without mutation |
| ingestor | legacy-compatible adapters | preserve, wrap, parity-test |
| market_data_bridge | symbol-aware adapters | preserve semantics first |
| feature_pipeline | feature snapshot pipeline | parity-critical, attribution after parity |
| trainer | trainer parity service | preserve GPU/hybrid behavior |
| orchestrator | decision service | lineage + risk-gateway routing |
| trader | trader fleet | paper/shadow before live |
| portfolio_monitor | readiness monitoring | no live actions |
| one_shot_validator | CI/readiness checks | local non-live validation |

V2_REBUILD_MAPPING_READY
