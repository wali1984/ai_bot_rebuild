# V2 Local-Native Runtime Plan

V2 starts without Docker.

Components:
- existing Redis instance
- existing legacy trainer venv for ML runtime
- optional separate V2 Python control-plane venv
- Node/npm frontend
- SQLite initially for audit index if Postgres/Docker unavailable
- Postgres optional later

Default ports:
- Web GUI: 3000
- API: 8000
- Existing Redis: keep current port, read-only for legacy keys
- V2 Redis prefix: v2:*

Do not create a new Redis container in Phase 1.
Do not create a new trainer container in Phase 1.

Startup model:
1. Legacy bot remains as-is.
2. V2 audit tools read legacy_reference and read-only runtime evidence.
3. V2 monitor reads Redis/logs/processes.
4. V2 GUI/API run separately.
5. V2 live trading blocked.

Trainer integration:
- Discover existing trainer Python path.
- Record it in v2/config/runtime_paths.example.json.
- Use adapter/subprocess boundary.
- Never pip install into trainer env.
- Never import legacy trainer into V2 API process unless explicitly approved.

Docker:
- Docker is optional for future hosting.
- Docker Compose can later run web/api/db only.
- Trainer GPU containerization requires separate approval and RTX 5080 CUDA compatibility testing.
