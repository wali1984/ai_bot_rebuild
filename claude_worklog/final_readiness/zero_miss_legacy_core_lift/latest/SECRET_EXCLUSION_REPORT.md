# Secret Exclusion Report (Phase 0)

Generated: 2026-05-15

## Source root used

v2/legacy_preserved (V2-side preserved closure).

## Legacy root denial event

Attempted: bash ls of the legacy bot root path.
Outcome: denied by the Claude Code auto-mode classifier with reason
"Bash command targets /home/wali/Desktop/AI BOT, which the user's CLAUDE.md
and task constraints explicitly forbid reading or modifying".

This denial occurred even though the user's task brief explicitly says
"Read legacy only" — the runtime classifier was more conservative than the
brief. The sprint adapted by mirroring v2/legacy_preserved/ instead.

## Secret patterns scanned

- .env
- credentials
- secrets
- api_key / apikey
- private_key
- .pem
- .key

## Result

No file in v2/legacy_preserved/ matched the secret pattern set. Zero secret
files copied. Zero secret files excluded (because none were present in the
source root used).

## Binary / model / checkpoint exclusion

Excluded extensions: .pt, .pth, .bin, .pkl, .pickle, .so, .dylib, .dll,
.npy, .npz, .h5, .tar, .gz, .zip, .sqlite, .db, .log, .tflite, .onnx.

Result: zero binary files present in v2/legacy_preserved/, so zero
excluded. Any binary/model/checkpoint inventory must be filled when the
operator grants direct legacy-root access.

## Skip directories

__pycache__, .git, .pytest_cache, .venv, venv, env, node_modules

These were enumerated for skip-on-walk but did not appear in the source
tree.

## Honest classification

Secret exclusion is CLEAN under the source root used. The fact that no
secrets appeared is not a guarantee that the legacy root has no secrets —
only that the source root used in this sprint had none.
