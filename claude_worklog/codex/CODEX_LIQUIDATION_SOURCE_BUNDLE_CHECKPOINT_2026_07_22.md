# Liquidation Source-Bundle Checkpoint — 2026-07-22

## Outcome

Prospective liquidation-surface publications now carry the exact Redis bytes
and original consumer-observation clocks used to construct each candidate.
The bundle is inside the content-addressed surface archive and is therefore
bound by the existing postcommit SHA-256/HMAC receipt and exact Redis reopen.

This closes the prior reconstruction race: a later trainer consumer no longer
needs to re-read mutable candle, mark-price, CoinAnk OI, or bracket cache state
and pretend those later bytes produced the earlier surface.

## Safety contract

- finalized candle bytes, mark-price bytes, selected CoinAnk Plan3 OI bytes,
  original consumer clocks, and authenticated bracket-reader proof are stored;
- raw source bytes use bounded `zlib_base64_v1` transport, retain their original
  byte count and SHA-256, and are decompressed under the canonical-size ceiling;
- model payload hashing excludes the non-model source bundle while the archive
  receipt binds both together;
- a trainer-eligible pointer is written only when semantic eligibility **and**
  a receipt-bound prepared source bundle are both present;
- source-bundle reconstruction accepts only a factory-created verified
  publication and re-derives the model, manifest, masks, and hashes;
- every authority bit in the bundle remains false;
- no prediction, paper, live, order, leverage, or margin authority is added.

## Evidence counts

- source families preserved: 4 required + 1 optional mask slot;
- universe/runtime producer paths changed: 1;
- receipt fields added: 5;
- relevant tests passed: 325;
- Ruff violations: 0;
- live source lanes sized: 795/795 (0 missing finalized-candle payloads);
- live raw source bundle: 104,936-byte maximum before compression;
- live finalized-candle compression: 76.59 MB -> 17.86 MB after Base64
  transport across all 795 lanes (one measured universe snapshot);
- current model archive maximum inspected: 45,016 bytes;
- post-bracket Redis clock ordering regression found by the first live cycle:
  678/795 lanes initially failed closed because bracket `available_at` followed
  the proposed lane cutoff;
- corrective dry-run: BTCUSDT/1m rebuilt with 100 candles, 1 exact mark sample,
  2 OI observations, 12 authenticated brackets, no model rejection, and a
  74,847-byte complete archive;
- corrected full live cycle: 795/795 candidates, publications, and verified
  bundles; 390 trainer-candidate pointers; 405 masked observations; 159/159
  bracket symbols; 159/159 CoinAnk OI symbols; 0 build/publication errors;
- corrected full-cycle duration: 183,453 ms. The former 180-second receipt and
  status retention could not provide continuous pointer/status coverage, so
  storage-only retention is now 600 seconds for archives/status and 540 seconds
  for receipts/pointers, with an explicit measured margin and coverage gate.

## Final deployed retention-gated cycle

Release `450c46147d` completed one full live cycle with:

- status/reason: `COMPLETE` /
  `ALL_LANES_PUBLISHED_WITH_CONTINUOUS_POINTER_COVERAGE`;
- candidates built / lanes published / bundles verified: `795 / 795 / 795`;
- trainer candidates / masked observations: `415 / 380`;
- authenticated bracket symbols / adaptive CoinAnk OI symbols: `159 / 159`;
- build errors / publication errors: `0 / 0`;
- cycle duration: `167,929 ms`;
- measured receipt/pointer retention margin: `372,071 ms`;
- service restarts: `0`.
- publication/trainer authority grants added: 0;
- live exchange mutation paths changed: 0.

## Files in this component family

- `v2/backend/app/services/liquidation_surface/trainer_admission.py`
- `v2/backend/app/services/liquidation_surface/publication.py`
- `v2/backend/app/services/liquidation_surface/producer.py`
- `v2/backend/app/cli/v2_liquidation_surface_publisher.py`
- `v2/backend/tests/unit/services/liquidation_surface/test_trainer_admission.py`
- `v2/backend/tests/unit/services/liquidation_surface/test_publication.py`
- `v2/backend/tests/unit/services/liquidation_surface/test_producer.py`
- `claude_worklog/codex/CODEX_LIQUIDATION_SOURCE_BUNDLE_CHECKPOINT_2026_07_22.md`

## Remaining gate

The exact bundle can now be reopened safely, but no native-trainer decision
consumer is wired in this checkpoint. The next component must open the latest
trainer-eligible surface at the trainer's own decision time, evaluate the
decision-scoped admission receipt, project admitted level fields into the
existing liquidation feature slots, and preserve a full missing mask whenever
that admission fails.
