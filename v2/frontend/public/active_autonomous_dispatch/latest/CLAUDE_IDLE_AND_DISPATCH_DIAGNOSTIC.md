# Claude Idle And Dispatch Diagnostic

Classification: `CLAUDE_ACTIVE_OK`

Evidence:

- selected primary task: `LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_AND_V2_PARITY_SYNC_UNBLOCK`
- task definition existed before repair: `True`
- queue next pending task: `SAFE_LEGACY_TRAINER_BRIDGE_AND_GPU_PARITY_SANDBOX`
- current running task: `None`
- control plane live gate: `blocked_human_only`
- supervised run status after repair: `completed`
- follow-on containment task status: `completed`
- next selected primary task status: `completed`
- required primary outputs materialized: `True`

Cause: the non-drift lock was active and rejecting all non-selected tasks, but the selected primary task did not have a supervisor task definition. The repair created the selected primary task definition and explicit non-drift Codex audit task definitions.
