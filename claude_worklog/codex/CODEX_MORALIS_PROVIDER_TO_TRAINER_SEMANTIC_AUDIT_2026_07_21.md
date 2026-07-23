# Moralis provider-to-trainer semantic audit — 2026-07-21

Scope: read-only architecture audit plus one fail-closed compatibility-bridge
hardening patch. Base snapshot: `10555fbcd659b80d6b3179521c5358be83329ef6`.
No service, Redis, systemd, exchange, paper loop, trainer process, model, strategy,
risk, allocator, or live-execution state was changed.

## Outcome

Moralis is correctly optional to the trainer and must remain masked today.
The transport, CU accounting, raw evidence, source CAS, identity mapping, and
source-side semantic quarantine are materially stronger than the consumer
bridge. The missing boundary is not provider connectivity: it is an exact,
per-slot, post-commit consumer receipt chain and an authenticated trainer
selection/profile that can carry those receipts.

There is no safe global “Moralis ready” switch. Only three of the seven Moralis
ABI slots have a defined semantic producer, and the canonical runtime does not
currently pass the authenticated classifier receipts/key needed to produce even
those three. The other four must remain missing until distinct causal producers
exist.

One latent bypass was closed in this audit: the generic provider bridge could
translate a self-declared legacy Moralis Redis payload into provider features
before the tensor builder masked them later. It now rejects every Moralis
payload at that compatibility boundary with
`moralis:consumer_receipt_contract:exact_retained_artifact_resolver_unwired`.
Moralis remains optional and non-blocking.

## Claude handoff reconciliation

The audited code agrees with the active Claude handoff boundaries:

- Moralis is an optional enhancement, not a trainer/core availability gate.
- The public-plan authority is bounded to 2,000,000 CU/month.
- The loop must not poll every symbol every minute.
- BTC is native/non-token-pollable; WBTC or another ERC-20 must never be used as
  a BTC/BTCUSDT proxy.
- A source observation, successful `SET`, readback echo, or producer boolean is
  not trainer authority.
- Missing Moralis observations remain explicit masks; they are never zero-valued
  observations.
- Moralis can neither approve a trade alone nor bypass risk/orchestrator policy.

The older handoff list of 15 Moralis features is not the deployed ABI. The
current immutable 446-slot trainer ABI has exactly seven Moralis slots.

## Exact raw-provider to trainer path

```text
Moralis HTTPS response
  -> bounded identity-encoded body (maximum 262,144 bytes)
  -> SHA-256 + byte count + exact base64 body + transport clocks
  -> strict JSON (duplicate keys/non-finite values rejected)
  -> endpoint normalizer
  -> content-addressed raw Redis source artifact
  -> source-artifact exact-byte/TTL re-resolution
  -> per-symbol monotonic aggregate CAS
  -> masked five-key feature fanout + non-authoritative completion record
  -X- no authoritative per-slot post-commit receipt resolver
  -X- no authenticated Moralis selection in the profiled trainer
  -> all seven Moralis tensor slots remain missing/disabled
```

### Transport evidence schema and clocks

`MoralisClient` requests `accept-encoding: identity` and consumes
`httpx.Response.iter_raw`. Non-identity content encoding and a response beyond
262,144 bytes fail closed. The exact body is hashed before normalization.

The raw evidence schema is `moralis_raw_response_evidence_v1`:

- `raw_response_body_base64`: exact retained application-body bytes.
- `raw_response_byte_count` and `raw_response_sha256`: recomputed and compared
  with the client claims.
- `raw_response_bytes_scope`:
  `HTTPX_ITER_RAW_AFTER_TRANSFER_DECODING_WITH_IDENTITY_CONTENT_ENCODING`.
- `transport_started_at <= observed_at <= ingested_at <= generated_at`.
- `available_at` is intentionally `null`.

Provider row time is separate:

- `event_time`: source transaction/block timestamp on a contributing row.
- `feature_cutoff`: the maximum contributing row time for that feature.
- `observed_at`: when the HTTP response became observable.
- `ingested_at`: after bounded body ingestion.
- `generated_at`: when the normalized/publication envelope was built.
- `available_at`: must be a later durable consumer-visible post-commit
  observation; it is not currently produced.
- `decision_time`: trainer sample/prediction clock; every admitted slot must
  prove `available_at <= decision_time` and `feature_cutoff <= decision_time`.

The current source clock checks enforce
`event_time <= feature_cutoff <= ingested_at <= generated_at`. They correctly do
not infer `available_at` from any of those clocks.

## Redis and CAS key map

### Provider budget, rate, and scheduler authority

| Key | Value/role |
|---|---|
| `v2:provider:moralis:cu_usage:{YYYY-MM}` | Atomic monthly CU counter |
| `v2:provider:moralis:cu_usage:{YYYY-MM-DD}` | Atomic UTC-day CU counter |
| `v2:provider:moralis:cu_reservation:{32_hex}` | Pending/settled durable request reservation |
| `v2:provider:moralis:cu_budget_status` | `moralis_cu_budget_status_v2` |
| `v2:provider:moralis:rps_window:{redis_epoch_second}` | Provider-wide Redis fixed-second request count |
| `v2:provider:moralis:backoff` | Shared 401/402/403/429/5xx backoff state |
| `v2:provider:moralis:scheduler_status` | Scheduler status document |
| `v2:provider:moralis:scheduler_lease:{chain}` | Fenced single-scheduler lease |
| `v2:provider:moralis:cadence_claim:{chain}:{sha256(job_id)}` | Per-target no-sooner-than claim |
| `v2:provider:moralis:rotation_cursor_v2:{chain}` | Tier-first fair-rotation cursor |
| `v2:provider:moralis:cu_admission_credit` | Provider-global adaptive earned-CU credit hash |
| `v2:provider:moralis:cu_admission_reservation:{32_hex}` | Fenced pacing reservation |
| `v2:provider:moralis:health` | Non-authoritative provider health |
| `v2:provider:moralis:usage` | Non-authoritative usage projection |
| `v2:provider:moralis:endpoint_status` | Per-endpoint observation status |

The request ledger and paced-credit ledger are not competing spend authorities.
The paced ledger controls fair admission; `MoralisCuBudget` is the final durable
day/month spend authority. A request reserves CU atomically before dispatch.
Every received response reconciles against provider CU headers. Ambiguous
delivery remains conservatively charged. Redis/CU authority failure blocks only
Moralis polling.

The documented cap is 40 RPS over the provider window, while the implementation
uses at most 30 requests per Redis UTC-second. Five overlapping fixed-second
buckets therefore cap an arbitrary four-second window at 150, below 160. Normal
mode is 5 RPS and catch-up is 10 RPS. These are provider safety limits, not
static market thresholds.

The monthly ceiling is 2,000,000 CU. The default daily budget is 55,000 with a
10,000 reserve, producing a 45,000 hard daily spend cap. The effective daily
allowance is also reduced adaptively from remaining monthly CU and remaining
UTC days. The scheduler earns the minimum of remaining-day and remaining-month
CU per future scheduler opportunity; it does not inflate every target cadence
by backlog size.

### Identity/bootstrap keys

| Key | Schema/role |
|---|---|
| `v2:moralis:token_map:{symbol}` | `moralis_token_map_symbol_v1` |
| `v2:moralis:token_map_status` | `moralis_token_map_status_v1` |
| `v2:moralis:wallet_watchlist` | Candidate wallet watchlist |
| `v2:moralis:wallet_watchlist_status` | Watchlist status |
| `v2:moralis:wallet_profile:{chain}:{address}` | Wallet profile |
| `v2:moralis:wallet_activity:{chain}:{address}` | Wallet activity |
| `v2:moralis:excluded_addresses` | Exclusion/classification status |
| `v2:moralis:address_classification:{chain}:{address}` | Address classification |

A token endpoint is pollable only when the code-owned seed row, published row,
chain/address identity, metadata cache, token symbol, and decimals agree. Native
BTCUSDT/ETHUSDT mappings use contract `native` and
`token_endpoint_supported=false`, so they cannot enter the EVM token map. The
reverse lookup is `(canonical chain, exact contract) -> unique trading symbol`;
ambiguous identities are quarantined. There is no BTC/WBTC proxy path.

### Raw, metadata, aggregate, and feature keys

| Key | Schema/role |
|---|---|
| `v2:moralis:raw:v2:{endpoint_id}:{source_identity_sha256}:{source_payload_sha256}` | Content-addressed `moralis_normalized_payload_v2` source observation plus exact raw-body evidence |
| `v2:moralis:manifest:v2:token_metadata:{source_payload_sha256}` | Immutable `moralis_token_metadata_manifest_v2` |
| `v2:moralis:index:v2:token_metadata:{chain}:{token}` | CAS-updated metadata index bound to manifest and raw source |
| `v2:moralis:feature_aggregate:{symbol}:{timeframe}` | `moralis_feature_aggregate_v2`, monotonic exact-byte CAS |
| `v2:features:moralis:{symbol}:{timeframe}` | Masked `moralis_feature_bridge_v2` |
| `v2:features:provider:moralis:{symbol}:{timeframe}` | Same masked provider projection |
| `v2:smart_money:signals:{symbol}` | Same masked symbol signal projection |
| `v2:provider:moralis:symbol_score:{symbol}` | Masked `moralis_symbol_score_v2` |
| `v2:provider:moralis:feature_bridge_status` | Cross-symbol observability only |
| `v2:provider:moralis:fanout_completion:{symbol}:{timeframe}` | `moralis_feature_fanout_completion_v1` exact artifact hashes |

The raw key identity is SHA-256 over
`{schema_version, endpoint_id, group, chain, identity_kind, identity_value,
symbol}`. The aggregate admits an endpoint row only after exact raw-key bytes,
digest, TTL, raw response evidence, clocks, feature evidence, origin, and (for
exchange flow) classifier evidence pass. Its Lua CAS rejects concurrent stale
writes, same-clock divergent content, and older source events.

The fanout completion verifier proves exact bytes and TTL for the four
symbol-scoped artifacts (the global status key is excluded). It deliberately
requires `features={}`, `admitted_feature_count=0`, `available_at=null`,
`postcommit_receipt_bound=false`, all authorities false, and isolation active.
It is evidence that masking completed, not evidence that trainer consumption is
safe.

## Deployed Moralis trainer ABI

All seven slots are `OPTIONAL_EVENT_DEPENDENT`, configured source
`v2:features:moralis`:

1. `moralis_exchange_inflow_usd`
2. `moralis_exchange_outflow_usd`
3. `moralis_net_exchange_flow_usd`
4. `moralis_whale_net_flow_usd`
5. `moralis_smart_wallet_accumulation_score`
6. `moralis_smart_wallet_distribution_score`
7. `moralis_onchain_risk_score`

Only the first three have a semantic derivation today. They require row-level
USD value plus an HMAC-authenticated classifier receipt bound to exact chain,
endpoint, request target, symbol, transaction hash, log index, source event ID,
source-row SHA-256, event time, classifier registry key/version/digest, and
classifier-source key/digest. Positive net flow means inflow minus outflow.

The canonical provider loop currently calls `publish_moralis_result` without
`authenticated_classifier_receipts`, `classifier_authentication_key`, or
`classifier_authentication_key_id`. Therefore the live code path cannot produce
those three source features; it emits explicit rejection reasons instead.

The remaining four have no honest causal producer:

- a balance/net-worth snapshot is not whale net flow or accumulation;
- a current holder count/page is not a holder delta or distribution statistic;
- observed swaps without a complete classified whale window are diagnostics;
- token price or metadata presence is not an on-chain risk score;
- stream event counts have no USD-flow semantics.

Diagnostics are retained under nine explicitly scoped names and never alias into
the seven ABI slots.

## Trainer consumption audit

There are four independent fail-closed fences:

1. `services/altdata/provider_feature_bridge.py::load_moralis_input` always
   returns `present=False` because it has no retained-key receipt verifier.
2. `native_trainer/dataset_builder.py` does not merge Moralis into the
   compatibility dataset.
3. `hybrid_cuda_trainer/data_loader.py` does not fetch legacy Moralis keys for
   snapshot construction.
4. `hybrid_cuda_trainer/tensor_builder.py` force-sets all seven Moralis slots to
   `None` and preserves their missing masks even if injected through a provider
   context or direct bridge payload.

The profile-aware trainer is also not an enablement path. Its current profile
physically proves 35 selected OHLCV model features plus four label-only cost
inputs. Moralis ordinals have selection mask 0, value 0, availability 0, no
receipt root, and are explicitly runtime-unwired. A new authenticated profile
and model lineage are required before any Moralis ordinal can be selected.

## Minimum safe partial-integration contract

This is the minimum sequence; skipping a step is a NO-GO:

1. Implement a canonical classifier producer and immutable registry/source
   artifacts. Wire authenticated per-event classifier receipts and a protected
   HMAC credential into the provider loop. This can initially make only the
   three exchange-flow slots source-ready.
2. After aggregate CAS, create a content-addressed immutable publication receipt
   from an exact post-commit Redis read. Bind aggregate bytes/digest/key/TTL,
   every contributing raw source key/digest/expiry, classifier artifacts, symbol,
   timeframe, and the exact slot evidence/value.
3. Give every admitted slot its own clocks and receipt root. Do not use the
   aggregate maximum clock as a substitute for per-slot evidence. Require
   `event_time <= feature_cutoff <= ingested_at <= generated_at <= available_at
   <= decision_time` and expiry beyond the consuming decision.
4. Build a consumer-side retained-key resolver that reads exact bytes with strict
   UTF-8/JSON, re-hashes them, checks TTL/expiry, re-verifies semantic evidence,
   and admits only the ABI whitelist. Embedded producer authority booleans must
   be ignored.
5. Extend the authenticated trainer profile/projection for only the proven
   Moralis ordinals. Preserve per-slot missing=1/availability=0/no receipt when
   an event-dependent observation is absent. Do not enable prediction/paper
   use until a newly trained model is bound to that exact profile and receipt
   graph.
6. Keep the four unsupported slots masked. Partial admission is per slot, never
   a provider-global ready flag.

## GO / NO-GO

- **GO:** keep Moralis polling optional; keep CU/rate/cadence controls; retain
  diagnostics and source evidence; ship the compatibility bridge hardening.
- **GO:** implement the classifier and receipt/profile contracts as isolated,
  test-only slices without unmasking runtime consumption.
- **NO-GO:** flip `MORALIS_*_BOUND` constants, trust fanout `SET` readback,
  accept self-declared receipt flags, merge raw Moralis maps into snapshots,
  synthesize absent values as zero, proxy WBTC to BTCUSDT, or enable all seven
  slots because one slot has evidence.
- **NO-GO:** describe Moralis as trainer-integrated today. It is source-visible,
  budget-controlled, and correctly isolated; it is not yet trainer-consumable.
