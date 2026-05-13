# Final Canary Hard Gate Checklist

Generated: 2026-05-13T03:59:24.783907+00:00

Summary: `{"MISSING_EVIDENCE": 3, "PASS": 40}`

- PASS: human approval file absent — Approval token file was not created.
- PASS: final live approval not created automatically — Automation produced packet only.
- PASS: activation remains blocked —
- PASS: no live API key activation by automation — No key activation performed.
- MISSING_EVIDENCE: read-only account status verified — Requires human/operator exchange-read confirmation before canary.
- MISSING_EVIDENCE: trade permission known — Must be explicitly verified before approval.
- PASS: isolated margin requirement defined — Required for canary.
- PASS: CROSS margin blocked for V2 canary — Cross margin not allowed.
- PASS: leverage cap 1x — 1x initial cap.
- PASS: ADJUST_LEVERAGE disabled — No leverage changes allowed.
- PASS: ADJUST_LEVERAGE_AND_POSITION disabled — No automatic leverage/position adjustment.
- PASS: missing signal_id blocks —
- PASS: missing prediction_id blocks —
- PASS: missing feature_snapshot_id blocks —
- PASS: missing confidence blocks —
- PASS: stale risk-add signal blocks —
- PASS: duplicate execution blocks/dedupes —
- PASS: stop policy required —
- PASS: daily loss hard stop required —
- MISSING_EVIDENCE: weekly loss hard stop required — Must be verified before live approval.
- PASS: kill switch required —
- PASS: tiny canary profile only —
- PASS: BTCUSDT only unless approval expands —
- PASS: no hedge/DCA initially —
- PASS: no averaging down —
- PASS: no live order function exposed until approval —
- PASS: V2 paper runtime current —
- PASS: legacy live bridge current or blocker explicit —
- PASS: CoinAnk market intelligence current or blocker explicit —
- PASS: trainer status current or blocker explicit —
- PASS: signal lineage current or blocker explicit —
- PASS: audit ledger current —
- PASS: public dashboard current —
- PASS: local dashboard current —
- PASS: live banner visible —
- PASS: dangerous controls disabled/approval-gated —
- PASS: Admin AI cannot enable live —
- PASS: Config Admin cannot silently change leverage/margin/live —
- PASS: final no-live-side-effects audit —
- PASS: final runtime truth audit —
- PASS: final risk gate audit —
- PASS: final website dangerous-controls audit —
- PASS: final approval packet audit —
