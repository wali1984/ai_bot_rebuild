# Final product defect register

## Fixed

- `AUDIT-UNKNOWN-RESULT`: `AuditResultPanel` now falls back for append-only result enums and stringifies structured actor/action/timestamp/reason/evidence values. Typecheck and production build passed.
- `IOS-VISIBLE-PAPER-COPY`: replaced the visible `Paper only` label with `Execution restricted`; SwiftPM test suite is now 36/36.

## Open / not falsely closed

- `VISUAL-SIGNAL-EXPLAINABILITY`: four screenshots were intentionally blocked because the proof payload made the renderer hang; this is an evidence gap, not a pass.
- `AUTH-TOKEN-EXPIRY-EVIDENCE`: historical all-route run contains 401 console errors after its short-lived admin token expired; no live claim is made from those rows.
- `LIVE-EXECUTION`: exchange mutation and live order submission remain fail-closed and were not enabled.

Publisher-held paths were not modified.
