# Offline pretrain + CoinAPI WSDS ingestor

This patch adds:

1. `rl/masa_supervised_pretrainer.py`
   - Supervised offline pretraining for the MASA network using the existing JSONL historical
     data format handled by `rl/historical_data_loader.py`.
   - Saves a checkpoint named `masa_historical_baseline.pth` by default.

2. `ingest/live_coinapi_wsds.py`
   - CoinAPI WebSocket DS order-book ingestor that writes Redis snapshots under:
     `msnap:coinapi_wsds:{SYMBOL}`.
   - These keys are already consumed by your existing microstructure stack
     (`rl/microstructure_source_router.py` and `rl/microstructure_aggregator.py`).

See the accompanying ChatGPT response for the required `hybrid_trainer.py` surgical edits
(confidence/logit fixes + tiered checkpoint loading).
