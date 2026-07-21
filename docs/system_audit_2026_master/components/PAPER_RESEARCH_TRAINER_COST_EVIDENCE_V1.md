# Paper/Research Trainer Cost Evidence V1

Status: implemented as an unwired evidence primitive. It does not restore or
authorize trainer execution by itself.

## Purpose and non-purpose

`paper_research_causal_cost_evidence_v1` provides a credential-free cost
component path for paper/research analysis. It combines:

1. an Ed25519-signed, operator-configured public fee-schedule artifact;
2. an exact causal expected-notional factory token;
3. one atomic read of direct Binance public order-book depth/features and mark
   price; and
4. four label-only float32 values: fee, spread, expected adverse slippage, and
   signed funding over the pinned counterfactual horizon.

It is not a substitute for the account-authenticated profiled publisher. It
does not claim that a configured fee is the account's actual commission tier.
It cannot construct an account commission response and its result has a
different exact Python type and schema.

## Why the existing paper fee blob is insufficient

The existing `paper_cost_fee_schedule_evidence_v1` shape contains only a
configured fee scalar, a source label, and a self-hash in its surrounding cost
payload. It has no independently pinned signing key, exact source-document
bytes, source revision, effective/available/expiry clocks, or account/public
authority classification. A self-hash detects accidental mutation only after
the expected hash is independently known; it does not authenticate who chose
the fee or when it was valid. It must never be translated into profiled trainer
authority.

## Fee signature boundary

The research fee material is signed in the domain:

`v2/native-trainer/paper-research-configured-public-fee-schedule/v1\0`

The consumer must receive all of these independently from the serialized
attestation:

- the raw 32-byte Ed25519 registry public key;
- the independently retained SHA-256 fingerprint of that key; and
- the expected trust-anchor identifier.

The attestation cannot select its own trusted key. The exact source document is
stored in immutable CAS and its SHA-256, byte count, and `source_revision` must
all bind to those exact bytes. The caller must also supply the independently
expected source revision; the signed material and exact document must match it.
Fee basis points are signed as a decimal string, not a binary JSON float.

Successful verification means only that the configured trust-anchor holder
signed those exact configuration bytes. The mandatory classification remains:

`PAPER_RESEARCH_CONFIGURED_PUBLIC_FEE_SCHEDULE_NOT_ACCOUNT_SPECIFIC`

Both `account_specific_commission_authenticated` and
`upstream_exchange_signature_verified` must be exactly boolean `false`.

## Point-in-time clock rules

### Configured fee

The fee material carries separate clocks:

- `source_observed_at`: when the source document was observed;
- `effective_at`: when the configured schedule says the fee applies;
- `available_at`: when the signed configuration was available to the consumer;
- `decision_time`: supplied by the feature snapshot; and
- `expires_at`: explicit signed configuration expiry.

Admission requires:

`max(source_observed_at, effective_at) <= available_at <= decision_time < expires_at`

There is no consumer-side fee-age fallback or default.

### Order book and mark price

The shared causal validator requires one atomic Redis transaction over the
three exact source keys. For every source:

`event_time <= received_at <= available_at <= generated_at <= redis_server_observed_at <= decision_time`

The Redis PTTL is captured in the same transaction. The projected expiry must
still be after `decision_time`. Missing keys, missing/non-positive PTTL,
expired sources, future clocks, schema/identity changes, non-finite values, and
order-book sequence gaps fail closed.

Depth and feature payloads must describe the same direct Binance sequence and
clock chain. Bid/ask ordering, spread, depth summaries, and reference impact
are recomputed from exact levels. The cost impact is recomputed by walking both
sides at the exact causal notional and choosing the larger adverse impact.

The mark payload must be the direct Binance USD-M public mark-price websocket
schema. Funding is included only when the next settlement is strictly after
the decision and within the pinned 900-second outcome horizon. The venue rate
sign is preserved.

### Expected notional

Loose caller-supplied notional bytes are not accepted. The research builder
requires the exact `CausalExpectedNotionalPolicyTokenV1` factory type and
revalidates it before construction and on every result read. That token derives:

`gross_notional_usd / candidate_count`

from the hash-bound full allocator aggregate, not the truncated operator
display. Zero candidates, a static default, a fallback, an expired PTTL, a
future clock, CAS mutation, or a forged token fails closed. Its exact raw
status and source-read receipt are copied into the research evidence CAS.

## Output formulas

The ordered label-only outputs are:

1. `fee_bps`: signed configured taker fee per side;
2. `spread_bps`: `(best_ask - best_bid) / mid * 10_000`;
3. `expected_slippage_bps`: maximum adverse buy/sell depth-walk VWAP impact at
   the exact causal notional; and
4. `expected_funding_bps`: raw signed settlement rate times 10,000 when the
   settlement falls inside the pinned horizon, otherwise a proven zero.

The four values and receipts are float32-bound, ordered, hashed, and stored in
CAS. The artifact also commits the exact ordered inventory of every raw market,
fee, notional, and read-receipt CAS address (schema, SHA-256, byte count, and
relative path), plus an inventory count and digest. Every result access requires
the retained object inventory to match that artifact-bound inventory and then
reopens every object. A caller cannot omit a damaged source object while
retaining only the final artifact. The values are explicitly label-only and are
never model input slots.

## Authority matrix

Every result and scalar receipt fixes all of these to `false`:

| Capability | Authorized |
| --- | --- |
| Trainer admission | No |
| Optimizer execution | No |
| Checkpoint write | No |
| Model write | No |
| Prediction | No |
| Paper trading | No |
| Live trading | No |
| Order submission | No |
| Execution | No |
| Runtime wiring | No |

The result additionally fixes `profiled_account_lane_compatible=false`.
`profiled_training_enrichment_record_v1` rejects it because that factory
requires the exact account-authenticated `CausalCostEvidenceV1Result` type.

## What remains before research training can run

This cost seam removes Binance account credentials from the research cost
component, but it does not by itself unblock optimizer work. A safe research
trainer needs all of the following as separately reviewed versions:

1. An operator-managed fee configuration signer and a registry-owned public
   key/fingerprint/trust-anchor deployment. No private signing key may be
   bundled with the consumer.
2. A monotonic external fee-revision registry/cursor and signed fee-source
   artifact for each symbol/revision with honest expiry. The current primitive
   requires an independently expected revision but does not itself prove that
   no newer signed revision superseded it. The signature authenticates
   configuration, not exchange truth.
3. A separately typed research 35+4 enrichment record and atomic append
   contract. It must not reuse or relabel the profiled account-fee lineage.
4. A research observation manifest, independent external witness namespace,
   anti-rollback cursor/challenge, and complete fixed-observation consumption
   receipt.
5. A research optimizer admission adapter that reopens every CAS object and
   outcome label and remains unable to write checkpoints/models until a
   separate checkpoint lifecycle review grants that capability.
6. A train/serve projection and explicit promotion policy. Research artifacts
   must never become prediction, paper, or live authority through schema-width
   or field-name coincidence.
7. Runtime configuration, monitoring, key rotation, expiry alarms, and a
   fail-closed operator runbook.

Until those items exist, `research_cost_components_complete=true` means only
that this one cost component is complete. The emitted status remains:

`NOT_AUTHORIZED_SEPARATE_LEDGER_MANIFEST_WITNESS_AND_ADMISSION_REQUIRED`

## Cryptographic and market-data limitations

- The configuration signature proves possession of the configured signing key;
  it does not prove the public fee document is correct or current beyond the
  signed clocks and revision.
- Binance public websocket payloads have no upstream signature in this path.
  Their exact bytes, recorder identity, schema, sequence continuity, clocks,
  PTTL, and numerical semantics are revalidated and content-addressed, but the
  contract does not overclaim cryptographic exchange authenticity.
- The 900-second horizon is a versioned label ABI, not a market-entry threshold.
  Changing it requires a new evidence version and label compatibility review.

## Verification coverage

The adversarial unit suite covers:

- wrong registry key and fingerprint;
- altered signed material and altered signature;
- non-canonical attestation bytes;
- source-document substitution;
- future and expired fee clocks;
- account-authority and JSON boolean/integer type-confusion claims;
- expired market-source PTTL and future mark clocks;
- forged causal-notional factory tokens;
- CAS mutation, source-inventory omission, and result scalar substitution; and
- exact-type rejection by the profiled enrichment path.
