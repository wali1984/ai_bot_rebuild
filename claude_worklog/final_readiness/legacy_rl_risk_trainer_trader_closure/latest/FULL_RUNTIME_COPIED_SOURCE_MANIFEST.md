# FULL_RUNTIME_COPIED_SOURCE_MANIFEST — Phase B

## Tool

[claude_worklog/tools/copy_legacy_full_runtime_closure.py](../../../tools/copy_legacy_full_runtime_closure.py)

## Totals

| status | count |
|---|---|
| COPIED | **248** |
| UNCHANGED | 0 |
| SKIPPED_BINARY_OR_DISALLOWED_EXTENSION | **139** |
| REFUSED_SECRET_LIKE_PATH | 0 |
| MISSING_IN_LEGACY_REPO | 0 |
| FLAGGED_SECRET_CONTENT_NOT_COPIED | **0** |

**Targets enumerated:** 387. **Bytes copied:** 11 MB (preserved closure tree). **Secret-content scan: zero hits across all 248 files.**

Per-file SHA256 + size + secret-heuristic scan: [full_runtime_copied_source_manifest.json](full_runtime_copied_source_manifest.json).

## Path-level exclusions (verified, zero matches)

- `.env`, `.env.*`, `credentials*`, `secrets` (path-named, not stdlib), `.pem`, `.p12`, `id_rsa*`

## Extension-level skips (139 binary/checkpoint files)

Skipped (inventory only in [binary_artifacts_skipped.json](binary_artifacts_skipped.json) once present):

- model checkpoints: `.pt`, `.pth`, `.pkl`, `.pickle`, `.npz`, `.npy`, `.bin`, `.ckpt`, `.safetensors`, `.onnx`, `.h5`
- compiled / native: `.so`, `.dll`, `.dylib`
- archives: `.zip`, `.tar`, `.gz`, `.tgz`, `.7z`
- images / docs: `.png`, `.jpg`, `.jpeg`, `.gif`, `.pdf`
- databases: `.sqlite`, `.db`

## Allow-listed extensions (copied)

`.py`, `.sh`, `.bash`, `.txt`, `.md`, `.rst`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`, `.json`, `.sql`, `.ps1`, `.conf`.

## Tree shape after copy

```text
v2/legacy_preserved/full_runtime_closure
├── config_accounts.py
├── config.py
├── risk/        (22)
├── rl/          (135 incl. subdirs and non-.py)
├── scripts/     (21)
├── services/    (8)
├── telegram_alerts.py
├── trading/     (35)
└── utils/       (21)
```

## Forbidden during this phase (verified)

- No legacy mutation — copier opens source read-only via `.read_bytes()`.
- No secret-content commits — heuristics block at copy-time; flagged files would land in `flagged_for_operator_review.json` (zero this turn).
- No binary blobs committed — 139 binary files inventoried but not copied.
- No exchange / leverage / margin / Redis / approval-token side-effects — the copier has no exchange SDK, no Redis client, and no approval-token codepath.
