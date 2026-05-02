# Phase 2D CoinAnk Discovery List - Codex Review

Decision: FAIL

## Finding

1. `BTCUSD_PERP` is not classified as inverse USD perpetual, and the required fixture-only test suite fails.

Evidence:
- `v2/backend/app/domain/symbols/coinank_rows.py:57` through `v2/backend/app/domain/symbols/coinank_rows.py:73` infers quote kind using raw suffix checks like `endswith("USD")`.
- `v2/backend/app/domain/symbols/coinank_rows.py:87` through `v2/backend/app/domain/symbols/coinank_rows.py:89` then requires `quote_kind == "USD"` for `is_perp_inverse`.
- For `BTCUSD_PERP`, the raw symbol ends with `_PERP`, not `USD`, so `quote_kind` becomes `OTHER` and `is_perp_inverse` becomes `False`.
- The required synthetic test `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py:57` through `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py:63` asserts the inverse flag and fails.

Verification command:

```bash
PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py
```

Observed result:

```text
1 failed, 10 passed
FAILED test_coinank_btcusd_perp_marked_inverse_and_does_not_collapse_with_usdm
assert False is True
```

Impact:
- Requirement 6 is not fully satisfied for `BTCUSD_PERP`.
- The Phase 2D go/no-go cannot pass because required verification item 14 requires this exact test suite to run successfully against the synthetic fixture.

## Passed Checks

- Raw rows are preserved under `metadata["coinank_raw"]` with `symbol`, `baseCoin`, `exchangeName`, `expireAt`, and `updateAt`.
- Chinese-name rows preserve decoded UTF-8 raw values and are marked `requires_confirmation`.
- Stock-like rows are blocked from USD-M confirmation by `candidate_for_usdm_confirmation=False`.
- `ETHBTC` is not a USD-M confirmation candidate.
- `BTCUSDT` confirmation requires a matching Binance USD-M identity with trading status.
- USDC and USDT symbols remain distinct.
- Tests use JSON fixtures and in-memory adapter payloads only; no live CoinAnk API path is present in the reviewed test/module set.
- No Redis write/delete path was found in the reviewed module set.
- No secrets were found in the reviewed module/fixture/task set; prompt literals containing the word `token` are not credentials.
- `git status --short -- v2/legacy_preserved/ingestors/live_coinank.py legacy_reference` returned no modifications.
- `python3 -m py_compile` succeeded for the four reviewed Python files. The documented trailing `
- `python3 -m json.tool` succeeded for `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json` and `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`. The task JSON contains literal prompt text naming `BEGIN_FILE`/`END_FILE`, but no appended leaked planner sentinel.

## Commands Run

```bash
python3 -m py_compile \
  v2/backend/app/domain/symbols/coinank_rows.py \
  v2/backend/app/domain/symbols/normalization.py \
  v2/backend/app/adapters/symbol_sources/coinank.py \
  v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py
```

```bash
python3 -m json.tool < claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json > /dev/null
python3 -m json.tool < v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json > /dev/null
```

```bash
PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py
```

PHASE2_COINANK_DISCOVERY_LIST_CODEX_REVIEW_COMPLETE
