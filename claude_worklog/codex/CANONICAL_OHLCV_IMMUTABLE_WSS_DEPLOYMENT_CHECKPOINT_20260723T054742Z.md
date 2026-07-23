# Canonical OHLCV Immutable WSS Deployment Checkpoint — 2026-07-23T05:47:42Z

## Immutable checkpoint

- Branch: `codex/strategy-receipt-promotion-20260723`
- Deployed release commit: `82c7fbfb4441e4357b8adc17e0018a0d4c023d55`
- Writer-receipt source commit: `c1134da0a6188238a473f8ffc2ca146833a09d06`
- Healthy-window adoption source commit:
  `a7d07f32a1e332d0a0480a38b3609529bf294ea4`
- Immutable release root:
  `/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/82c7fbfb4441e4357b8adc17e0018a0d4c023d55`
- Shared Python environment:
  `/home/wali/ai_bot_local_data/deployments/python_envs/6360ea33fcfb9f9a81724989bbd32ace2b02bf7eaa7a8771d64d282f423173f0`
- Deployment family defects: **0**
- Remaining adjacent writer blocker: **1** — the periodic coverage-sync
  fallback still needs its own immutable release binding before a gap or new
  universe member is allowed to use that legacy process image.

## Deployment binding

The WSS service now imports and executes the exact detached release above.
Repository source files are read-only; tracked executable files retain their
executable bit; the release Git tree is clean. Python starts with `-P -B`, an
explicit immutable `PYTHONPATH`, a release-scoped pycache outside the release,
and `AI_BOT_CODE_SHA` equal to the deployed commit.

The systemd override is external deployment state at:

`/home/wali/.config/systemd/user/ai-bot-v2-binance-kline-wss-loop.service.d/90-immutable-release.conf`

Its SHA-256 is
`790cbe621ddd0977242a77f0bcd4942d330cb5dc16dc5f3b3a53debecc43b9ac`.
The loaded WSS module SHA-256 is
`26f7fb88c6909a88bb7a700cd85277d1fe300ff2ee779ad0607e617360497cb2`.
All mutable database, status, public-payload, and worklog targets are explicit
absolute paths outside the immutable release.

## Runtime evidence

At the final sample the service was active/running with PID `825698`, start
time `2026-07-23 01:42:16 EDT`, and `NRestarts=0`. Its operator payload showed:

- WebSocket connections: **7/7 connected**
- Adaptive universe: **159 symbols**
- Configured timeframes: **5** (`1m`, `5m`, `15m`, `1h`, `4h`)
- Streams: **795**
- Messages after restart: **48,023**
- Authenticated atomic canonical writes after restart: **318**
- Write / parse / connection / Redis-reconnect errors: **0 / 0 / 0 / 0**
- Blocked canonical keys: **0**
- Adoption attempts / adopted / failed / pending: **795 / 795 / 0 / 0**
- Adoption REST/HTTP requests / Redis scans: **0 / 0**
- Durable 5m label rows pending / volatile rows at risk: **0 / 0**
- Label-pipeline runtime errors: **0**

A separate read-only verifier reopened every current
pointer/canonical/archive/receipt tuple and independently re-derived the
payload schema, exact bytes/hash/count, revision ID, key bindings, receipt
hash, source/finality clocks, authority fields, and TTL ordering:

- Current pointer keys discovered: **795**
- Current tuples verified: **795/795**
- Verification defects: **0**
- Verified per timeframe: **159/159 for all 5 timeframes**
- Genuine WSS producer receipts: **477**
- Explicit adoption-only receipts: **318**
- Distinct loaded producer-code hashes: **1**
- Loaded producer-code hash matches deployed WSS module: **yes**

The role split is expected and changes only when a timeframe closes. At this
sample, the `1m`, `5m`, and `15m` windows had been replaced by genuine WSS
publications; the not-yet-closed `1h` and `4h` windows retained the separate
adoption-only role. No downstream consumer may treat that adoption role as
proof of the legacy payload's original Binance producer authenticity.

The dynamic proof-key inventory sample contained **795 current pointers**,
**1,431 revision receipts**, and **1,590 revision archives**. Superseded proofs
overlap only for their cadence-derived TTL. Redis memory was **15.59 GiB used /
32.00 GiB max** at exact reopen, versus approximately **15.43 GiB** before the
rollout; this is consistent with the previously measured cadence-bounded
projection and remains a runtime watch item rather than an unbounded-retention
design.

## Execution-safety evidence

Exactly **13/13** exposed execution-authority fields remained false or empty:

1. `approves_canary=false`
2. `approves_live=false`
3. `calls_binance_rest=false`
4. `calls_rest_api=false`
5. `calls_test_order_endpoint=false`
6. `execution_live_symbols=[]`
7. `leverage_changed=false`
8. `live_symbols=[]`
9. `margin_mode_changed=false`
10. `places_exchange_orders=false`
11. `writes_exchange_orders=false`
12. `writes_legacy_redis=false`
13. `writes_old_redis=false`

`LIVE_GATE` remains `blocked_human_only`. This deployment consumed public
market data and wrote only V2 canonical/provenance and configured local
operator/label artifacts. It did not call an order endpoint or mutate exchange
orders, leverage, margin mode, or live-symbol authority.

## Evidence counts

- Source files changed by deployment: **0**
- External systemd override files created: **1**
- Immutable releases created: **1**
- Services changed/restarted: **1/1**
- Service restarts after activation: **0**
- Systemd unit verifications: **1/1 passed**
- Immutable import/code-path checks: **1/1 passed**
- Release Git-tree integrity checks: **1/1 passed**
- Current receipt tuples checked: **795**
- Receipt fields re-derived per tuple: **all 39 required fields**
- Runtime safety fields checked: **13/13**
- Runtime screenshots captured: **0**
- Routes inspected / endpoints compared / product builds passed: **0 / 0 / 0**
- Exchange calls / orders / leverage changes / margin changes: **0 / 0 / 0 / 0**
- Deployment family defects: **0**
- Adjacent writer defects remaining: **1**

The source and adoption families were already verified at **160/160** and
**242/242** affected tests respectively. Those proven suites were not rerun
during this deployment checkpoint.

## Deployment artifacts

1. External systemd override:
   `/home/wali/.config/systemd/user/ai-bot-v2-binance-kline-wss-loop.service.d/90-immutable-release.conf`
2. Immutable detached release:
   `/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/82c7fbfb4441e4357b8adc17e0018a0d4c023d55`
3. This committed checkpoint document.

## Commands executed for deployment and verification

```text
git worktree add --detach <immutable-release-root> 82c7fbfb4441e4357b8adc17e0018a0d4c023d55
ln -s <shared-python-environment> <immutable-release-root>/.venv
find/chmod release directories and files to 0555/0444, restoring tracked executable files to 0555
systemd-analyze --user verify ai-bot-v2-binance-kline-wss-loop.service
systemctl --user daemon-reload
systemctl --user restart ai-bot-v2-binance-kline-wss-loop.service
systemctl --user show ai-bot-v2-binance-kline-wss-loop.service <selected properties>
systemctl --user cat ai-bot-v2-binance-kline-wss-loop.service
jq <selected status/adoption/label/safety fields> v2_binance_kline_wss_status.json
tail/wc -l v2_binance_kline_wss_loop.log and v2_binance_kline_wss_loop.err
redis-cli INFO memory
redis-cli --scan <three exact publication-proof patterns>
sha256sum <systemd override> <deployed WSS module>
git -C <immutable-release-root> status --short
git -C <immutable-release-root> rev-parse HEAD
env PYTHONPATH=<immutable-release-root> <release-python> -P -B - <read-only 795-tuple verifier>
```

The first manual verifier invocation omitted the explicit `PYTHONPATH` while
using `-P` and therefore stopped before Redis access with
`ModuleNotFoundError: v2.backend`. The corrected invocation used the same
explicit immutable `PYTHONPATH` as systemd and verified **795/795** tuples. No
runtime mutation occurred in either invocation.

## Next gate

Bind coverage-sync to an immutable release with an external status target,
then implement the strategy input consumer's independent exact-read receipt
and strict genuine-writer allow-list. Keep strategy publication and all paper
or live admission held until that contract and its deterministic transform
manifest are complete.
