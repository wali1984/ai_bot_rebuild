# Phase 2D CoinAnk Discovery List - Pass 21 BTCUSD_PERP Quote Classification Fix

## 1. Decision

Pass 21 fixes the actual Codex finding from `07_CODEX_REVIEW.md`:

> `BTCUSD_PERP` is not classified as inverse USD perpetual, and the
> required fixture-only test suite fails.

Passes 19 and 20 addressed the cosmetic `END_FILE: <path>` pollution that
was breaking parsing, but neither pass touched
`v2/backend/app/domain/symbols/coinank_rows.py:_classify_quote_kind`.
Re-running supervisor task 042 against the unmodified module would re-emit
the same `PHASE2_COINANK_DISCOVERY_LIST_CODEX_FAIL` because
`test_coinank_btcusd_perp_marked_inverse_and_does_not_collapse_with_usdm`
still fails: `is_perp_inverse` resolves to `False` because `quote_kind`
returns `OTHER` instead of `USD`.

Pass 21 changes one function (`_classify_quote_kind`). It strips a trailing
`_PERP` or `_NNNNNN` (dated) suffix from a stem copy before checking the
quote suffix, so `BTCUSD_PERP` resolves to `quote_kind == "USD"`, and then
`is_perp_inverse = bool(PERP_SUFFIX_RE.search(symbol)) and quote_kind == "USD"`
becomes `True`. No other function, dataclass, signature, fixture, test, or
adapter is changed.

## 2. Root cause

`_classify_quote_kind("BTCUSD_PERP", None)` walked through the suffix
checks:

- `endswith("USDT")` -> False
- `endswith("USDC")` -> False
- `endswith("USD")` -> False (the symbol ends in `_PERP`)
- `endswith("BTC")` -> False
- `endswith("ETH")` -> False
- Returned `"OTHER"`

`is_perp_inverse = bool(PERP_SUFFIX_RE.search(symbol)) and quote_kind == "USD"`
required both the `_PERP` regex match AND a `USD` quote, but the `_PERP`
suffix itself prevented the `USD` quote from being detected. The two
conditions were mutually exclusive for inverse-perp symbols.

The same blind spot affected dated contracts: `BTCUSD_260626` returned
`quote_kind == "OTHER"` even though it is conceptually a `USD`-quoted
dated delivery.

## 3. Pass 21 actions

Re-emit `v2/backend/app/domain/symbols/coinank_rows.py` with
`_classify_quote_kind` updated to:

1. Build a `stem` copy of the upper-cased symbol.
2. If `PERP_SUFFIX_RE.search(stem)` matches, slice the stem before the
   `_PERP` suffix.
3. Else if `DATED_SUFFIX_RE.search(stem)` matches, slice the stem before
   the `_NNNNNN` suffix.
4. Run the same five `endswith` checks against the stem.

The fix is local to one function. The `is_perp_inverse`, `is_dated`,
`candidate_for_usdm_confirmation`, identity construction, alias building,
and confirmation logic are byte-identical to Pass 20.

## 4. Expected test impact

After Pass 21 materializes and `pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py` runs:

- `test_coinank_btcusd_perp_marked_inverse_and_does_not_collapse_with_usdm`
  passes: `quote_kind == "USD"` and `is_perp_inverse == True`.
- `BTCUSD_PERP.candidate_for_usdm_confirmation` stays `False` because
  `quote_kind` is `"USD"` (still not in `{"USDT", "USDC"}`).
- `match_cross_source_symbol(coinank_btcusd_perp, usdm_btcusdt)` still
  returns `"none"` because `base+quote` differ (`USD` vs `USDT`).
- `test_coinank_dated_does_not_collapse_with_perpetuals` still passes:
  `is_dated == True`, `contract_type == "dated_delivery"`,
  `candidate_for_usdm_confirmation == False`. `quote_kind` improves from
  `"OTHER"` to `"USD"` but no assertion depends on the prior value.
- `test_coinank_btcusdt_is_discovery_only_with_low_confidence`,
  `test_coinank_btcusdt_does_not_collapse_with_usdm_btcusdt`,
  `test_coinank_usdc_separate_from_usdt`, `test_ethbtc_not_usdm_candidate`,
  `test_stock_like_marked_and_blocked_from_confirmation`,
  `test_chinese_name_preserved_and_blocked_from_confirmation`,
  `test_confirmation_requires_usdm_present_and_trading`,
  `test_adapter_emits_identities_with_alias_set`, and
  `test_adapter_confirm_against_usdm_returns_only_valid_matches` all
  continue to pass because their symbols have no `_PERP` or `_NNNNNN`
  suffix and the stem stripping is a no-op for them.

Expected pytest result: `11 passed`.

## 5. Out of scope

- No change to `v2/backend/app/domain/symbols/normalization.py`.
- No change to `v2/backend/app/adapters/symbol_sources/coinank.py`.
- No change to the synthetic fixture or the test file.
- No change to `v2/legacy_preserved/ingestors/live_coinank.py`.
- No change to `legacy_reference/**`.
- No change to `/home/wali/Desktop/AI BOT/**`.
- No `.env` file is read or printed. No secret value is read or printed.
- No live API call. No Redis read, write, or delete. No exchange action.
- No leverage or margin change. No live-trading enablement.
- The user-supplied `/home/wali/Downloads/coinanksymbols.odt` is not
  committed; ingesting the actual ODT into a real fixture remains a
  follow-up after REQ_0002 closes through Codex review.

## 6. Operator validation steps after Pass 21 materializes

Run from `/home/wali/Desktop/AI BOT REBUILD`:

1. `python3 -m py_compile v2/backend/app/domain/symbols/coinank_rows.py`
   Expected: no output, exit 0.
2. `python3 -m json.tool < claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json > /dev/null`
   Expected: exit 0.
3. `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
   Expected: `11 passed`.
4. `tail -n 1 v2/backend/app/domain/symbols/coinank_rows.py`
   Expected: `    return None` (last real line of `confirm_coinank_against_usdm`).

If all four pass, stage and commit:

- `v2/backend/app/domain/symbols/coinank_rows.py` (Pass 21 quote fix)
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/21_REMEDIATION_BTCUSD_PERP_QUOTE_FIX.md`
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
  (re-emitted with `21_REMEDIATION_BTCUSD_PERP_QUOTE_FIX.md` added to the
  Codex input list and the prompt refreshed to expect a passing test suite)

Suggested commit message:

    Phase 2D CoinAnk discovery list - pass 21 BTCUSD_PERP quote fix

    Strips trailing _PERP or _NNNNNN dated suffix before quote-suffix
    classification in coinank_rows._classify_quote_kind so BTCUSD_PERP
    resolves to quote_kind=USD and is_perp_inverse=True. Resolves the
    Codex finding in 07_CODEX_REVIEW.md. Re-arms supervisor task 042
    with 21_REMEDIATION_BTCUSD_PERP_QUOTE_FIX.md in its input list.

    No live API calls. No Redis writes or deletes. No exchange-action
    paths. No leverage or margin change. No live-trading enablement.
    v2/legacy_preserved/ingestors/live_coinank.py untouched.
    legacy_reference/** untouched. /home/wali/Desktop/AI BOT untouched.

Then push. Supervisor task 042 re-runs Codex against the fixed module set
and the broader Phase 2D artifact set.

## 7. Safety boundaries

- No live API calls.
- No Redis writes, reads, or deletes.
- No exchange-action paths.
- No leverage or margin change.
- No live-trading enablement.
- `v2/legacy_preserved/ingestors/live_coinank.py` is not touched.
- `legacy_reference/**` is not touched.
- `/home/wali/Desktop/AI BOT/**` is not touched.
- No `.env` file is read or printed.
- No secret value is read or printed.

## 8. Next planner action

After the operator commits and pushes the Pass 21 file set, supervisor
task `042_codex_review_phase2_coinank_discovery_list` re-runs Codex.
Codex re-reads the Phase 2D scope plus this Pass 21 closure, re-runs
`pytest`, and emits `07_CODEX_REVIEW.md` plus `08_CODEX_GO_NO_GO.md`.

If task 042 returns `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`:

- The planner records REQ_0002 as evidence-satisfied via a marker check
  on `08_CODEX_GO_NO_GO.md` containing
  `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS` (added in a follow-up planner
  pass that touches only
  `claude_worklog/tools/claude_master_rebuild_planner.py:evidence_satisfied_requirements`).
- The planner advances to `REQ_0004_TRAINER_GPU_PARITY.md` (the next
  highest-priority requirement; REQ_0003 is already evidence-satisfied
  via `live_coinank.py` copy-as-is, REQ_0005 is sequenced after trainer
  parity in the master plan).

If task 042 returns `PHASE2_COINANK_DISCOVERY_LIST_CODEX_FAIL` with a
finding that touches only artifacts under `claude_worklog/` or `v2/`,
the planner emits a single targeted remediation note and does not advance
to REQ_0004.

Any fail demanding modification of `v2/legacy_preserved/ingestors/live_coinank.py`,
`legacy_reference/**`, secrets, Redis, the exchange path, leverage or
margin, or `/home/wali/Desktop/AI BOT/**` is a hard stop and is escalated
to human review.

PHASE2_COINANK_DISCOVERY_LIST_REMEDIATION_21_READY
