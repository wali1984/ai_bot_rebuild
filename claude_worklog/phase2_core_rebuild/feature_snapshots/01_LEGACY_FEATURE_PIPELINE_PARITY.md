# Legacy Feature Pipeline Parity

`feature_pipeline.py` is parity-critical.

Rules:
- Preserve behavior first.
- Do not rewrite the legacy pipeline.
- Do not call live Redis or live ingestors.
- Build adapters around captured payload shape.
- Enhancement is allowed only after parity baselines, replay evidence, and Codex review.

The Phase 2C adapter converts local fixture payloads into V2 `FeatureSnapshot` records. It does not mutate the preserved pipeline.

LEGACY_FEATURE_PIPELINE_PARITY_READY
