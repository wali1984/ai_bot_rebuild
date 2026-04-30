# Ingestor / Feature Key Map (Read-Only)

Generated from coverage artifacts; key patterns are evidence-backed where available and explicitly marked when inferred.

## Binance market data
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| depth:{cfg} | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "depth" | head -20` | no | no | High |
| orderbook:bids:{cfg} | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "orderbook" | head -20` | no | no | High |
| orderbook:asks:{cfg} | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "orderbook" | head -20` | no | no | High |
| heartbeat:OrderBook:{cfg} | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "heartbeat" | head -20` | yes | no | High |
| heartbeat:OrderBook:{sym} | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "heartbeat" | head -20` | yes | no | High |
| market:{sym}:oi | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "market" | head -20` | no | no | High |
| oi:{sym}:spot | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "oi" | head -20` | no | no | High |
| oi:{sym} | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "oi" | head -20` | no | no | High |
| market:{sym}:premium_index | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "market" | head -20` | no | no | High |
| mark_price:{sym} | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "mark_price" | head -20` | no | no | High |
| index_price:{sym} | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "index_price" | head -20` | no | no | High |
| premium_index:{sym} | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "premium_index" | head -20` | no | no | High |
| market:{sym}:funding | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "market" | head -20` | no | no | High |
| funding:{sym}:8h | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "funding" | head -20` | no | no | High |
| funding:{sym} | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "funding" | head -20` | no | no | High |
| market:{sym}:{tf} | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "market" | head -20` | no | no | High |
| price:{sym} | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "price" | head -20` | no | no | High |
| price:last:{sym} | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "price" | head -20` | no | no | High |
| volatility:{sym} | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "volatility" | head -20` | no | no | High |
| spark:{sym} | ingest/live_binance.py | redis_write | `redis-cli --scan | grep -E "spark" | head -20` | no | no | High |
| heartbeat:writer | ingest/live_binance.py | redis_unknown | `redis-cli TYPE "heartbeat:writer" && redis-cli TTL "heartbeat:writer"` | yes | no | Medium |
| heartbeat:IngestBinance | ingest/live_binance.py | redis_write | `redis-cli TYPE "heartbeat:IngestBinance" && redis-cli TTL "heartbeat:IngestBinance"` | yes | no | High |
| lock:live_binance | ingest/live_binance.py | redis_write | `redis-cli TYPE "lock:live_binance" && redis-cli TTL "lock:live_binance"` | no | no | High |
| proc:last_error:IngestBinance | ingest/live_binance.py | redis_write | `redis-cli TYPE "proc:last_error:IngestBinance" && redis-cli TTL "proc:last_error:IngestBinance"` | no | no | High |

## Binance liquidations
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| debug:binance_liquidations:counters | ingest/live_binance_liquidations.py | redis_write | `redis-cli TYPE "debug:binance_liquidations:counters" && redis-cli TTL "debug:binance_liquidations:counters"` | no | no | High |
| heartbeat:IngestLiquidations | ingest/live_binance_liquidations.py | redis_write | `redis-cli TYPE "heartbeat:IngestLiquidations" && redis-cli TTL "heartbeat:IngestLiquidations"` | yes | no | High |
| debug:binance_liquidations:status | ingest/live_binance_liquidations.py | redis_write | `redis-cli TYPE "debug:binance_liquidations:status" && redis-cli TTL "debug:binance_liquidations:status"` | no | no | High |
| liq:agg:{w}s | ingest/live_binance_liquidations.py | redis_write | `redis-cli --scan | grep -E "liq" | head -20` | no | no | High |
| spoof:score | ingest/live_binance_liquidations.py | redis_write | `redis-cli TYPE "spoof:score" && redis-cli TTL "spoof:score"` | no | no | High |
| lock:live_binance_liq | ingest/live_binance_liquidations.py | redis_write | `redis-cli TYPE "lock:live_binance_liq" && redis-cli TTL "lock:live_binance_liq"` | no | no | High |
| debug:binance_liquidations:last_session | ingest/live_binance_liquidations.py | redis_write | `redis-cli TYPE "debug:binance_liquidations:last_session" && redis-cli TTL "debug:binance_liquidations:last_session"` | no | no | High |

## KuCoin
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| heartbeat:KuCoin | ingest/live_kucoin.py | redis_unknown | `redis-cli TYPE "heartbeat:KuCoin" && redis-cli TTL "heartbeat:KuCoin"` | yes | no | Medium |
| price:{SYMBOLS | ingest/live_kucoin.py | redis_read | `redis-cli --scan | grep -E "price" | head -20` | no | no | High |
| orderbook:top:{SYMBOLS | ingest/live_kucoin.py | redis_read | `redis-cli --scan | grep -E "orderbook" | head -20` | no | no | High |
| orderbook:top:{s} | ingest/live_kucoin.py | redis_read | `redis-cli --scan | grep -E "orderbook" | head -20` | no | no | High |
| orderbook:top:{s} | ingest/live_kucoin.py | redis_write | `redis-cli --scan | grep -E "orderbook" | head -20` | no | no | High |
| orderbook:bids:{s} | ingest/live_kucoin.py | redis_write | `redis-cli --scan | grep -E "orderbook" | head -20` | no | no | High |
| orderbook:asks:{s} | ingest/live_kucoin.py | redis_write | `redis-cli --scan | grep -E "orderbook" | head -20` | no | no | High |
| heartbeat:OrderBook:{s} | ingest/live_kucoin.py | redis_write | `redis-cli --scan | grep -E "heartbeat" | head -20` | yes | no | High |

## CoinAPI
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| metrics:coinapi:ws:last_msg_ts | ingest/live_coinapi_wsds.py | redis_write | `redis-cli TYPE "metrics:coinapi:ws:last_msg_ts" && redis-cli TTL "metrics:coinapi:ws:last_msg_ts"` | no | no | High |
| metrics:coinapi:ws:bytes_today | ingest/live_coinapi_wsds.py | redis_write | `redis-cli TYPE "metrics:coinapi:ws:bytes_today" && redis-cli TTL "metrics:coinapi:ws:bytes_today"` | no | no | High |
| metrics:coinapi:ws:msgs_today | ingest/live_coinapi_wsds.py | redis_write | `redis-cli TYPE "metrics:coinapi:ws:msgs_today" && redis-cli TTL "metrics:coinapi:ws:msgs_today"` | no | no | High |
| metrics:coinapi:ws:bytes:{today} | ingest/live_coinapi_wsds.py | redis_write | `redis-cli --scan | grep -E "metrics" | head -20` | no | no | High |
| metrics:coinapi:ws:msgs:{today} | ingest/live_coinapi_wsds.py | redis_write | `redis-cli --scan | grep -E "metrics" | head -20` | no | no | High |
| metrics:coinapi:ws:staleness_p50_ms | ingest/live_coinapi_wsds.py | redis_write | `redis-cli TYPE "metrics:coinapi:ws:staleness_p50_ms" && redis-cli TTL "metrics:coinapi:ws:staleness_p50_ms"` | no | no | High |
| metrics:coinapi:ws:staleness_p95_ms | ingest/live_coinapi_wsds.py | redis_write | `redis-cli TYPE "metrics:coinapi:ws:staleness_p95_ms" && redis-cli TTL "metrics:coinapi:ws:staleness_p95_ms"` | no | no | High |

## CoinAnk
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| heartbeat:IngestCoinAnk | ingest/live_coinank.py | redis_unknown | `redis-cli TYPE "heartbeat:IngestCoinAnk" && redis-cli TTL "heartbeat:IngestCoinAnk"` | yes | no | Medium |
| heartbeat:CoinAnkIngest | ingest/live_coinank.py | redis_unknown | `redis-cli TYPE "heartbeat:CoinAnkIngest" && redis-cli TTL "heartbeat:CoinAnkIngest"` | yes | no | Medium |
| heartbeat:IngestCoinAnk | ingest/live_coinank.py | redis_write | `redis-cli TYPE "heartbeat:IngestCoinAnk" && redis-cli TTL "heartbeat:IngestCoinAnk"` | yes | no | High |
| heartbeat:CoinAnkIngest | ingest/live_coinank.py | redis_write | `redis-cli TYPE "heartbeat:CoinAnkIngest" && redis-cli TTL "heartbeat:CoinAnkIngest"` | yes | no | High |
| heartbeat:writer | ingest/live_coinank.py | redis_write | `redis-cli TYPE "heartbeat:writer" && redis-cli TTL "heartbeat:writer"` | yes | no | High |
| debug:coinank_ingest:status | ingest/live_coinank.py | redis_write | `redis-cli TYPE "debug:coinank_ingest:status" && redis-cli TTL "debug:coinank_ingest:status"` | no | no | High |
| k:{ | ingest/live_coinank.py | redis_write | `redis-cli --scan | grep -E "k" | head -20` | no | no | High |
| k:p | ingest/live_coinank.py | redis_write | `redis-cli TYPE "k:p" && redis-cli TTL "k:p"` | no | no | High |
| basic:{key} | ingest/live_coinank.py | redis_write | `redis-cli --scan | grep -E "basic" | head -20` | no | no | High |
| lock:live_coinank | ingest/live_coinank.py | redis_write | `redis-cli TYPE "lock:live_coinank" && redis-cli TTL "lock:live_coinank"` | no | no | High |
| proc:last_error:IngestCoinAnk | ingest/live_coinank.py | redis_write | `redis-cli TYPE "proc:last_error:IngestCoinAnk" && redis-cli TTL "proc:last_error:IngestCoinAnk"` | no | no | High |

## CoinAnk global aggregator
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| unified_features:{sym}:{tf} | ingest/live_coinank_global_aggregator.py | redis_read | `redis-cli --scan | grep -E "unified_features" | head -20` | no | no | High |
| meta:coinank_global:last_update | ingest/live_coinank_global_aggregator.py | redis_write | `redis-cli TYPE "meta:coinank_global:last_update" && redis-cli TTL "meta:coinank_global:last_update"` | no | no | High |

## liquidation bridge
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| <requires targeted extraction from source references> | artifact-only inference | unknown | `redis-cli --scan | grep -Ei "feature|signal|trainer|orchestrator" | head -50` | no | yes | Low |

## liquidation levels engine
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| price:{symbol} | ingest/liquidation_levels_engine.py | redis_read | `redis-cli --scan | grep -E "price" | head -20` | no | no | High |
| market:{symbol}:1m | ingest/liquidation_levels_engine.py | redis_read | `redis-cli --scan | grep -E "market" | head -20` | no | no | High |
| ohlcv:{symbol}:1m | ingest/liquidation_levels_engine.py | redis_read | `redis-cli --scan | grep -E "ohlcv" | head -20` | no | no | High |
| latest:coinapi:ohlcv:{symbol}:1m | ingest/liquidation_levels_engine.py | redis_read | `redis-cli --scan | grep -E "latest" | head -20` | no | no | High |

## realtime price provider
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| price:realtime:{symbol} | ingest/realtime_price_provider.py | redis_write | `redis-cli --scan | grep -E "price" | head -20` | no | no | High |
| price:{symbol} | ingest/realtime_price_provider.py | redis_write | `redis-cli --scan | grep -E "price" | head -20` | no | no | High |
| metrics:price_provider:{symbol} | ingest/realtime_price_provider.py | redis_write | `redis-cli --scan | grep -E "metrics" | head -20` | no | no | High |

## technical analysis
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| <requires targeted extraction from source references> | artifact-only inference | unknown | `redis-cli --scan | grep -Ei "feature|signal|trainer|orchestrator" | head -50` | no | yes | Low |

## OHLCV resampler
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| <requires targeted extraction from source references> | artifact-only inference | unknown | `redis-cli --scan | grep -Ei "feature|signal|trainer|orchestrator" | head -50` | no | yes | Low |

## feature_pipeline
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| heartbeat:simple_feature_pipeline | simple_feature_pipeline.py | redis_write | `redis-cli TYPE "heartbeat:simple_feature_pipeline" && redis-cli TTL "heartbeat:simple_feature_pipeline"` | yes | yes | High |
| unified_features:{symbol}:{tf} | feature_pipeline.py | redis_read | `redis-cli --scan | grep -E "unified_features" | head -20` | no | yes | High |
| features:updated | feature_pipeline.py | redis_read | `redis-cli TYPE "features:updated" && redis-cli TTL "features:updated"` | no | yes | High |
| heartbeat:FeaturePipeline | feature_pipeline.py | redis_read | `redis-cli TYPE "heartbeat:FeaturePipeline" && redis-cli TTL "heartbeat:FeaturePipeline"` | yes | yes | High |
| unified_features:{symbol}:{tf} | feature_pipeline.py | redis_write | `redis-cli --scan | grep -E "unified_features" | head -20` | no | yes | High |
| features:updated | feature_pipeline.py | redis_write | `redis-cli TYPE "features:updated" && redis-cli TTL "features:updated"` | no | yes | High |
| heartbeat:FeaturePipeline | feature_pipeline.py | redis_write | `redis-cli TYPE "heartbeat:FeaturePipeline" && redis-cli TTL "heartbeat:FeaturePipeline"` | yes | yes | High |
| orderbook:depth:{symbol} | feature_pipeline.py | redis_write | `redis-cli --scan | grep -E "orderbook" | head -20` | no | yes | High |
| slow_lane:last_run | feature_pipeline.py | redis_unknown | `redis-cli TYPE "slow_lane:last_run" && redis-cli TTL "slow_lane:last_run"` | no | yes | Medium |
| slow_lane:last_success | feature_pipeline.py | redis_unknown | `redis-cli TYPE "slow_lane:last_success" && redis-cli TTL "slow_lane:last_success"` | no | yes | Medium |
| unified_features:{symbol}:{tf} | feature_pipeline.py | redis_unknown | `redis-cli --scan | grep -E "unified_features" | head -20` | no | yes | Medium |
| features:updated | feature_pipeline.py | redis_unknown | `redis-cli TYPE "features:updated" && redis-cli TTL "features:updated"` | no | yes | Medium |
| heartbeat:FeaturePipeline | feature_pipeline.py | redis_unknown | `redis-cli TYPE "heartbeat:FeaturePipeline" && redis-cli TTL "heartbeat:FeaturePipeline"` | yes | yes | Medium |

## trainer inputs
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| unified_features:{symbol}:{tf} | rl/hybrid_trainer.py | redis_write | `redis-cli --scan | grep -E "unified_features" | head -20` | no | yes | High |
| price:{symbol} | rl/hybrid_trainer.py | redis_write | `redis-cli --scan | grep -E "price" | head -20` | no | yes | High |
| orderbook:{symbol} | rl/hybrid_trainer.py | redis_write | `redis-cli --scan | grep -E "orderbook" | head -20` | no | yes | High |
| unified_features:{symbol}:{tf} | rl/hybrid_trainer.py | redis_read | `redis-cli --scan | grep -E "unified_features" | head -20` | no | yes | High |
| price:{symbol} | rl/hybrid_trainer.py | redis_read | `redis-cli --scan | grep -E "price" | head -20` | no | yes | High |
| orderbook:{symbol} | rl/hybrid_trainer.py | redis_read | `redis-cli --scan | grep -E "orderbook" | head -20` | no | yes | High |
| portfolio:positions | rl/hybrid_trainer.py | redis_unknown | `redis-cli TYPE "portfolio:positions" && redis-cli TTL "portfolio:positions"` | no | yes | Medium |
| portfolio:positions:{account} | rl/hybrid_trainer.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| unified_features:{symbol}:{tf} | rl/hybrid_trainer.py | redis_unknown | `redis-cli --scan | grep -E "unified_features" | head -20` | no | yes | Medium |
| price:{symbol} | rl/hybrid_trainer.py | redis_unknown | `redis-cli --scan | grep -E "price" | head -20` | no | yes | Medium |
| orderbook:{symbol} | rl/hybrid_trainer.py | redis_unknown | `redis-cli --scan | grep -E "orderbook" | head -20` | no | yes | Medium |
| portfolio:positions:{aid} | rl/hybrid_trainer.py | redis_read | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | High |
| signals:trading | rl/hybrid_trainer.py | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| portfolio:positions:{account_id} | rl/hybrid_trainer.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| portfolio:positions:{account_id} | rl/hybrid_trainer.py | redis_read | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | High |
| msnap:coinapi_wsds:{sym} | rl/hybrid_trainer.py | redis_read | `redis-cli --scan | grep -E "msnap" | head -20` | no | yes | High |
| portfolio:positions:{aid} | rl/hybrid_trainer.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| features:unified:{symbol}:{tf} | rl/hybrid_trainer.py | redis_read | `redis-cli --scan | grep -E "features" | head -20` | no | yes | High |
| portfolio:equity:{aid} | rl/hybrid_trainer.py | redis_read | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | High |
| wma:{account_id_check}:positions:{symbol} | rl/hybrid_trainer.py | redis_unknown | `redis-cli --scan | grep -E "wma" | head -20` | yes | yes | Medium |
| wma:{account_id_for_val}:positions:{symbol_for_val} | rl/hybrid_trainer.py | redis_unknown | `redis-cli --scan | grep -E "wma" | head -20` | yes | yes | Medium |
| price:{symbol_for_target} | rl/hybrid_trainer.py | redis_read | `redis-cli --scan | grep -E "price" | head -20` | no | yes | High |
| unified_features:{symbol_for_target}:{tf_k} | rl/hybrid_trainer.py | redis_read | `redis-cli --scan | grep -E "unified_features" | head -20` | no | yes | High |
| orderbook:top:{symbol_for_target} | rl/hybrid_trainer.py | redis_read | `redis-cli --scan | grep -E "orderbook" | head -20` | no | yes | High |
| portfolio:equity:{chosen_account} | rl/hybrid_trainer.py | redis_read | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | High |
| portfolio:equity:{account_id} | rl/hybrid_trainer.py | redis_read | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | High |
| portfolio:positions:{acct} | rl/hybrid_trainer.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| portfolio:positions:primary | rl/hybrid_trainer.py | redis_unknown | `redis-cli TYPE "portfolio:positions:primary" && redis-cli TTL "portfolio:positions:primary"` | no | yes | Medium |
| portfolio:positions:asjad | rl/hybrid_trainer.py | redis_unknown | `redis-cli TYPE "portfolio:positions:asjad" && redis-cli TTL "portfolio:positions:asjad"` | no | yes | Medium |
| wma:{account}:positions:{symbol} | rl/hybrid_trainer.py | redis_unknown | `redis-cli --scan | grep -E "wma" | head -20` | yes | yes | Medium |
| wma:{acct}:positions:{symbol} | rl/hybrid_trainer.py | redis_unknown | `redis-cli --scan | grep -E "wma" | head -20` | yes | yes | Medium |
| wma:last_exit:{aid}:{symbol} | rl/hybrid_trainer.py | redis_read | `redis-cli --scan | grep -E "wma" | head -20` | yes | yes | High |
| features:unified:{symbol}:1m | rl/hybrid_trainer.py | redis_read | `redis-cli --scan | grep -E "features" | head -20` | no | yes | High |
| signals:trading:primary | rl/hybrid_trainer.py | redis_unknown | `redis-cli XLEN "signals:trading:primary" && redis-cli XREVRANGE "signals:trading:primary" + - COUNT 1` | yes | yes | Medium |
| signals:trading:asjad | rl/hybrid_trainer.py | redis_unknown | `redis-cli XLEN "signals:trading:asjad" && redis-cli XREVRANGE "signals:trading:asjad" + - COUNT 1` | yes | yes | Medium |
| portfolio:state:{acct} | rl/hybrid_trainer.py | redis_read | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | High |
| trainer:critical_fixes:initialized | rl/hybrid_trainer.py | redis_write | `redis-cli TYPE "trainer:critical_fixes:initialized" && redis-cli TTL "trainer:critical_fixes:initialized"` | no | yes | High |
| trainer:critical_fixes:stats | rl/hybrid_trainer.py | redis_write | `redis-cli TYPE "trainer:critical_fixes:stats" && redis-cli TTL "trainer:critical_fixes:stats"` | no | yes | High |
| trainer:liq_prevention:status | rl/hybrid_trainer.py | redis_write | `redis-cli TYPE "trainer:liq_prevention:status" && redis-cli TTL "trainer:liq_prevention:status"` | no | yes | High |
| heartbeat:trainer | rl/hybrid_trainer.py | redis_unknown | `redis-cli TYPE "heartbeat:trainer" && redis-cli TTL "heartbeat:trainer"` | yes | yes | Medium |

## trainer outputs
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| <requires targeted extraction from source references> | artifact-only inference | unknown | `redis-cli --scan | grep -Ei "feature|signal|trainer|orchestrator" | head -50` | no | yes | Low |

## orchestrator inputs
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| portfolio:positions:{account_id} | rl/tradeplan_orchestrator.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| portfolio:equity:{account_id} | rl/tradeplan_orchestrator.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| portfolio:equity:{account_id} | rl/tradeplan_orchestrator.py | redis_read | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | High |
| portfolio:positions:{acct} | rl/tradeplan_orchestrator.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| portfolio:equity:{acct} | rl/tradeplan_orchestrator.py | redis_read | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | High |
| signals:trading | rl/orchestrator_worker.py | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| signals:trading:primary | rl/orchestrator_worker.py | redis_unknown | `redis-cli XLEN "signals:trading:primary" && redis-cli XREVRANGE "signals:trading:primary" + - COUNT 1` | yes | yes | Medium |
| signals:trading:asjad | rl/orchestrator_worker.py | redis_unknown | `redis-cli XLEN "signals:trading:asjad" && redis-cli XREVRANGE "signals:trading:asjad" + - COUNT 1` | yes | yes | Medium |
| positions:live:symbols:{account_id} | rl/orchestrator_worker.py | redis_read | `redis-cli --scan | grep -E "positions" | head -20` | no | yes | High |
| positions:live:{account_id}:{sym_u} | rl/orchestrator_worker.py | redis_read | `redis-cli --scan | grep -E "positions" | head -20` | no | yes | High |
| portfolio:positions:{account_id} | rl/orchestrator_worker.py | redis_read | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | High |
| positions:{account_id} | rl/orchestrator_worker.py | redis_read | `redis-cli --scan | grep -E "positions" | head -20` | no | yes | High |
| portfolio:equity:{account_id} | rl/orchestrator_worker.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| portfolio:equity:{aid} | rl/orchestrator_worker.py | redis_read | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | High |
| positions:live:{account_id}:{symbol} | rl/orchestrator_worker.py | redis_read | `redis-cli --scan | grep -E "positions" | head -20` | no | yes | High |
| portfolio:positions:{account_id}. | rl/orchestrator_worker.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| portfolio:positions:{account_id} | rl/orchestrator_worker.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| positions:live:{account}:{symbol} | rl/orchestrator_worker.py | redis_unknown | `redis-cli --scan | grep -E "positions" | head -20` | no | yes | Medium |
| portfolio:state:{acct} | rl/orchestrator_worker.py | redis_read | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | High |
| portfolio:equity:{account_id} | rl/orchestrator_worker.py | redis_read | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | High |
| portfolio:drawdown:{account_id} | rl/orchestrator_worker.py | redis_read | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | High |
| positions:live. | rl/orchestrator_worker.py | redis_unknown | `redis-cli TYPE "positions:live." && redis-cli TTL "positions:live."` | no | yes | Medium |
| positions:live | rl/orchestrator_worker.py | redis_unknown | `redis-cli TYPE "positions:live" && redis-cli TTL "positions:live"` | no | yes | Medium |

## signal streams
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| signals:trading | DUAL_LANE_COMPLETE.md | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| signals:trading | RESTART_SUMMARY_CLEAN.md | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| signals:execution:skips | RESTART_SUMMARY_CLEAN.md | redis_unknown | `redis-cli XLEN "signals:execution:skips" && redis-cli XREVRANGE "signals:execution:skips" + - COUNT 1` | yes | yes | Medium |
| wma:proposals | RESTART_SUMMARY_CLEAN.md | redis_unknown | `redis-cli XLEN "wma:proposals" && redis-cli XREVRANGE "wma:proposals" + - COUNT 1` | yes | yes | Medium |
| signals:trading | VALIDATION_FINDINGS_DETAILED.md | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| signals:execution:skips | VALIDATION_FINDINGS_DETAILED.md | redis_unknown | `redis-cli XLEN "signals:execution:skips" && redis-cli XREVRANGE "signals:execution:skips" + - COUNT 1` | yes | yes | Medium |
| wma:proposals | VALIDATION_FINDINGS_DETAILED.md | redis_unknown | `redis-cli XLEN "wma:proposals" && redis-cli XREVRANGE "wma:proposals" + - COUNT 1` | yes | yes | Medium |
| wma:trainer:predictions | VALIDATION_FINDINGS_DETAILED.md | redis_unknown | `redis-cli TYPE "wma:trainer:predictions" && redis-cli TTL "wma:trainer:predictions"` | yes | yes | Medium |
| signals:trading | audit_last_48h_streams.md | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| signals:execution:skips | audit_last_48h_streams.md | redis_unknown | `redis-cli XLEN "signals:execution:skips" && redis-cli XREVRANGE "signals:execution:skips" + - COUNT 1` | yes | yes | Medium |
| wma:proposals | audit_last_48h_streams.md | redis_unknown | `redis-cli XLEN "wma:proposals" && redis-cli XREVRANGE "wma:proposals" + - COUNT 1` | yes | yes | Medium |
| signals:trading | END_TO_END_VALIDATION_CHECKLIST.md | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| signals:execution:skips | END_TO_END_VALIDATION_CHECKLIST.md | redis_unknown | `redis-cli XLEN "signals:execution:skips" && redis-cli XREVRANGE "signals:execution:skips" + - COUNT 1` | yes | yes | Medium |
| wma:proposals | END_TO_END_VALIDATION_CHECKLIST.md | redis_unknown | `redis-cli XLEN "wma:proposals" && redis-cli XREVRANGE "wma:proposals" + - COUNT 1` | yes | yes | Medium |
| signals:trading | FULL-REDESIGN-RUNBOOK-301225.md | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| signals:execution:skips | FULL-REDESIGN-RUNBOOK-301225.md | redis_unknown | `redis-cli XLEN "signals:execution:skips" && redis-cli XREVRANGE "signals:execution:skips" + - COUNT 1` | yes | yes | Medium |
| wma:proposals | FULL-REDESIGN-RUNBOOK-301225.md | redis_unknown | `redis-cli XLEN "wma:proposals" && redis-cli XREVRANGE "wma:proposals" + - COUNT 1` | yes | yes | Medium |
| wma:trader:execution_feedback | FULL-REDESIGN-RUNBOOK-301225.md | redis_unknown | `redis-cli TYPE "wma:trader:execution_feedback" && redis-cli TTL "wma:trader:execution_feedback"` | yes | yes | Medium |
| signals:trading:primary | FULL-REDESIGN-RUNBOOK-301225.md | redis_unknown | `redis-cli XLEN "signals:trading:primary" && redis-cli XREVRANGE "signals:trading:primary" + - COUNT 1` | yes | yes | Medium |
| signals:trading:asjad | FULL-REDESIGN-RUNBOOK-301225.md | redis_unknown | `redis-cli XLEN "signals:trading:asjad" && redis-cli XREVRANGE "signals:trading:asjad" + - COUNT 1` | yes | yes | Medium |
| signals:trading | test_production_ta_section7.py | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| signals:execution:skips | test_production_ta_section7.py | redis_unknown | `redis-cli XLEN "signals:execution:skips" && redis-cli XREVRANGE "signals:execution:skips" + - COUNT 1` | yes | yes | Medium |
| wma:proposals | test_production_ta_section7.py | redis_unknown | `redis-cli XLEN "wma:proposals" && redis-cli XREVRANGE "wma:proposals" + - COUNT 1` | yes | yes | Medium |
| signals:trading | test_production_ta_section7.py | redis_read | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | High |
| signals:execution:skips | test_production_ta_section7.py | redis_read | `redis-cli XLEN "signals:execution:skips" && redis-cli XREVRANGE "signals:execution:skips" + - COUNT 1` | yes | yes | High |
| wma:proposals | test_production_ta_section7.py | redis_read | `redis-cli XLEN "wma:proposals" && redis-cli XREVRANGE "wma:proposals" + - COUNT 1` | yes | yes | High |
| signals:trading | PRODUCTION_TA_COMPLETE_SUMMARY.md | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| signals:execution:skips | PRODUCTION_TA_COMPLETE_SUMMARY.md | redis_unknown | `redis-cli XLEN "signals:execution:skips" && redis-cli XREVRANGE "signals:execution:skips" + - COUNT 1` | yes | yes | Medium |
| wma:proposals | PRODUCTION_TA_COMPLETE_SUMMARY.md | redis_unknown | `redis-cli XLEN "wma:proposals" && redis-cli XREVRANGE "wma:proposals" + - COUNT 1` | yes | yes | Medium |
| signals:trading | ADAPTIVE_HEDGE_ARCHITECTURE_PLAN.md | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| signals:trading | PRODUCTION_TA_ROADMAP.md | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| signals:execution:skips | PRODUCTION_TA_ROADMAP.md | redis_unknown | `redis-cli XLEN "signals:execution:skips" && redis-cli XREVRANGE "signals:execution:skips" + - COUNT 1` | yes | yes | Medium |
| wma:proposals | PRODUCTION_TA_ROADMAP.md | redis_unknown | `redis-cli XLEN "wma:proposals" && redis-cli XREVRANGE "wma:proposals" + - COUNT 1` | yes | yes | Medium |
| signals:trading | TELEGRAM_FIXES_PRICE_LEVERAGE.md | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| signals:trading | TRADES_NOW_EXECUTING_FINAL.md | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| signals:trading | GPU_BATCH_PREDICTION_FIX.md | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| signals:trading:asjad | MASTER_FIX_PLAN.md | redis_unknown | `redis-cli XLEN "signals:trading:asjad" && redis-cli XREVRANGE "signals:trading:asjad" + - COUNT 1` | yes | yes | Medium |
| signals:trading:primary | MASTER_FIX_PLAN.md | redis_read | `redis-cli XLEN "signals:trading:primary" && redis-cli XREVRANGE "signals:trading:primary" + - COUNT 1` | yes | yes | High |
| signals:trading | COMPREHENSIVE_ANALYSIS_AND_RECOMMENDATIONS.md | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| signals:trading | PPO_CONFIDENCE_FIX_VALIDATION.md | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |

## trader execution inputs
| key/pattern | source file evidence | classification | sample read-only command | captured by current monitor | V2 must expose in GUI | confidence |
|---|---|---|---|---|---|---|
| pnl_pct_f:.8f} | trading/base_executor.py | redis_write | `redis-cli TYPE "pnl_pct_f:.8f}" && redis-cli TTL "pnl_pct_f:.8f}"` | no | yes | High |
| signals:trading | trading/trader.py | redis_unknown | `redis-cli XLEN "signals:trading" && redis-cli XREVRANGE "signals:trading" + - COUNT 1` | yes | yes | Medium |
| signals:trading:{self.account_id} | trading/trader.py | redis_unknown | `redis-cli XLEN "signals:trading:{self.account_id}" && redis-cli XREVRANGE "signals:trading:{self.account_id}" + - COUNT 1` | yes | yes | Medium |
| portfolio:state | trading/trader.py | redis_unknown | `redis-cli TYPE "portfolio:state" && redis-cli TTL "portfolio:state"` | no | yes | Medium |
| portfolio:equity | trading/trader.py | redis_unknown | `redis-cli TYPE "portfolio:equity" && redis-cli TTL "portfolio:equity"` | no | yes | Medium |
| portfolio:state:stream | trading/trader.py | redis_unknown | `redis-cli TYPE "portfolio:state:stream" && redis-cli TTL "portfolio:state:stream"` | no | yes | Medium |
| portfolio:equity:{self.account_id} | trading/trader.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| portfolio:equity:series:{self.account_id} | trading/trader.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| portfolio:drawdown:{self.account_id} | trading/trader.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| positions:live:symbols:{account_id} | trading/trader.py | redis_unknown | `redis-cli --scan | grep -E "positions" | head -20` | no | yes | Medium |
| positions:live:symbols:{acct} | trading/trader.py | redis_unknown | `redis-cli --scan | grep -E "positions" | head -20` | no | yes | Medium |
| positions:live:{acct}:{sym} | trading/trader.py | redis_unknown | `redis-cli --scan | grep -E "positions" | head -20` | no | yes | Medium |
| positions:live:{sym} | trading/trader.py | redis_write | `redis-cli --scan | grep -E "positions" | head -20` | no | yes | High |
| portfolio:positions:{account_id} | trading/trader.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| portfolio:positions:{acct} | trading/trader.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| wma:{self.account_id}:positions:{symbol} | trading/trader.py | redis_unknown | `redis-cli --scan | grep -E "wma" | head -20` | yes | yes | Medium |
| portfolio:positions:{self.account_id} | trading/trader.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| positions:live:{symbol} | trading/trader.py | redis_unknown | `redis-cli --scan | grep -E "positions" | head -20` | no | yes | Medium |
| positions:live:{self.account_id}:{symbol} | trading/trader.py | redis_unknown | `redis-cli --scan | grep -E "positions" | head -20` | no | yes | Medium |
| positions:live:accounts | trading/trader.py | redis_unknown | `redis-cli TYPE "positions:live:accounts" && redis-cli TTL "positions:live:accounts"` | no | yes | Medium |
| positions:live:symbols:{self.account_id} | trading/trader.py | redis_unknown | `redis-cli --scan | grep -E "positions" | head -20` | no | yes | Medium |
| net_amt:.12f} | trading/trader.py | redis_write | `redis-cli TYPE "net_amt:.12f}" && redis-cli TTL "net_amt:.12f}"` | no | yes | High |
| entry_price_net:.8f} | trading/trader.py | redis_write | `redis-cli TYPE "entry_price_net:.8f}" && redis-cli TTL "entry_price_net:.8f}"` | no | yes | High |
| mark_price_net:.8f} | trading/trader.py | redis_write | `redis-cli TYPE "mark_price_net:.8f}" && redis-cli TTL "mark_price_net:.8f}"` | no | yes | High |
| liq_price_net:.8f} | trading/trader.py | redis_write | `redis-cli TYPE "liq_price_net:.8f}" && redis-cli TTL "liq_price_net:.8f}"` | no | yes | High |
| leverage_net:.6f} | trading/trader.py | redis_write | `redis-cli TYPE "leverage_net:.6f}" && redis-cli TTL "leverage_net:.6f}"` | no | yes | High |
| initial_margin_net:.8f} | trading/trader.py | redis_write | `redis-cli TYPE "initial_margin_net:.8f}" && redis-cli TTL "initial_margin_net:.8f}"` | no | yes | High |
| maint_margin_net:.8f} | trading/trader.py | redis_write | `redis-cli TYPE "maint_margin_net:.8f}" && redis-cli TTL "maint_margin_net:.8f}"` | no | yes | High |
| unrealized_pnl_net:.8f} | trading/trader.py | redis_write | `redis-cli TYPE "unrealized_pnl_net:.8f}" && redis-cli TTL "unrealized_pnl_net:.8f}"` | no | yes | High |
| notional_usd:.8f} | trading/trader.py | redis_write | `redis-cli TYPE "notional_usd:.8f}" && redis-cli TTL "notional_usd:.8f}"` | no | yes | High |
| roe_pct:.6f} | trading/trader.py | redis_write | `redis-cli TYPE "roe_pct:.6f}" && redis-cli TTL "roe_pct:.6f}"` | no | yes | High |
| trader:{self.account_id}:last_consumed_ts_ms | trading/trader.py | redis_write | `redis-cli --scan | grep -E "trader" | head -20` | no | yes | High |
| trader:{self.account_id}:last_consumed_id | trading/trader.py | redis_write | `redis-cli --scan | grep -E "trader" | head -20` | no | yes | High |
| positions:{self.account_id} | trading/trader.py | redis_read | `redis-cli --scan | grep -E "positions" | head -20` | no | yes | High |
| positions:live:{self.account_id}:{symbol} | trading/trader.py | redis_read | `redis-cli --scan | grep -E "positions" | head -20` | no | yes | High |
| portfolio:drawdown:{self.account_id} | trading/trader.py | redis_read | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | High |
| portfolio:positions:{acct_id} | trading/trader.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| portfolio:positions:{self.account_id} | trading/trader.py | redis_read | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | High |
| portfolio:state:{account} | trading/trader.py | redis_unknown | `redis-cli --scan | grep -E "portfolio" | head -20` | no | yes | Medium |
| positions:live:symbols:{self.account_id} | trading/trader.py | redis_read | `redis-cli --scan | grep -E "positions" | head -20` | no | yes | High |

