# Moralis Endpoint Semantic Projection Checkpoint

Date: 2026-07-21

Base checkpoint: `c71745005748139c42bbb612a152d26498832618`

Scope: parsed Moralis payload projection and source-row evidence only. No
service was restarted, no provider request was made, no Redis runtime key was
changed, and no trainer, allocator, risk, paper, live, order, leverage, or
margin authority was enabled.

## Evidence counts

- registered Moralis endpoint contracts covered: 14;
- endpoint feature families projected: 16;
- explicit endpoint-field bindings checked: 96 across 19 unique fields;
- transport resource checks: UTF-8, finite numbers, JSON type, canonical byte
  size, string size, depth, node count, list cardinality, and object
  cardinality;
- reproduced large-page regression: 100 wallet-history rows, 500 nested
  transfer records, and 1 unsafe nested display label;
- large-page result: 100 rows retained, 1 field path quarantined, 0 fabricated
  semantic features, and 0 downstream authorities enabled;
- backend routes or UI pages changed: 0;
- screenshots captured: 0 (backend evidence family);
- Moralis provider requests used by this family: 0;
- Moralis unit tests passed at checkpoint validation: 263;
- Python source files compiled: 3;
- changed files linted: 5;
- remaining Moralis release families: 3 (causal event/post-commit receipts,
  real signed Streams webhook/registry evidence, and official wallet-PnL plus
  adaptive scorer wiring).

## Corrected boundary

Transport JSON and semantic JSON are no longer treated as the same contract.
The shared transport canonicalizer accepts valid provider-owned Unicode
metadata while enforcing immutable resource limits. The normalizer then:

1. walks the bounded response and records the exact safe field path for any
   metadata quarantined from semantic output;
2. projects only fields defined for that endpoint family;
3. binds every contributing row to its original row ordinal, full transport
   row digest, strict semantic-projection digest, and the exact raw-response
   SHA-256 when the publisher has authenticated that receipt; and
4. keeps the full provider row only as ASCII-escaped canonical audit evidence,
   never as a model feature or Redis-key source.

An invalid or self-declared raw-response digest cannot become a bound
projection. It remains observable with `raw_response_evidence_bound=false`,
`admitted_feature_count=0`, and all consumer authorities false.

## Remaining release boundary

This family removes a false whole-response rejection. It does not make
Moralis green. `available_at` and the durable post-commit receipt remain
unbound; trainer and every execution consumer must therefore continue to mask
Moralis. A future checkpoint may turn the source green only after the causal
clock chain and consumer receipt checks pass on the exact deployed SHA.
