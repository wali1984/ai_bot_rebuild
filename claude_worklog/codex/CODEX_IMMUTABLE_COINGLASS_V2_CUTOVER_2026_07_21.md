# Codex immutable CoinGlass V2 producer cutover — 2026-07-21

## Result

Deployment verdict: **GO for the scoped read-only CoinGlass producer**.

The active service now runs the exact pushed Git object:

- branch at release creation: `codex/pipeline-trust-refresh`
- release commit: `99b3f306811d8bd4f187a033c3101740a1ee644b`
- immutable worktree:
  `/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/99b3f306811d8bd4f187a033c3101740a1ee644b`
- unit: `ai-bot-v2-coinglass-provider-loop.service`
- post-cutover PID: `2450504`
- start: `2026-07-21 15:24:07 EDT`
- state: `active/running`
- `NRestarts=0`

This cutover did not submit, cancel, test, or modify an exchange order. It did
not change exchange leverage, margin mode, balances, positions, or the live
gate. CoinGlass is a read-only external market-data source and writes only the
existing V2 provider/feature Redis namespace.

## Why the cutover was necessary

The resident producer was healthy as a process but still emitted
`coinglass_aggregated_feature_payload_v1`. Its aggregate rows omitted the exact
timeframe identity and `temporal_contract_valid`, and percentage-like fields
used mixed units. The repaired consumers therefore correctly rejected every
row, leaving confluence with zero providers despite successful HTTP results.

The V2 producer release now enforces:

1. exact provider, symbol, and timeframe identity;
2. closed higher-timeframe interval evidence before admission;
3. distinct `feature_cutoff`, `available_at`, `ingested_at`, and
   `generated_at` clocks;
4. `feature_cutoff <= available_at <= decision_time` at consumption;
5. finite numeric values and explicit missing/stale masks;
6. percentage-to-fraction normalization for funding, long/short ratios,
   open-interest change, and 24-hour price change;
7. observation deduplication without moving the original evidence clocks;
8. expiry derived from source finality/freshness rather than key existence;
9. `decision_time_safe=true` and `temporal_contract_valid=true` only when the
   aggregate is causally consumable.

## Immutable service boundary

Installed reversible external drop-in:

`/home/wali/.config/systemd/user/ai-bot-v2-coinglass-provider-loop.service.d/90-immutable-release.conf`

It binds:

- `WorkingDirectory` and both Python import roots to the exact release;
- `AI_BOT_CODE_SHA` to the exact release SHA;
- `ExecStartPre` to a tracked-byte Git integrity check;
- `ReadOnlyPaths` to the release root;
- bytecode output to a release-specific runtime cache;
- `LIVE_GATE=blocked_human_only` from the base unit;
- a provider-only systemd credential named `coinglass-api-key`.

Runtime inspection confirmed the process CWD and `PYTHONPATH` resolve to the
release and the release mount is read-only in the service namespace.

## Credential handling

The old process loaded the CoinGlass key from a multi-purpose local dotenv
file. An immutable worktree intentionally contains no ignored credential file,
so the cutover created a provider-only local credential file at:

`/home/wali/.config/ai-bot-v2/credentials/coinglass-api-key.cred`

The directory is mode `0700`, the file is mode `0600`, and the systemd unit
uses `LoadCredential` so the service receives a private runtime copy. The key
value was never printed, logged, committed, or placed in the unit file or
command line. The service shell reads it into the process environment and
immediately `exec`s Python.

`systemd-creds encrypt` was attempted first but failed because the user cannot
read the host credential secret. The current `0600` source file is therefore a
known local-at-rest limitation, not an encrypted credential. A future operator
security change can replace `LoadCredential` with `LoadCredentialEncrypted`
without changing provider logic once host-key access is available.

## Test and runtime evidence

Exact-release tests:

- CoinGlass normalizer, publisher/registry, and semantic-contract suite:
  `21 passed`;
- release tracked diff: clean;
- release untracked inventory: empty.

Fresh Redis evidence after restart:

| Symbol | Schema | Identity | PIT flags | Representative normalized fields |
|---|---|---|---|---|
| BTCUSDT | `coinglass_aggregated_feature_payload_v2` | `BTCUSDT:1m` | provider ready, decision-time safe, temporal contract valid | funding `0.00002164`, long `0.5244`, short `0.4756`, OI 5m change `-0.0003` |
| ETHUSDT | `coinglass_aggregated_feature_payload_v2` | `ETHUSDT:1m` | provider ready, decision-time safe, temporal contract valid | funding `0.00008055`, long `0.574`, short `0.426`, OI 5m change `0.0003` |
| SOLUSDT | `coinglass_aggregated_feature_payload_v2` | `SOLUSDT:1m` | provider ready, decision-time safe, temporal contract valid | funding `0.00004852`, long `0.7166`, short `0.2834`, OI 5m change `0.0005` |

All three rows had empty missing/stale masks in the sampled cycle. The active
confluence publisher then consumed the repaired CoinGlass row on its next
cycle and emitted `actual_payload_present=true`,
`decision_time_safe=true`, `providers_present=["coinglass"]`, and causal
feature cutoffs for BTC, ETH, and SOL. Moralis and CoinAnk remained honestly
missing rather than zero-filled.

This proves the producer-to-confluence data seam. It does not yet authorize
the held strategy-supply, cascade, or microstructure consumers; those require
their own immutable release checks. It also does not grant trainer authority:
the separately repaired baseline trainer masks unauthenticated provider slots,
and the authenticated profiled trainer path remains witness/cost-evidence
gated.

## Commands executed

The commands below are recorded without any credential value:

```text
git worktree add --detach <release-path> 99b3f306811d8bd4f187a033c3101740a1ee644b
git -C <release-path> diff --quiet --exit-code 99b3f306811d8bd4f187a033c3101740a1ee644b --
git -C <release-path> status --porcelain=v1 --untracked-files=all
PYTHONPATH=<release>:<release>/v2/backend <shared-venv-python> -m pytest -q <three CoinGlass test modules>
rg --files v2/backend/tests | rg 'coinglass.*(contract|publisher|normalizer)'
systemd-creds --version
systemd-creds encrypt --name=coinglass-api-key - <encrypted-credential-path>
install -d -m 700 /home/wali/.config/ai-bot-v2/credentials
<redacted-value extractor> <v2/.env.local> | install -m 600 /dev/stdin <provider-only-credential-path>
install -d -m 700 <coinglass-unit-drop-in-directory>
systemd-analyze --user verify ai-bot-v2-coinglass-provider-loop.service
systemctl --user daemon-reload
systemctl --user restart ai-bot-v2-coinglass-provider-loop.service
systemctl --user show ai-bot-v2-coinglass-provider-loop.service <scoped properties>
readlink -f /proc/<pid>/cwd
<name-only process-environment inspection>
rg -F <release-path> /proc/<pid>/mountinfo
redis-cli GET <scoped CoinGlass feature/status keys> | jq <non-secret contract fields>
redis-cli GET <scoped confluence keys> | jq <non-secret contract fields>
tail <CoinGlass stdout/stderr files>
```

The failed encrypted-credential attempt created no credential artifact. The
unrelated `systemd-analyze` warning concerned the pre-existing report-center
indexer unit, not the CoinGlass service.
