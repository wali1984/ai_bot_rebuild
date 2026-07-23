# Authenticated Strategy TA Transform Checkpoint — 2026-07-23T07:09:43Z

## Immutable checkpoint

- Branch: `codex/strategy-receipt-promotion-20260723`
- Source commit: `b0bd338e3d7894d0e8caec355a8ab353caf63aca`
- Remote: `origin/codex/strategy-receipt-promotion-20260723`
- Push divergence after source push: `0 ahead / 0 behind`
- Production module SHA-256:
  `d2979df5ed6128e1c2124834f23315692c79660bdc0a22357071411aab9644f7`
- Test module SHA-256:
  `752ab64ae91b4fc68482085dc92571f9a20a1ae72222eb9bd9a2d9a2ab7629d1`
- Implementation identity SHA-256:
  `5763a9790ac93940831cac7106aa4c620c6201c5056b8e3f08b9b5c56c398f51`
- Configuration identity SHA-256:
  `63cd854621ae1f2db23dd0e81057b3d9c31c173494a949d29f2f2ce9c885c7c4`
- Ordered dependency-code root SHA-256:
  `ec7e0ceaecaae82d7a651e2a179a98fd4168e2d0aefe46eafa66e88cf2bb96cc`
- Known defects in this new component family: **0**

## Scoped result

The new standalone transform accepts only:

1. An exact factory-authenticated
   `CanonicalOhlcvWriterBoundAtomicCapture`.
2. An authentic `ImmutableSourcePayloadStore`.
3. The requested symbol and timeframe.
4. An injectable audit clock.

There is no Redis client, risk-profile document, provider payload, price
fallback, paper-account object, or live-execution interface in the public
function. The transform therefore cannot read the mutable canonical key a
second time and cannot consume `v2:live_gate:state`.

The source proof may bind an entire contiguous suffix longer than the
calculation dependency. In the genuine test path it bound **100** rows and
**100** per-candle receipts. The transform independently revalidates the exact
full writer-authenticated payload with the mathematical **89-row** TA
dependency, then calculates from the exact final 89 rows. It never claims that
only 89 upstream receipts existed and never splices an excluded prefix across
a gap.

The output is split into two immutable CAS artifacts:

1. Deterministic semantic content: exact source bytes/economic row identity,
   exact final-89 calculation identity, indicators, reference price, transform
   implementation/configuration, and pinned TA dependency identity.
2. Audit manifest: the semantic address plus the complete upstream receipt
   chain, genuine writer revision/role/code/config/receipt/allowlist, Redis and
   consumer observation clocks, generated time, and all false authority flags.

The same exact economic bytes under a new genuine writer revision produce the
same semantic bytes/hash and a different audit manifest/hash. The same writer
revision captured at different observation clocks behaves the same way.

## Evidence counts

- Files content-inspected for this boundary: **7**
- Callable routes inspected: **22**
- Current unsafe route chains inspected: **2**
- Trusted replacement source route inspected: **1**
- Existing field surfaces inventoried: **10**
- Existing composite fields / manifest fields: **75 / 72**
- New production/test files: **1 / 1**
- Existing files modified: **0**
- Production/test lines: **1,504 / 929**
- New result dataclass fields: **69**
- Bound code-dependency modules: **7/7**
- Required strategy indicators checked: **7/7**
- Genuine WSS source rows / receipts: **100 / 100**
- Genuine REST source rows / receipts: **100 / 100**
- Exact calculation rows: **89/89**
- Finite indicators in deterministic fixture: **219**
- Ordered non-null clocks checked: **15/15**
- Explicit null clocks checked: **3/3**
- Authority flags checked false: **10/10**
- Optional provider groups explicitly excluded: **14/14**
- Mutable external economics keys explicitly excluded: **1/1**
- Immutable output artifacts created/reopened: **2/2**
- Unit/adversarial test cases: **19/19 passed**
- Genuine-Redis integration cases: **4/4 passed**
- Primary final regression: **23/23 passed in 31.30s**
- Files compiled / full-linted / format-checked: **2/2 / 2/2 / 2/2**
- Pytest cases collected: **23/23**
- Whitespace findings: **0**
- Design defects exposed before final test: **2**
- Design defects fixed and regression-covered: **2/2**
- Test-only assertion drift exposed/fixed: **1/1**
- Production defects exposed by the final suite: **0**
- Defects remaining in this new family: **0**
- Routes / endpoints / screenshots / product builds: **0 / 0 / 0 / 0**
- Runtime services / production Redis keys / exchange actions changed:
  **0 / 0 / 0**

The two corrected design defects were:

1. The first draft treated the existing atomic suffix as exactly 89 rows. The
   actual contract receipts the entire valid contiguous suffix (100 in the
   regression fixture). The final implementation accepts a suffix of at least
   89 and binds the exact final 89 calculation rows without misreporting the
   upstream receipt count.
2. The first draft included writer revision/publication provenance in the
   semantic identity. The final split keeps numerical/economic semantics
   stable and moves revision, producer identity, writer receipt, publication
   clock, atomic receipt identities, and observation clocks into the audit
   manifest.

The only warning was the pre-existing unset `pytest-asyncio` loop-scope
deprecation warning. It did not alter collection or execution.

## Exact dependency identity

The ordered dependency-code root binds these seven module hashes:

1. Strategy transform:
   `d2979df5ed6128e1c2124834f23315692c79660bdc0a22357071411aab9644f7`
2. Full TA-Lib service:
   `dde82d42542446588ad92ccaff108acd9ef9c844655665b15feb950301e90b78`
3. Model TA technical-dependency contract:
   `c2143c9406379dcf281242221ab565975f05977c9f1a167a125499d7966d1cfb`
4. Writer-bound atomic composite:
   `ef87b28c90c41212b94c51c992a646dbc8c62e818404389d5919f4e077a877e7`
5. Canonical atomic receipt adapter:
   `a2da3769419f855bd1c9f4d0d498f7175ba2ece80c81d0d101e41fd70ac39c0b`
6. Canonical writer-receipt consumer:
   `f412790842273113c44c4c142d37b6c7468a85801ffb536379376ab23304103f`
7. Closed-OHLCV schema:
   `337e3d1b8f3c9ebb43f87e8472c4e7bd952278952a6df1b9931ba4e89a040966`

The semantic transform also carries and validates the frozen model TA
technical-dependency, deployed TA-Lib environment, model ABI, TA field-map,
TA field inventory, ABI-leaf, and lookback-manifest hashes. The TA environment
is inspected immediately before and after calculation; a mid-computation
identity change fails closed.

## Exact clock split

The audit manifest retains this **15-clock** order:

```text
feature_cutoff / latest economic close
<= max producer_event_time
<= max ingested_at
<= max source available_at
<= writer publication_available_at
<= pre-writer discovery Redis TIME
<= pre-writer authoritative Redis TIME
<= pre-writer consumer_observed_at
<= atomic-adapter Redis TIME
<= atomic-adapter consumer_observed_at
<= post-writer discovery Redis TIME
<= post-writer authoritative Redis TIME
<= post-writer consumer_observed_at
<= source-capture generated_at
<= transform generated_at
```

The semantic artifact retains the source-row economic close, producer event,
ingestion, and availability clocks because they describe the exact economic
input. It excludes all Redis/local observation clocks, both generated clocks,
the genuine writer revision/publication identity, and the upstream receipt
identities. `available_at`, `decision_time`, and `execution_time` remain
explicitly null because no later post-commit availability receipt or decision
has occurred.

## Point-in-time and finality invariants

1. Exact binary canonical source bytes only.
2. Genuine writer role/code allowlist proof only.
3. Pre/atomic/post writer revision and receipt stability.
4. Fresh immutable CAS reopen for source, semantic output, and audit manifest.
5. Exact 30-field closed-OHLCV schema validation.
6. Exact requested symbol, timeframe, and source-key binding.
7. At least 89 contiguous finalized rows; exact final 89 selected for TA.
8. No selected gap, duplicate identity, unfinished candle, or stale tail.
9. Final row equals the latest completed interval at transform generation.
10. Correct ordered `event_time`, `ingested_at`, `available_at`, publication,
    observation, and generation clocks.
11. Reference price is the positive finite close of the exact same final
    selected candle used for TA.
12. Seven strategy-critical indicators are finite; optional TA failures remain
    explicit rejections and are never zero-filled or back-scanned.

## Explicitly excluded optional inputs

Until each has an independent exact retained-artifact resolver and later
availability/admission receipt, this transform consumes none of these 14
groups: FVG, liquidity zones, liquidation levels, sweep risk, microstructure,
microstructure trust, order book, top-of-book, REST order book, trade tape,
trade-tape confirmation, CoinGlass, Moralis, and alt-data confluence.

This is not removal. It is a truthful typed absence. Later receipt families
can add each source without letting stale, missing, rate-limited, or
self-attested provider data silently alter the authenticated TA result.

## Legacy runtime defects still held outside this unwired slice

The current strategy runtime remains unchanged, so these **12** inventoried
defects still exist on the legacy route until the output-receipt/admission and
wiring gates are complete:

1. Direct unreceipted canonical Redis `GET`.
2. Writer-bound composite proof not consumed by the current publisher.
3. Current causal semantic hash includes `read_observed_at`.
4. Current TA result does not bind code/config/environment identity.
5. `v2:live_gate:state` changes economics without an exact receipt.
6. Builder/causal wall clocks are mixed into current artifact surfaces.
7. Current computed `available_at` has no post-commit receipt.
8. Current route accepts any non-empty finite indicator mapping.
9. Redis transport failure collapses into the same optional-missing mask.
10. Hypothesis and feature-vector identities contain a wall-clock minute.
11. `or`-based indicator selection treats legitimate numeric zero as missing.
12. Static market/economic constants remain in the downstream generator.

The new component resolves the applicable input/transform defects in an
isolated path but is intentionally not runtime-wired yet. Claiming those
legacy defects fixed before wiring would be false.

## Exact files in the source commit

1. `v2/backend/app/services/strategy_supply/authenticated_strategy_ta_transform_v1.py`
2. `v2/backend/tests/unit/services/strategy_supply/test_authenticated_strategy_ta_transform_v1.py`

Source diff: **2 files / 2,433 insertions / 0 deletions**.

## Commands executed

```text
rg/wc/sed targeted inspection of the seven boundary files and direct callers
<repo-venv>/bin/python inline deterministic 89-row TA inventory probe
<repo-venv>/bin/python inline genuine-Redis 100-row writer/capture/transform smoke
ln -s <repo .venv> .venv  # ignored temporary worktree environment identity
rm .venv                  # removed before staging
<repo-venv>/bin/python -m py_compile <production> <test>
<repo-venv>/bin/ruff check [--fix] <production> <test>
<repo-venv>/bin/ruff format [--check] <production> <test>
<repo-venv>/bin/python -m pytest --collect-only -q <focused test>
<repo-venv>/bin/python -m pytest -q <focused test>
git diff --check
git add -- <two exact source/test files>
git diff --cached --check
git commit -m 'feat(strategy): bind TA to authenticated OHLCV'
git push origin codex/strategy-receipt-promotion-20260723
sha256sum <seven dependency modules> <test module>
git rev-list --left-right --count '@{upstream}'...HEAD
```

## Runtime and execution boundary

No publisher, trainer, strategy generator, paper loop, allocator, risk
controller, leverage engine, margin logic, or live-execution path was changed
or restarted. Redis writes occurred only in disposable test servers. No paper
or live order, cancellation, position transition, leverage change, margin
change, or exchange action occurred.

## Next gate

Build a strategy-output publication receipt and paper-only admission boundary
that consumes this immutable transform. The later receipt must establish a
truthful post-commit `available_at`; the decision boundary must enforce
`feature_cutoff <= available_at <= decision_time`, retain
`execution_time=None`, and keep live execution false. Only then may the
strategy publisher replace the legacy direct-GET route and be released from
hold. Static market/economic constants must be converted to authenticated
adaptive policy inputs in their own reviewed slice rather than smuggled into
this transform.
