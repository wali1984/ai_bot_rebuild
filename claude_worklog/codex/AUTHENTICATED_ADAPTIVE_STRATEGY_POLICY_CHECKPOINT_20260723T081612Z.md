# Authenticated Adaptive Strategy Policy Checkpoint — 2026-07-23T08:16:12Z

## Immutable checkpoint

- Branch: `codex/strategy-receipt-promotion-20260723`
- Implementation commit: `2e46a6c50d2cb937000975b6937c8f73f5998dd5`
- Commit pushed: **yes**
- Upstream divergence after push: **0 ahead / 0 behind**
- Worktree after implementation push: **clean**
- Runtime state: legacy strategy publisher remains deliberately held and inactive
- Deployment decision: **NO-GO for candidate/PAPER release**
- Scope completed: authenticated adaptive TA-only raw directional proposal

## Family completed

This slice adds one unwired, factory-only adaptive strategy-policy boundary.
It consumes only a `VerifiedStrategyOutputPublicationV1`, reopens the exact
factory-bound `AuthenticatedStrategyTaTransformV1`, independently validates
the writer-authenticated closed-OHLCV bytes, and calculates one raw
one-timeframe directional proposal.

The proposal is adaptive because all four expert weights are derived from the
same artifact's prior-only walk-forward errors. It has no market score cutoff,
fixed expert weights, confidence cutoff, reward/risk cutoff, ATR multiplier,
or mutable live-gate input. Exact zero is structural neutrality.

This is not a candidate. Fees, spread, slippage, funding, notional, account,
margin, position, risk, and leverage evidence remain absent and explicit.
Consequently prediction, PAPER, live, and order authority all remain false.

### Files

1. `v2/backend/app/services/strategy_supply/authenticated_adaptive_strategy_policy_v1.py`
2. `v2/backend/app/services/strategy_supply/authenticated_strategy_output_publication_v1.py`
3. `v2/backend/tests/unit/services/strategy_supply/test_authenticated_adaptive_strategy_policy_v1.py`

SHA-256 identities:

- Policy production file:
  `aa52daa2fd10313f176c2f46ba028fda782d08c6d1651ce91b324359fa35714a`
- Output-publication file after the revalidating upstream accessor:
  `887c01f3f0eb1d76bf2aef10ecf60248c6041213b3e9ba238edec935e6b5047f`
- Focused test file:
  `392c561be686cf87c81c5700be96acb7e9b2fb21d42e3cbadffe9b3762a8a34d`

## Exact evidence counts

- Production result fields: **77**
- Production module functions: **26**
- Exact authenticated calculation rows: **89**
- Prior-only walk-forward evaluations: **87**
- Exact prefix histories checked by test: **87**, plus the final 89-row forecast history
- Adaptive experts: **4**
- Fixed expert weights: **0**
- Market-performance/score cutoffs: **0**
- Immutable policy CAS artifacts: **2** (semantic content and audit manifest)
- Exact dependency code hashes: **5**
- Ordered point-in-time clocks: **11**
- Genuine Redis strategy-output objects reopened: **4**
- Null economic/state receipts: **4**
- Explicitly excluded economic/state inputs: **11**
- Explicitly excluded mutable legacy inputs: **4**
- Optional-provider inputs consumed: **0**
- Upstream optional-provider groups still explicitly excluded: **14**
- Candidate/output/prediction/PAPER/live/order authorities granted: **0 / 0 / 0 / 0 / 0 / 0**
- HTTP routes inspected/changed: **0 / 0**
- Endpoints compared: **0**
- Screenshots captured: **0**
- Frontend/iOS builds run: **0** (later product family by explicit ordering)
- Services started/restarted: **0**
- Production Redis writes: **0**
- Exchange calls, orders, cancellations, leverage, or margin mutations: **0**
- Defects remaining inside this isolated family: **0**

## Adaptive calculation contract

For the exact final 89 authenticated closed candles, the implementation uses
natural-log close-to-close returns and four one-step experts:

1. expanding mean log return;
2. last-return momentum;
3. last-return reversion;
4. least-squares log-price trend.

For every target after the mathematical two-price minimum, each expert sees
only the exact prefix preceding that target. Its mean squared error is derived
over all 87 available one-step evaluations. Weights are normalized inverse
error. If one or more experts have exact zero error, weight is shared equally
only among those exact-zero experts; no epsilon or floor is introduced.

The current ensemble forecast is the adaptive weighted sum. Predictive
uncertainty combines each expert's prior residual MSE with its current
disagreement from the ensemble. Outputs include:

- exact-sign `UP`, `DOWN`, or structural `NEUTRAL` proposal;
- expected log return and expected move bps;
- uncertainty log return;
- separate, numerically consistent up/down uncertainty bps;
- separate non-executable lower/upper uncertainty prices;
- one non-executable expected target price;
- a bounded directional signal-strength ratio explicitly labeled
  `NOT_A_PROBABILITY`.

No output is represented as calibrated win probability, executable target,
stop, candidate, quantity, or order instruction.

## Point-in-time and availability contract

The factory revalidates this complete order:

```text
feature_cutoff
<= max_source_available_at
<= writer_publication_available_at
<= capture_generated_at
<= transform_generated_at
<= output_generated_at
<= output_available_at
<= output_receipt_postcommit_observed_at
<= output_consumer_reopened_at
<= proposal decision_time
<= proposal generated_at
```

At `decision_time`, the exact source's latest candle close must equal the
latest fully completed interval for the source timeframe. Every source row's
`available_at` must also be no later than `decision_time`. A stale source,
unfinished/dirty candle, gap-shortened suffix, future source availability,
pre-reopen decision, or regressing generation clock fails closed.

The policy artifact itself has `available_at=None`; its two CAS captures are
not misrepresented as a downstream publication receipt. A later authenticated
publication/admission boundary is still required before any consumer may use
the proposal as authority. `execution_time` remains `None`.

## Immutable and code identity contract

The semantic artifact binds the exact output ID/payload/receipt, upstream TA
semantic and audit hashes, exact OHLCV payload hash, exact calculation window,
forecast result, adaptive weights, source timeframe, implementation identity,
configuration identity, and dependency root.

The audit artifact binds the semantic address, all 11 clocks, downstream hold,
and these five exact source modules:

1. `authenticated_adaptive_strategy_policy_v1.py`
2. `authenticated_strategy_output_publication_v1.py`
3. `authenticated_strategy_ta_transform_v1.py`
4. `ohlcv_closed_window_schema.py`
5. `immutable_source_payload_store.py`

Both artifacts are written through the existing immutable, fsync-backed CAS
and immediately reopened byte-for-byte. Result validation re-derives the
complete proposal and both canonical documents, recomputes every code/hash
identity, and reopens both CAS objects again.

## Test and quality evidence

- Focused pytest cases: **21 / 21 passed in 207.15 seconds**
- Focused test functions: **15**
- Genuine writer-authenticated TA transforms: **1**
- Genuine Redis output publications: **1**
- Genuine Redis output objects checked: **4**
- Exact-prefix future-leak checks: **88** (87 evaluated prefixes + final history)
- Regime-dependent adaptive-weight cases: **2**
- Arbitrarily small nonzero-direction cases: **2**
- Exact-zero neutrality/zero-MSE branch cases: **1**
- Invalid close-price cases: **4**
- Stale/pre-reopen/regressing clock cases: **3**
- Factory/store type cases: **2**
- Result/address forgery cases: **2**
- Postconstruction CAS corruption/deletion cases: **4**
- Exact dependency-file identities checked: **5**
- Python files compiled: **3 / 3**
- Ruff findings: **0**
- Ruff format drift: **0**
- Git whitespace errors: **0**
- Independent targeted review defects fixed: **6 / 6**
- Independent targeted re-review regressions: **0**
- Pre-existing warnings: **1** pytest-asyncio default-loop-scope deprecation

Final focused command/result:

```text
PYTHONPATH=. .venv/bin/python -m pytest -q \
  v2/backend/tests/unit/services/strategy_supply/test_authenticated_adaptive_strategy_policy_v1.py
21 passed in 207.15s
```

The temporary `.venv` symlink was removed before static verification and
staging.

## Defects found and corrected before commit

1. The first focused attempt invoked the shared interpreter through its main
   worktree absolute path. The pinned trainer environment correctly rejected
   that different interpreter identity. The isolated worktree `.venv` path was
   used for authenticated runs; no production contract was weakened.
2. One draft test referenced `output_available_at` on the upstream result
   instead of its actual `available_at` field. The test was corrected; the
   production assertion had already passed.
3. The first future-leak test checked prefix lengths only. It now compares all
   87 exact prefix values plus the final 89-row history.
4. The first dependency root omitted the immutable CAS implementation. The
   final root binds five modules and tests every hash in order.
5. The first uncertainty bps field represented the upper lognormal move while
   a directional uncertainty price could represent the lower move. The final
   schema emits consistent up/down bps and lower/upper prices independently.
6. The first bounded ratio was named `directional_confidence`. It is now
   `directional_signal_strength` and explicitly declares that it is neither a
   calibrated probability nor a win-rate estimate.
7. The first CAS adversarial test forged only an address. The final suite also
   corrupts and deletes semantic and audit objects after construction.
8. The first no-threshold assertion only checked empty configuration lists.
   The final suite proves arbitrarily small positive/negative forecasts and
   the exact-zero tie branch.
9. The first fixture used a fake Redis output publisher after a genuine writer
   capture. The final fixture uses the genuine three-phase Redis publication
   factory and reopens all four output objects.

## Commands executed for this family

Read-only shell commands, in execution order by command family:

```text
git status --short --branch && git log -5 --oneline --decorate && wc -l <3 files>
rg -n <class/function/property patterns> <output and TA modules>
sed -n <targeted ranges> <output, TA, writer-bound capture, OHLCV schema,
  immutable store, and focused test files>
rg -n <capture/window/test helper patterns> <targeted files>
git diff -- <output publication file>
git check-ignore -v <new policy file>; git ls-files --error-unmatch <new policy file>;
  git status --short --untracked-files=all
wc -l <new files>; git diff --stat; git status --short
rg -n <authority/clock/threshold/economic terms> <new policy file>
rg -n <finality fields> <OHLCV schema>; sed -n <row validation range> <OHLCV schema>
python3 -c <AST field/function/test/numeric-literal inventories>
sha256sum <3 family files>
git rev-parse HEAD
git rev-list --left-right --count HEAD...origin/codex/strategy-receipt-promotion-20260723
git status --short --branch
wc -l <prior checkpoint>; sed -n '1,260p' <prior checkpoint>; date -u +%Y%m%dT%H%M%SZ
```

Mutation and verification shell commands:

```text
python3 -m py_compile <policy, output-publication, test files>
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/ruff check <3 files>
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/ruff format --check <3 files>
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/ruff format <policy and test files>
PYTHONPATH=. /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q <focused test>
ln -s /home/wali/Desktop/AI\ BOT\ REBUILD/.venv .venv
PYTHONPATH=. .venv/bin/python -m pytest -q <focused test>
PYTHONPATH=. .venv/bin/python -m pytest -q <corrected single test>
PYTHONPATH=. .venv/bin/python -m pytest -q <pre-review 16-case family>
rm .venv
PYTHONPATH=. /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q
  <8-case numerical/API subset>
ln -s /home/wali/Desktop/AI\ BOT\ REBUILD/.venv .venv
PYTHONPATH=. .venv/bin/python -m pytest -q <final 21-case family>
rm .venv
git diff --check
git add -- <exact 3 family files>
git diff --cached --check
git diff --cached --stat
git diff --cached --name-status
git commit -m 'feat(strategy): authenticate adaptive TA proposal'
git push origin codex/strategy-receipt-promotion-20260723
```

All source/test/document edits used `apply_patch`; formatting was the only
bulk mechanical rewrite. Test mutation occurred only inside pytest temporary
CAS roots and disposable local Redis servers.

## Runtime and execution boundary

No legacy publisher, inventory reader, trainer, allocator, orchestrator, risk
controller, paper loop, leverage engine, margin logic, website, iOS client, or
live-execution path was edited or restarted. No systemd unit was touched. All
Redis writes targeted disposable test servers. No real or paper order was
submitted, cancelled, or modified.

## Blockers intentionally retained

An actionable PAPER candidate still lacks seven authenticated boundaries:

1. factory-authenticated order-book/mark source evidence;
2. cost evidence whose market bytes and fee bytes both have authenticated
   producer/publication receipts;
3. non-circular expected notional for a zero-candidate bootstrap;
4. authenticated paper equity, margin, exposure, and risk-budget snapshot;
5. decision-time position-state consumer with a unique per-symbol state;
6. an exact transition validator that rejects unknown states instead of
   normalizing them to `FLAT`;
7. a candidate/output publication schema that can bind the completed policy
   and retain PAPER-only authority while live/order authority stays false.

The existing cost artifact is audit-only, the current expected-notional token
is label-only and circular at zero candidates, and the generic position helper
maps unknown values to `FLAT`. None is promoted by this checkpoint.

Therefore the legacy publisher and five downstream held services must remain
held. This checkpoint does not claim that the publisher is online or that
candidate supply is restored.

## Next gate

Build the smallest authenticated economic/state chain needed for a truthful
PAPER-only candidate, beginning with producer-authenticated cost evidence and
a non-circular paper account/notional source. Position state and transition
evidence must then be exact and fail closed. Only after those receipts exist
may a new candidate publication attach this adaptive proposal and PAPER
admission be reconsidered. Live execution remains out of scope.
