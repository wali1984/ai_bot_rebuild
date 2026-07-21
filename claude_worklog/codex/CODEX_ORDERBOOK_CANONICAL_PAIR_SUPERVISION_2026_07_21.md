# Exact direct-orderbook pair supervision — 2026-07-21

## Decision

**Code-integration candidate: GO for independent re-review.**

**Runtime deployment: NO-GO.**  The exact code artifact and repository service
drop-in are staged, but the dedicated Redis ACL credential does not exist and
the operator has not authorized installation or restart.  This slice grants
no trainer, paper, model, leverage, margin, order, or live-execution authority.

The currently running service is the older mutable process started on
2026-07-17.  It was not stopped, restarted, reloaded, or modified by this
slice.  The staged implementation must not be confused with that process.

## Correct ownership and atomicity model

The direct recorder is the only authorized writer of these per-symbol keys:

- `v2:orderbook:depth:binance:{symbol}` using
  `direct_orderbook_depth_v1`;
- `v2:orderbook:features:binance:{symbol}` using
  `direct_orderbook_features_v1`.

The recorder currently performs separate Redis `SET` operations for depth and
features.  The producer write is therefore **not atomic as a pair**.  The
supervisor does not claim otherwise and does not repair either half.  It uses
one Redis Lua execution to return Redis `TIME`, exact depth bytes, exact
feature bytes, and both `PTTL` values without another Redis command
interleaving that observation.  A read landing between producer writes is
fail-closed by exact sequence, source, clock, and semantic pair checks.

The supervisor has one write boundary only:
`v2:orderbook:features:summary`.  Static AST regression coverage rejects
write-method aliases and requires the sole `SET` call's key argument to be the
literal `SUMMARY_KEY` name.  The component registry now describes this as a
summary-only validator, not as a feature derivation publisher.

## Exact-byte and semantic contract

Each atomic observation records, without republishing source data:

- exact byte length and SHA-256 for both values;
- Redis server observation time;
- both exact `PTTL` values;
- source keys and presence flags;
- source sequence ID, validation result, and adaptive-freshness evidence;
- the SHA-256 of the exact read-only Lua program.

Strict JSON parsing rejects invalid UTF-8, duplicate keys at any nesting
level, non-standard `NaN`/`Infinity` constants, numeric overflow to infinity,
non-object roots, empty/oversize records, and non-binary Redis values.  The
2-MiB byte ceiling is an immutable memory/decoder resource limit, not a market
threshold.

The semantic validator requires exact schemas, `direct_binance`, `binance`,
the requested canonical symbol, positive exact-integer current and previous
sequence IDs, no sequence gap, and matching identity/sequence/clock fields.
Only the Binance direct-WebSocket `partial_depth` protocol is accepted.  The
allowed depth levels (`5`, `10`, `20`) and announced transports (`100 ms`,
`250 ms`) are Binance protocol enumerations; REST snapshots are rejected.

Depth must be a non-empty JSON list whose entries contain exactly `price` and
`quantity`; both must be positive and finite.  Bids must be strictly
descending, asks strictly ascending, and the best ask must exceed the best
bid.  Declared level counts must match the exact arrays.

The supervisor independently recomputes and compares every producer economic
claim used by this schema:

- top bid/ask, sizes, midpoint, and spread;
- source latency and update age from the named clocks;
- USD depth at 5/20/50/500 levels on both sides;
- quantity imbalance and depth slope;
- reference-notional visible-book price impact;
- minimum-side liquidity, 20-level total depth, and microstructure depth.

This is integrity supervision only.  It is not a CAS retention receipt and
cannot substitute for the trainer's authenticated cost-evidence boundary.

## Adaptive freshness contract

The former fixed 900-second market-age admission threshold and its CLI option
were removed.  Freshness is now derived from evidence observed by this
process:

1. On the first valid observation, status is
   `COLD_START_NO_OBSERVED_CADENCE` / `UNKNOWN`; it is not healthy.
2. A later sequence must increase and its `available_at` must postdate the
   previous Redis server observation.  This prevents replayed old records from
   seeding a permissive cadence.
3. Recent exact availability intervals form a bounded process-local evidence
   window.  The bound of 32 entries limits memory only.
4. The freshness budget is the lesser of the maximum recently observed source
   interval and the currently evidenced producer-expiry horizon.  No fixed
   seconds value or market multiplier participates.
5. Missing/non-expiring keys, sequence regression, content mutation under one
   sequence, non-advancing availability, invalid expiry, or observed age beyond
   that learned budget is held.

The two key expiries may differ only within the exact announced WebSocket
cadence.  That is a pair-write coherence check tied to the transport protocol,
not a market-freshness threshold.  Summary TTL and loop interval remain
operational storage/scheduling values and grant no data authority.

Process-local cadence is deliberate.  A restart cannot restore trust from the
worker's own prior summary; it must observe a new causal source transition.

## Read-only runtime evidence

A read-only inventory used `SCAN` plus the read-only Lua boundary; it executed
no `SET` or other Redis mutation:

- exact Binance depth keys observed: 157;
- strict schema/identity/clock/sequence/depth/economic pairs valid: 157/157;
- rejection reasons: none;
- minimum remaining pair TTL during the inventory: 27,369 ms;
- maximum depth/features TTL skew: 1 ms.

A separate two-observation BTCUSDT probe produced:

- observation 1: `UNKNOWN`, age 65 ms, evidenced expiry horizon 30,002 ms;
- observation 2: `HEALTHY`, new sequence, observed interval 508 ms,
  age 158 ms, adaptive budget 508 ms.

These values are point observations, not market constants and not trainer
admission evidence.

## Immutable staging identity

- pushed code commit:
  `5c625692472496c7ddca89782f38445ea6412420`;
- detached clean code artifact:
  `/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/5c625692472496c7ddca89782f38445ea6412420`;
- frozen Python dependency tree:
  `/home/wali/ai_bot_local_data/deployments/python_envs/6360ea33fcfb9f9a81724989bbd32ace2b02bf7eaa7a8771d64d282f423173f0`;
- dependency normalized-content identity:
  `6360ea33fcfb9f9a81724989bbd32ace2b02bf7eaa7a8771d64d282f423173f0`;
- repository drop-in:
  `claude_worklog/systemd/user/ai-bot-v2-orderbook-features-publisher.service.d/90-immutable-release.conf`.

The drop-in resets mutable working-directory/environment/command entries,
pins both exact paths read-only in the service mount namespace, checks a clean
detached worktree whose HEAD equals the pushed SHA in both ancestry
directions, and runs the frozen interpreter directly.  Namespace read-only
mounting does not make the host path tamper-proof against the same host user;
that residual limitation is explicit.

## Dedicated Redis ACL operator gate

The staged service requires the absent encrypted credential:

`~/.config/ai-bot-v2/credentials/orderbook-pair-supervisor/redis-url.cred`

Its systemd credential name is
`V2_ORDERBOOK_SUPERVISOR_REDIS_URL`.  Code does not fall back to `REDIS_URL`,
`V2_REDIS_URL`, or unauthenticated localhost.  The operator-provisioned Redis
user must be limited to:

- read access to `v2:orderbook:depth:binance:*` and
  `v2:orderbook:features:binance:*`;
- write access only to `v2:orderbook:features:summary`;
- only `PING`, `EVAL`, `TIME`, `MGET`, `PTTL`, and `SET` command families
  needed by this exact implementation.

Redis 7 read/write key-pattern selectors should be used so granting `SET`
does not grant writes to per-symbol feature keys.  Credential creation, ACL
mutation, unit installation, daemon reload, and cutover remain operator work;
none occurred here.

## Validation

The source worktree and the frozen, read-only transient namespace both passed
the combined supervisor/direct-recorder/causal-cost/component-registry suites:

- 123 tests passed;
- Python compilation passed;
- Ruff fatal selectors `E9,F63,F7,F82` passed;
- `git diff --check` passed;
- repository unit/drop-in verification had no error scoped to this service;
- transient `findmnt` showed both code and dependency roots `ro,relatime`.

The adversarial suite covers duplicate/nonfinite JSON, numeric overflow,
malformed truthy books, missing/bool sequence IDs, REST substitution, forged
top/depth/imbalance/slope/impact fields, wrong ordering, crossed books, a
one-day-old pair with freshly reset TTL, replayed availability, invalid/skewed
expiry, client-side torn-read traps, nonfinite/bool/zero/negative config, and
Redis-write AST aliases.

## Remaining deploy gates

1. Independent re-review of this follow-up commit and the staged artifact.
2. Operator provisions and verifies the dedicated least-privilege Redis ACL
   and encrypted credential without exposing it in the repository or logs.
3. Operator authorizes replacement of the old mutable service.
4. Install the tracked base unit and exact drop-in, reload, then verify the
   merged unit before start.
5. After start, observe cold-start UNKNOWN followed by causally earned health,
   verify zero per-symbol writes, and confirm the direct recorder remains the
   sole owner.

Until all five complete, deployment remains **NO-GO**.
