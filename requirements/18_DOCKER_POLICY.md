# Docker Policy

Docker is not required for Phase 1 audit.

Docker is deferred because:
- existing trainer uses RTX 5080 GPU
- RTX 5080 / Blackwell requires compatible CUDA/PyTorch stack
- current trainer environment may already be correctly configured
- Docker GPU compatibility requires NVIDIA Container Toolkit and exact CUDA/PyTorch validation
- changing this during audit could break the working trainer

Allowed Docker use later:
- web GUI
- FastAPI backend
- Postgres
- optional Redis V2
- reverse proxy for internet hosting

Blocked Docker use for now:
- trainer
- live trader
- anything requiring GPU
- anything touching exchange keys

Before trainer Dockerization:
- prove nvidia-smi works inside container
- prove torch.cuda.is_available() inside container
- prove device is RTX 5080
- prove CUDA version is compatible
- prove model inference/training parity
- prove no performance regression
- human approval required
