# Paper → Trainer Control Checkpoint — 2026-07-23T05:00:46Z

## Immutable checkpoint

- Branch: `codex/paper-admission-remediation-20260721`
- Source commit: `6f5dd649b1a962c2f16b08b3beb7caa3bb375ba0`
- Source was pushed with divergence `0 ahead / 0 behind` before this document.
- Immutable release: `/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/6f5dd649b1a962c2f16b08b3beb7caa3bb375ba0`
- Release integrity: tracked diff clean; root mode `0555`; tracked source mode `0444`.
- Unit: `ai-bot-v2-trade-management-paper-loop.service`
- Replacement PID: `759182`; start: `2026-07-23T04:55:25Z`; `NRestarts=0`.

## Exact defect and repair

The commissioned publisher reads `v2:paper:adaptive_sizing_runtime_status` and
`v2:paper:account_margin_status` in one atomic snapshot. Its cold-start policy
correctly requires one exact generation clock and one identity formatted as
`paper_cycle:<64 lowercase hex>`. The paper loop omitted that identity and
published the keys separately, so the consumer failed closed with
`COLD_START_NOTIONAL_PRODUCER_CYCLE_ID_INVALID`.

The repair adds one deterministic cycle identity, stamps both payloads with
one clock, and writes both keys in one `MULTI/EXEC` transaction with equal
TTLs. It rejects mismatched clocks/IDs and prevents a malformed nonempty row
collection from masquerading as a valid zero-candidate cycle. It changes no
risk threshold, leverage decision, margin-mode decision, order path, live
route, fallback notional, or static notional.

## Evidence counts

- Production/test/documentation files: **1 / 1 / 1**
- Redis controls repaired: **2 keys in 1 transaction**
- New regression tests: **3**
- Focused cases: **6/6 passed**
- Full paper-loop regression: **590/590 passed**
- Cross-release producer→commissioned-consumer probes: **1/1 passed**
- Compile targets: **2/2 passed**
- Fatal Ruff checks: **2/2 files passed**
- Diff whitespace errors: **0**
- Fresh paper control cycles: **3/3 matching IDs, clocks, and positive TTLs**
- Margin results: **3/3 PASS**
- Trainer publisher after repair: **1 selected / 1 published / 0 failed**
- Durable feature rows: **2 inserted / 0 duplicate**
- Publisher failure reasons after repair: **0**
- Live-safety fields checked pre/post: **13 + 13**
- Services restarted: **1** (paper loop only)
- Direct Redis writes, screenshots, product routes/builds: **0 / 0 / 0**
- Exchange calls, orders, test orders, leverage or margin mutations: **0**
- Immediate publisher-boundary defects remaining: **0**

## Runtime proof

| Shared clock | Shared cycle suffix | Candidates | Margin | TTLs | Mutations |
|---|---|---:|---|---|---|
| `04:55:26.467Z` | `d807a249…dcafe94` | 0 | PASS | equal, positive | false |
| `04:56:44.914Z` | `cdaf4809…e6ca24` | 0 | PASS | equal, positive | false |
| `04:59:28.947Z` | `fdefe416…8588e9` | 0 | PASS | equal, positive | false |

The next scheduled publisher cycle ran without a restart from
`04:58:03.111012Z` to `04:59:06.279376Z` (63.168 seconds). It selected and
published `ASTERUSDT`, reported
`CYCLE_COMPLETE_ALL_SELECTED_AUTHENTICATED_OR_UNCHANGED`, and had zero
failures. Expected notional was `$2476.55059808`, derived by the adaptive
symmetric visible-depth cold-start policy from the atomic paper controls and
current market sources. Commission evidence was READY/authenticated. The
feature append committed and read back parent sequence 85 and child sequence
86. Legacy feature Redis write was false.

The verified clock order was:

`event_time 04:54:59.999Z <= ingested_at/available_at 04:55:02.028Z <= transform_available_at 04:58:14.135184Z <= feature_cutoff 04:58:49.179Z <= cost_artifact_available_at 04:58:49.606657Z <= decision_time 04:59:04.112030Z`.

`execution_time` was absent. Publisher runtime, prediction, paper, and live
authority all remained false. Child trainer-input eligibility is not serving
or trading authority.

The canonical live gate remained `blocked_human_only`; both live symbol lists
were empty; all order/test-order/leverage/margin/live-route flags were false.

## Remaining bounded work

1. The persistent local research trainer is active with `NRestarts=0` and was
   already inside a long cycle when sequence 86 arrived. Its next completion
   must prove consumption; restarting a progressing trainer is unwarranted.
2. Candidate count remains truthfully zero while strategy supply is held for
   the canonical OHLCV receipt chain. Do not manufacture supply or relax gates.
3. UI/iOS, hardware tuning, Moralis, CoinAPI-optional, CoinAnk, and liquidation
   levels were not re-audited in this narrow repair.

## Files changed

- `v2/backend/app/cli/v2_trade_management_paper_loop.py`
- `v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py`
- `claude_worklog/codex/PAPER_TRAINER_CONTROL_CHECKPOINT_20260723T050046Z.md`

Outside Git, the immutable-release paths in
`/home/wali/.config/systemd/user/ai-bot-v2-trade-management-paper-loop.service.d/90-immutable-release.conf`
were advanced from `9ef0e6e…` to `6f5dd649…`.

## Commands run

- `/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py -k 'paper_adaptive_sizing or paper_cycle_control_bundle or account_margin_status'`
- `/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py`
- `/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m py_compile v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py`
- `/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m ruff check --select E9,F63,F7,F82 v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py`
- `git diff --check`
- `git add v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py`
- `git commit -m 'fix(paper): restore atomic trainer cycle controls'`
- `git push`
- `git worktree add --detach /home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/6f5dd649b1a962c2f16b08b3beb7caa3bb375ba0 6f5dd649b1a962c2f16b08b3beb7caa3bb375ba0`
- `ln -s <shared-python-env> <immutable-release>/.venv`
- `chmod -R a-w <immutable-release>`
- `git -C <immutable-release> diff --quiet --exit-code 6f5dd649b1a962c2f16b08b3beb7caa3bb375ba0 --`
- `systemd-analyze --user verify ai-bot-v2-trade-management-paper-loop.service`
- `systemctl --user daemon-reload`
- `systemctl --user restart ai-bot-v2-trade-management-paper-loop.service`
- `systemctl --user show ai-bot-v2-trade-management-paper-loop.service -p ActiveState -p SubState -p MainPID -p NRestarts -p ExecStart -p Environment`
- `curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8000/api/v2/live-gate/status`

The cross-release acceptance probe was read-only with respect to Redis and
services; it used an ephemeral temporary CAS directory and the exact
commissioned `974caa6…` cold-start consumer.
