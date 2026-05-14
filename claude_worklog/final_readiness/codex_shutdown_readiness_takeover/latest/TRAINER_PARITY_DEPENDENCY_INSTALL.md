# Trainer Parity Dependency Install

Status: dependency install approved and completed for V2 `.venv` only.

- Scope: `/home/wali/Desktop/AI BOT REBUILD/.venv`
- Legacy runtime mutated: no
- Live approval created: no
- Old Redis write performed: no
- Exchange action performed: no
- Requirements file: `requirements/trainer_parity_requirements.txt`

Installed top-level versions:

- `torch==2.10.0` installed as `2.10.0+cu128`
- `stable_baselines3==2.7.1`
- `cloudpickle==3.1.2`
- `gymnasium==1.2.3`

Validation:

- `pip check`: PASS
- Python imports: PASS
- `torch.cuda.is_available()`: true
- GPU: NVIDIA GeForce RTX 5080
- Driver: 580.126.09
- Torch CUDA: 12.8
- CUDA tensor probe: PASS (`6.0`)

This clears only the dependency-install blocker for trainer parity work. It does not accept checkpoint evidence, does not clear `WRAPPER_NOT_LEGACY_HYBRID_PARITY`, and does not change the shutdown recommendation.
