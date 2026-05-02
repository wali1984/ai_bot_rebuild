```
# GPU and Batching Parity Requirements

V2 must not replace the legacy hybrid trainer with a basic trainer. V2 must
preserve GPU and batching assumptions and must invoke the legacy runtime via
the subprocess boundary defined in `07_PROCESS_BOUNDARY_AND_SUBPROCESS_ADAPTER_SPEC.md`.

## Preserved GPU assumptions

- CUDA device selection rules from
  `claude_worklog/trainer_atlas/HYBRID_TRAINER_CONFIG_USAGE.json`.
- GPU saturation behavior referenced from
  `legacy_reference/rl/gpu_saturation.py` (read-only reference; not modified).
- GPU forced PPO behavior referenced from class index entries in
  `claude_worklog/trainer_atlas/HYBRID_TRAINER_CLASS_INDEX.json`.

## Preserved batching assumptions

- SubprocVecEnv worker patterns referenced from
  `claude_worklog/trainer_atlas/HYBRID_TRAINER_REDIS_WRITE_CLASSIFICATION.md`
  rows annotated `read_only` for SubprocVecEnv worker startup.
- Worker stagger behavior to avoid Redis / socket "thundering herd" must be
  preserved as documented in the atlas (read-only annotation).
- Redis-touching code paths inside training workers remain read-only as
  classified in
  `claude_worklog/trainer_atlas/HYBRID_TRAINER_REDIS_WRITE_CLASSIFICATION.md`.

## Forbidden simplifications

- Do not collapse hybrid PPO + supervised pretraining into a single basic
  policy gradient loop.
- Do not remove SubprocVecEnv-style parallelism without an evidence-backed
  performance test.
- Do not change CUDA device selection logic.
- Do not change batch sizes without explicit human approval and evidence.
- Do not change the optimizer or scheduler families used by the legacy
  trainer without parity evidence.

## Required runtime telemetry (V2-side)

- GPU device id used per training run.
- Per-process GPU memory high-water mark (read via legacy runtime; emitted
  through subprocess boundary).
- Last `GPU_BATCH` timestamp (used by liveness monitor; see
  `claude_worklog/v2_requirements/09_TRAINER_INTERNAL_WORKER_SUPERVISION_REQUIREMENT.md`).

PHASE2_TRAINER_GPU_PARITY_GPU_BATCHING_READY
```
