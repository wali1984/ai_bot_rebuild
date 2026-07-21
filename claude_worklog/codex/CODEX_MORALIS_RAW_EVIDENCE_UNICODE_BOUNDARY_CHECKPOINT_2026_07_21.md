# Moralis Raw-Evidence Unicode Boundary Checkpoint

Date: 2026-07-21

Scope: Moralis raw HTTP evidence only. No provider service, Redis runtime,
trainer, allocator, risk, paper, live, order, leverage, or margin behavior is
enabled by this checkpoint.

## Evidence counts

- registered endpoint contracts inspected: 14;
- current Moralis Redis keys inventoried before this change: 110, including 86
  raw keys and 0 trainer feature keys;
- candidate wallets inventoried: 270 (239 Ethereum, 14 Arbitrum, 17 Optimism),
  with 0 verified wallets;
- exact current `wallet_history` responses structurally examined: 1 response,
  100 records, approximately 198 KiB;
- bounded diagnostic provider requests charged through the durable ledger: 5
  requests at 150 CU each (750 CU total); no provider request is needed to
  validate this source change;
- backend routes or UI pages changed: 0;
- screenshots captured: 0 (no UI surface in this family);
- regression tests passed: 193 across raw evidence, registry/publisher, and
  semantic-receipt hardening;
- Python files compiled: 2;
- files linted: 2, with 0 findings;
- defects remaining before Moralis can be truthfully green: 3 families
  (endpoint-specific semantic projection, causal/post-commit clock receipts,
  and a real signed Streams webhook/registry path).

## Reproduced defect

One current `wallet_history` response was sampled through the existing durable
CU ledger. It returned HTTP 200 with 100 records and about 198 KiB of valid
identity-encoded JSON. UTF-8, JSON syntax, duplicate-key rejection, finite
numbers, configured depth/cardinality bounds, and the exact-body SHA-256 all
passed. Publication still classified the response as
`RAW_RESPONSE_JSON_INVALID` because an optional nested `token_name` contained a
Unicode format/control character.

The field was not a clock, transaction identity, amount, address, classifier
receipt, feature, or trainer input. Rejecting the complete raw receipt lost
valid provenance while providing no additional semantic safety.

## Boundary correction

Raw transport validation now has its own bounded JSON validator. It enforces:

- exact UTF-8 encodability;
- duplicate-key and non-finite rejection;
- response, canonical JSON, string, depth, node, list, and object resource
  bounds; and
- equality between the exact parsed HTTP bytes and the parsed payload supplied
  by the client.

It does not treat arbitrary provider-owned display metadata as semantically
safe. Valid control/format characters may exist only inside the exact raw body,
which is base64-wrapped in an authority-false source artifact. The existing
semantic normalizer remains strict and rejects/quarantines the payload before
it can contribute any Moralis feature.

## Authority and follow-on work

All publication, trainer, prediction, risk, orchestrator, allocator, paper,
live, order, and execution authorities remain false. This checkpoint restores
lossless raw evidence only; it does not make Moralis green.

The next separately committed family must project endpoint-specific semantic
fields from the raw response, bind each projection back to the exact response
and row ordinal, quarantine unsafe optional metadata field-wise, and establish
valid source-event and post-commit clocks before any feature bridge can become
available.
