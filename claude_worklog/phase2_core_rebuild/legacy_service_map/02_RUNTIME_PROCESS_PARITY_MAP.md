# Runtime Process Parity Map

| component | startup_script_expected | currently_running | observed_pid_if_known | startup_phase | category | V2 strategy | preservation level | parity tests required | notes |
|---|---:|---:|---:|---|---|---|---|---|---|
| `redis-server` | True | True | 1925 | Phase 0 | infra | preserve read-only monitoring; no live restarts | document_and_wrap | read-only smoke/evidence tests |  |
| `scripts/memory_monitor.py` | True | True | 2422220 | Phase 0.5 | monitor | replace/preserve as evidence packet monitor | document_and_wrap | read-only smoke/evidence tests |  |
| `scripts/monitor_trainer_predictions.py` | True | True | 2422445 | Phase 0.5 | monitor | preserve trainer prediction liveness checks | document_and_wrap | read-only smoke/evidence tests |  |
| `vpn_monitor.py` | True | False | - | Phase 0.5 | monitor | document missing runtime; monitor only | document_and_wrap | read-only smoke/evidence tests |  |
| `system_telegram_monitor.py` | True | False | - | Phase 0.5 | monitor | document missing runtime; monitor only | document_and_wrap | read-only smoke/evidence tests |  |
| `monitor_system_memory.py` | True | False | - | Phase 0.5 | monitor | document missing runtime; monitor only | document_and_wrap | read-only smoke/evidence tests |  |
| `live_binance.py` | True | True | 2434190 | Phase 1 | ingestor | wrap/adapt after parity | preserve_first | hash + replay/fixture parity + Codex review |  |
| `live_kucoin.py` | True | True | 2434257 | Phase 1 | ingestor | wrap/adapt after parity | preserve_first | hash + replay/fixture parity + Codex review |  |
| `live_coinank.py` | True | True | 2434262 | Phase 1 | ingestor | copy as-is plus wrapper; no behavior change | copy_as_is | hash + replay/fixture parity + Codex review |  |
| `live_binance_liquidations.py` | True | True | 2434267 | Phase 1 | ingestor | wrap/adapt after parity | preserve_first | hash + replay/fixture parity + Codex review |  |
| `liquidation_bridge.py` | True | True | 2434272 | Phase 1 | market_data_bridge | wrap/adapt after parity | preserve_first | hash + replay/fixture parity + Codex review |  |
| `liquidation_levels_engine.py` | True | True | 2434277 | Phase 1 | market_data_bridge | wrap/adapt after parity | preserve_first | hash + replay/fixture parity + Codex review |  |
| `realtime_price_provider.py` | True | True | 2434282 | Phase 1 | market_data_bridge | wrap/adapt after parity | preserve_first | hash + replay/fixture parity + Codex review |  |
| `live_coinank_global_aggregator.py` | True | True | 2435742 | Phase 1 | ingestor | wrap/adapt after parity | preserve_first | hash + replay/fixture parity + Codex review |  |
| `ingest.live_coinapi_wsds` | True | True | 2435747 | Phase 1 | ingestor | wrap/adapt after parity | preserve_first | hash + replay/fixture parity + Codex review |  |
| `ingest.live_coinapi_v1` | True | True | 3451261 | Phase 1 | ingestor | wrap/adapt after parity | preserve_first | hash + replay/fixture parity + Codex review |  |
| `ohlcv_resampler_hotfix.py` | True | True | 2434939 | Phase 2 | feature_pipeline | preserve behavior first | preserve_first | hash + replay/fixture parity + Codex review |  |
| `feature_pipeline.py` | True | True | 2435072 | Phase 2 | feature_pipeline | parity-critical; add attribution after parity | preserve_first | hash + replay/fixture parity + Codex review |  |
| `live_technical_analysis.py` | True | True | 2435730 | Phase 2.5 | feature_pipeline | preserve technical feature behavior first | preserve_first | hash + replay/fixture parity + Codex review |  |
| `rl.hybrid_trainer` | True | True | 3355777 | Phase 3 | trainer | parity rebuild preserving GPU/hybrid behavior | preserve_first | hash + replay/fixture parity + Codex review |  |
| `rl.orchestrator_worker` | True | True | 2435672 | Phase 3B | orchestrator | preserve decision logic; add lineage/risk-gateway routing | document_and_wrap | read-only smoke/evidence tests | startup display grep omits orchestrator_worker |
| `trading/trader.py` | True | True | 2432997 | Phase 4B | trader | rebuild as paper/shadow trader fleet first | document_and_wrap | read-only smoke/evidence tests |  |
| `trading/trader-asjad.py` | True | False | - | Phase 4B | trader | document missing runtime; paper/shadow only | document_and_wrap | read-only smoke/evidence tests |  |
| `monitor_portfolio_primary.py` | True | False | - | Phase 4C | portfolio_monitor | preserve into readiness monitor | document_and_wrap | read-only smoke/evidence tests |  |
| `monitor_portfolio_asjad.py` | True | False | - | Phase 4C | portfolio_monitor | preserve into readiness monitor | document_and_wrap | read-only smoke/evidence tests |  |
| `scripts/monitor_trainer_prices.py` | False | True | 147111 | extra | extra_runtime_process | inventory as extra runtime trainer price monitor | document_and_wrap | read-only smoke/evidence tests | extra process not referenced in startup script |
| `scripts/paralysis_detectors.py` | True | False | - | one-shot | one_shot_validator | port as read-only validation | document_and_wrap | read-only smoke/evidence tests |  |
| `scripts/validate_symbol_universe_data.py` | True | False | - | one-shot | one_shot_validator | superseded by Phase 2B symbol-universe validation | document_and_wrap | read-only smoke/evidence tests |  |
| `scripts/health_probe.py` | True | False | - | one-shot | one_shot_validator | port as V2 health probe | document_and_wrap | read-only smoke/evidence tests |  |
| `trading/signal_router.py` | False | False | - | removed | removed_or_deprecated | do not re-add blindly | document_and_wrap | read-only smoke/evidence tests |  |
| `scripts/ingestors_watchdog.py` | False | True | 2422250 | removed | removed_or_deprecated | do not re-add blindly | document_and_wrap | read-only smoke/evidence tests |  |

RUNTIME_PROCESS_PARITY_MAP_READY
