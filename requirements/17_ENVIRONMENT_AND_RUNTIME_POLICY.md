# Environment and Runtime Policy

The existing bot/trainer Python environment is protected.

Rules:
- Do not pip install into the existing trainer venv.
- Do not upgrade torch, CUDA, numpy, pandas, or ML libraries in the existing trainer venv.
- Do not recreate the existing trainer venv.
- Do not Dockerize the trainer until a separate GPU container compatibility project is approved.
- Treat the existing venv as the ML Runtime of Record.
- V2 must interface with the trainer through an adapter or subprocess using the existing Python path.
- All V2 audit/control tools must be able to run without mutating the trainer environment.
- If V2 needs new Python packages, use a separate V2 control-plane venv.
- The V2 control-plane venv must not contain or modify PyTorch unless explicitly approved.
- The V2 control plane may read artifacts/logs/Redis produced by the trainer.
- The V2 control plane may call the trainer runtime only through explicit adapter commands.
- Live trading remains blocked.

Environment roles:
1. Legacy ML Runtime:
   Existing venv/env for trainer and GPU workloads.
   Protected.

2. V2 Control Plane Runtime:
   Lightweight Python environment for FastAPI, audit tools, monitor tools, config, risk gateway.
   Must not modify Legacy ML Runtime.

3. Frontend Runtime:
   Node/npm environment for GUI.

4. Redis Runtime:
   Existing Redis remains for legacy.
   V2 reads old Redis read-only first.
   V2 writes only to v2:* prefixes when permitted.

5. Docker Runtime:
   Optional future deployment path.
   Not required for Phase 1 audit.
   Not used for trainer until RTX 5080/CUDA/PyTorch container compatibility is proven.

Required runtime detection records for V2:
- LEGACY_TRAINER_PYTHON
- LEGACY_BOT_ROOT
- LEGACY_REDIS_URL
- V2_REDIS_PREFIX
- V2_MODE=paper/read_only by default

Trainer integration and safety boundary:
- V2 must support a runtime adapter that can call existing trainer Python without modifying it.
- V2 must not import legacy trainer directly into the FastAPI process unless dependency safety is proven.
- Prefer subprocess boundary for trainer runtime:
  LEGACY_TRAINER_PYTHON /path/to/script.py --mode read_only/status/export
- Any trainer call must be logged and audited.
