# Trainer Derived Evidence Paper-Only Acceptance Packet

Generated: 2026-05-15T11:00:37Z

This packet is an operator decision packet, not an approval.

Current trainer lineage state:
- `feature_snapshot_id`: derived from legacy read-only bridge evidence.
- `confidence_calibrated`: derived from the same legacy confidence value as `confidence_raw`.
- `top_positive_features`: incomplete attribution.
- `top_negative_features`: incomplete attribution.
- `expected_move_bps`: native field present, but this does not clear lineage/attribution blockers.

The derived evidence may be acceptable for V2 paper-only legacy shutdown only if the operator explicitly accepts these limitations:
- The V2 trainer bridge has legacy hybrid trainer log/Redis evidence and checkpoint evidence.
- The active prediction lineage does not contain a native trainer-emitted `feature_snapshot_id`.
- The active prediction lineage does not contain a separate native calibrated confidence field.
- The active prediction lineage does not contain native feature attribution for top positive and negative features.
- V2 feature snapshot missing/stale/unused flags are available from V2 payloads, but they do not prove native trainer attribution for the legacy prediction.

This limitation is not acceptable for live or canary readiness.

Required operator acceptance language, if the operator chooses to accept this for paper-only shutdown:

```text
I accept derived trainer lineage evidence for V2 paper-only legacy shutdown evaluation.
I understand this does not establish live or canary readiness.
I understand trainer native feature_snapshot_id, native calibrated confidence, and native feature attribution remain incomplete.
I understand live_gate must remain blocked_human_only and live_symbols must remain [].
```

Until that explicit acceptance exists:
- Keep `LEGACY_LOG_FEATURE_SNAPSHOT_ID_DERIVED` blocked.
- Keep `LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED` blocked.
- Keep `LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE` blocked.
- Keep legacy shutdown recommendation `BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE`.

Safety invariants:
- `live_gate = blocked_human_only`
- `live_symbols = []`
- final approval token absent
- Redis trim approval absent
- no old Redis writes
- no exchange mutation
- no leverage change
- no margin-mode change
