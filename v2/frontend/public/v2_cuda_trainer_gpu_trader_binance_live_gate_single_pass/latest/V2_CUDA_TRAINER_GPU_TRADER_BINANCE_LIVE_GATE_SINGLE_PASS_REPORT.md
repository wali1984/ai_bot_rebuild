# V2 CUDA Trainer GPU Trader Binance Live Gate Single Pass Report

Gate: `V2_CUDA_TRAINER_GPU_TRADER_BINANCE_LIVE_GATE_SINGLE_PASS_BLOCKED`
Generated EST: `2026-06-05T00:54:38-04:00`

Live execution remains blocked.

- live_gate: `blocked_human_only`
- live_symbols: `[]`
- execution_live_symbols: `[]`
- trader_execution_enabled: `False`
- exchange mutation: `EXCHANGE_MUTATION_FROZEN`

CUDA trainer evidence:
- GPU: `NVIDIA GeForce RTX 5080`
- RTX 5080 detected: `True`
- current batch size: `505`
- current VRAM reserved MB: `52.0`
- utilization verdict: `MODEL_TOO_SMALL_TO_SATURATE_GPU`
- predictions checked: `505/505`
- price target missing: `0`

Binance private trader evidence:
- status: `BINANCE_PRIVATE_READONLY_CONNECTIVITY_READY`
- env source: `v2/.env.local`
- raw credentials in payload: `NEVER`
- test order attempted: `False`

Edge evidence:
- edge proven: `False`
- after-cost expectancy bps: `2.3025843929103904`
- CI lower bps: `-2.1690836772714452`
- recommendation: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`

Exact blockers:
- `BACKTEST_EDGE_BLOCKED_NO_EDGE_CLAIM`
- `CODEX_5_5_FINAL_PASS_REQUIRED`
- `GPU_UTILIZATION_OR_VRAM_TARGET_NOT_MET`
- `LIVE_GATE_REMAINS_BLOCKED_HUMAN_ONLY`
- `LIVE_RISK_CAPS_OPERATOR_REQUIRED`
- `LIVE_SYMBOL_APPROVAL_REQUIRED`
- `MODEL_TOO_SMALL_TO_SATURATE_GPU`
- `UNIFIED_FEATURE_PARITY_BLOCKED_OR_PARTIAL`

Safety: no order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no legacy restart, no Redis trim.
