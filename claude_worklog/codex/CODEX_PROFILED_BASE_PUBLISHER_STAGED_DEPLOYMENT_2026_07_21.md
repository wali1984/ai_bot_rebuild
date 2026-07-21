# Profiled Base-Feature Publisher — Staged Deployment Record

Date: 2026-07-21

Operator timezone: America/New_York

Scope: authenticated, point-in-time-safe trainer-input publication only

Runtime/trading authority: **none**

## Executive status

The profiled base-feature publisher is installed and enabled as a user service,
but it is intentionally **inactive**. All three service-specific encrypted
credential source files are absent, so systemd's unit conditions prevent the
process and every `ExecStartPre` command from running. This is a safe staged
state, not a healthy publishing state.

As observed at `2026-07-21T17:45:41-04:00`:

| Property | Observed value | Meaning |
| --- | --- | --- |
| `LoadState` | `loaded` | systemd parsed the unit |
| `UnitFileState` | `enabled` | the unit is selected for a future user-manager start |
| `ActiveState/SubState` | `inactive/dead` | no publisher process is running |
| `ConditionResult` | `no` | at least one required file condition was unmet |
| `ExecMainPID` | `0` | no main process exists |
| `NRestarts` | `0` | there is no crash/restart loop |
| journal entries for this unit | none | the staged service has not executed |

`enabled` must not be interpreted as `online`. The missing encrypted
credentials are the exact remaining activation dependency for this unit.

## Immutable artifact identities

### Code release

| Field | Value |
| --- | --- |
| Git commit | `7c231cc38d287d12a61fa4a4826640824faf022c` |
| Git branch used to build the release | `codex/trainer-release-integration-20260721` |
| Release path | `/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/7c231cc38d287d12a61fa4a4826640824faf022c` |
| Checkout state | detached at the exact commit |
| Tracked-tree verification | `git diff --quiet --exit-code <sha> --` returned `0` |

The service runs the Python module from this checkout, not from the dirty main
working tree. The drop-in also performs the exact Git diff check before each
start.

### Python dependency environment

| Field | Value |
| --- | --- |
| Normalized copy identity | `6360ea33fcfb9f9a81724989bbd32ace2b02bf7eaa7a8771d64d282f423173f0` |
| Environment path | `/home/wali/ai_bot_local_data/deployments/python_envs/6360ea33fcfb9f9a81724989bbd32ace2b02bf7eaa7a8771d64d282f423173f0` |
| Approximate size | `8.2G` |
| Regular-file count | `58,022` |
| Files with link count greater than one | `0` |
| Python | `3.12.3` |

The release checkout's `.venv` symlink resolves to that copied dependency
environment. It is not linked to the mutable repository environment, and no
regular dependency file is hard-linked to another file. Python reports
`sys.prefix` as the release checkout's `.venv`, while resolving its content to
the copied environment.

The normalized copy identity was calculated when the independent environment
was materialized. It identifies that staged copy; it is not a package-lock or
reproducible-build claim.

## Installed unit files

Repository-controlled sources:

- `claude_worklog/systemd/user/ai-bot-v2-profiled-base-feature-publisher.service`
- `claude_worklog/systemd/user/ai-bot-v2-profiled-base-feature-publisher.service.d/90-immutable-release.conf`
- `claude_worklog/systemd/user/ai-bot-v2-profiled-base-feature-publisher.credentials.md`

Installed copies:

- `/home/wali/.config/systemd/user/ai-bot-v2-profiled-base-feature-publisher.service`
- `/home/wali/.config/systemd/user/ai-bot-v2-profiled-base-feature-publisher.service.d/90-immutable-release.conf`

Byte comparison between each repository source and its installed copy returned
success. The release drop-in replaces all mutable code-path settings, clears
and replaces the executable condition, clears and replaces `ExecStart`, and
clears/rebuilds the ordered `ExecStartPre` list.

The effective release controls are:

- documentation reference fixed to the credential contract in the exact
  release checkout;
- working directory and `PYTHONPATH` fixed to the exact release checkout;
- executable fixed to the release checkout's independent environment;
- `AI_BOT_CODE_SHA` fixed to the exact commit;
- code and dependency paths bind-mounted read-only inside the service;
- tracked-tree equality checked before execution;
- no Python bytecode written into the release;
- writes limited by the base unit to the trainer evidence root;
- `LIVE_GATE=blocked_human_only` retained;
- no order, leverage-change, margin-change, transfer, cancel, or other exchange
  mutation endpoint is reachable from this publisher.

## Runtime-namespace proof

A transient user service was run with the same exact code and dependency paths
mounted read-only. It proved:

| Check | Observed result |
| --- | --- |
| imported publisher module | exact file below the release checkout |
| `.venv` resolved path | exact copied dependency environment |
| code mount | `ro,relatime` |
| dependency mount | `ro,relatime` |
| transient process result | success, exit status `0` |

This proves the paths selected inside that mount namespace. It does not protect
against a separate process running as the same host user modifying the physical
files outside the service namespace. Closing that residual threat requires a
root-owned/immutable or filesystem-verified artifact and, for independent
provenance, an external signed witness. Neither authority is claimed here.

## Credential gate

The service accepts exactly these protected credential identities:

| Protected identity | Required encrypted source file | Current state |
| --- | --- | --- |
| `ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_KEY` | `/home/wali/.config/ai-bot-v2/credentials/profiled-base-feature-publisher/api-key.cred` | missing |
| `ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_SECRET` | `/home/wali/.config/ai-bot-v2/credentials/profiled-base-feature-publisher/api-secret.cred` | missing |
| `PROFILED_BASE_COMMISSION_FINGERPRINT_HMAC_SECRET` | `/home/wali/.config/ai-bot-v2/credentials/profiled-base-feature-publisher/fingerprint-hmac.cred` | missing |

The first two must belong to a **distinct Binance USD-M key** for
`trader-wajidali1984`, restricted to account-data/USER_DATA reads, with trading
and withdrawal disabled and IP restriction enabled where Binance permits it.
The third must be an independent random value of at least 32 UTF-8 bytes and
must differ from both exchange values.

The publisher's only authenticated exchange operation is structurally bound to
the signed USD-M `GET /fapi/v1/commissionRate` request. This endpoint is
classified by Binance as `USER_DATA`; it does not require an order mutation.
Local names containing `READONLY` are assertions, not remote proof of the
Binance-side key permissions. Those permissions must be checked by the
operator before activation.

An unprivileged attempt to create an encrypted HMAC source with
`systemd-creds encrypt` failed before output with:

```text
Failed to determine local credential host secret: Permission denied
```

No plaintext fallback was created. Provisioning therefore requires an
operator-controlled privileged terminal or an approved host-credential setup.
Secrets must be supplied via standard input or another protected local source,
never as shell arguments, repository text, unit environment values, or journal
content. Each encryption operation must use the exact protected identity in
`--name=` so systemd validates the embedded credential name.

The previously inspected generic Binance credential is not eligible for this
service: its remote capabilities include trading, deposit, and withdrawal.
It must not be copied, renamed, or repurposed as the read-only publisher key.

## Evidence that predates service staging

The publisher evidence directory is not empty. It contains status/state and CAS
artifacts from a bounded manual validation cycle completed at
`2026-07-21T09:43:51.337343Z`:

- 161 symbols discovered;
- one symbol selected and published;
- zero symbol failures;
- no legacy Redis feature write;
- no market-performance threshold applied;
- every training, prediction, paper, and live authority bit false.

These files predate the staged service activation attempt. They prove a prior
manual capture path ran; they do **not** prove that the installed service is
online or that the trainer currently has sufficient admitted examples.

## Test evidence

The two publisher-specific suites are executed from the frozen code release and
independent dependency copy inside a transient read-only service namespace:

```text
v2/backend/tests/unit/services/native_trainer/test_profiled_base_publisher_runtime_credentials.py
v2/backend/tests/unit/services/native_trainer/test_profiled_base_feature_publisher_v1.py
```

Final result: **79 passed in 368.72 seconds**. The transient service completed
successfully with exit status `0`.

The first transient harness attempt exited before test collection because the
ad-hoc `ProtectSystem=strict` probe did not expose a writable temporary
directory. No publisher code or assertion failed. The corrected harness adds a
private writable `/tmp`, matching the base service's `PrivateTmp=true`, while
leaving both release inputs read-only.

`systemd-analyze --user verify` reports no error in this unit or its drop-in.
It also prints warnings from several unrelated pre-existing user units; those
warnings are outside this deployment slice and are not suppressed here.
`systemd-analyze --user security` reports exposure level `3.7 (OK)` for the
staged unit. That heuristic score is supporting information, not an authority
grant.

## Activation decision

Activation is permitted only after all of the following are true:

1. A distinct Binance USD-M account-data key exists for the fixed trader.
2. Binance-side permissions are independently inspected: no trade, transfer,
   deposit, or withdrawal capability.
3. The key is IP-restricted where supported.
4. All three encrypted source files exist with restrictive ownership/modes and
   exact embedded credential identities.
5. The final frozen-release publisher tests pass.
6. `systemd-analyze verify` still reports no scoped unit error.
7. The immutable code and dependency paths still match their recorded
   identities.

After those gates, the safe activation sequence is to start **only this
publisher**, observe multiple cycles, and verify ledger/CAS/status coherence
before releasing any trainer consumer. Starting this unit does not authorize
the continuous trainer, optimizer, checkpoint writer, predictor, allocator,
paper loop, or live execution.

## Post-start evidence required before consumer release

For multiple consecutive cycles, record and reconcile:

- main PID, `NRestarts`, exit status, and journal classification;
- discovery, selected, published, unchanged, deferred, and failed counts;
- exact `event_time`, `ingested_at`, `available_at`, `generated_at`,
  `feature_cutoff`, and prospective `decision_time` ordering;
- closed-candle finality for every required timeframe;
- source receipt bytes and hashes against CAS objects;
- account-specific commission observation time and credential fingerprint;
- append-only ledger sequence, previous-record hash, and local seal validity;
- loader rejection counts and exact reason codes;
- disk-resource horizon and evidence-accounting totals;
- confirmation that no legacy Redis feature write or downstream authority
  transition occurred.

Only loader-admitted, causally ordered, fully closed, byte-replayable children
may become trainer examples. Missing optional providers remain explicitly
masked; missing required price/clock/lineage/cost evidence remains rejected.

## Honest residual blockers

- The publisher cannot run until the three service-specific encrypted
  credentials are provisioned.
- A running publisher alone does not create sufficient sample diversity or an
  independently validated model.
- The local seal proves local integrity, not an independent external witness.
- The same-host-user artifact mutation threat is reduced by the read-only
  service namespace but not eliminated outside that namespace.
- No return multiple, positive expectancy, leverage level, or 90-day outcome is
  implied by staging or activating this service.

This slice advances the 1000x research objective by restoring trustworthy data
acquisition capacity. It does not lower causal, cost, risk, or execution safety
requirements in order to manufacture throughput or grades.
