# Legacy Trainer Startup Decision Packet

Generated: 2026-05-12T06:11:36Z

Status: `STARTUP_NOT_APPROVED_IN_THIS_TASK`.

## Candidate Commands

- `cd legacy_reference && python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features`
- `cd legacy_reference && python3 rl/hybrid_trainer.py --mode hybrid`
- `legacy_reference/start_hybrid_trainer_live.sh`
- `legacy_reference/launch_hybrid_trainer.sh` (points to `/home/wali/Desktop/AI BOT`, so it is forbidden for this task)

## Expected Environment

- Python/Torch CUDA runtime required for full GPU path.
- Observed local Python: `3.12.3`.
- Observed Torch: `2.8.0+cu128`.
- Observed CUDA available: `True`.
- Observed GPU: `NVIDIA GeForce RTX 5080`.

## Expected Redis Writes / Live Signal Risk

Known legacy paths can write or publish:

- `wma:proposals`
- `signals:trading:primary`
- `signals:debug`
- `prediction:<symbol>:<timeframe>` hashes
- `signals:trading:last:<symbol>:<timeframe>` hashes
- calibration comparison streams/hashes

Legacy trader process observed: `True`.

Starting the legacy trainer could publish live-like signals into legacy Redis while a legacy trader is visible. This task therefore does not start it.

## Safety Decision

Starting legacy trainer requires a separate explicit safe startup packet that proves:

- output streams are redirected or contained to V2 paper-only storage,
- legacy Redis writes are disabled or safely isolated,
- live trader cannot consume generated signals,
- no exchange actions are possible,
- rollback/stop procedure is defined.
