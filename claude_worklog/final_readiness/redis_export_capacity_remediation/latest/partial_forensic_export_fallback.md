# Partial Forensic Export Fallback

```json
{
  "not_equivalent_to_full_preservation": true,
  "operator_decision": "If full export is infeasible, operator must explicitly accept partial forensic preservation before any trim.",
  "recommended_bundle": [
    "first 100k entries",
    "last 100k entries",
    "hour/day bucket counts from stream IDs if approved",
    "representative high-notional liquidation clusters",
    "XINFO STREAM metadata",
    "consumer group safety snapshot",
    "sha256 manifest for every artifact"
  ],
  "stream_length": 70928809
}
```

PARTIAL_FORENSIC_EXPORT_FALLBACK_READY
