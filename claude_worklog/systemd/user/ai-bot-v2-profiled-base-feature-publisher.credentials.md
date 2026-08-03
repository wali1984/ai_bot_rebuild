# Profiled base-feature publisher credential contract

This is a deployment contract, not an activation instruction. Installing,
enabling, or starting the unit remains an explicit operator action.

The service accepts exactly three encrypted systemd credentials. It does not
load a repository `.env`, a service `EnvironmentFile`, generic `BINANCE_*`
variables, or secrets from command-line arguments.

| Protected credential name | Encrypted file outside the repository | Purpose |
| --- | --- | --- |
| `ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_KEY` | `%h/.config/ai-bot-v2/credentials/profiled-base-feature-publisher/api-key.cred` | Account-specific key for the signed read-only Binance USD-M commission-rate GET |
| `ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_SECRET` | `%h/.config/ai-bot-v2/credentials/profiled-base-feature-publisher/api-secret.cred` | Account-specific signing secret for that GET |
| `PROFILED_BASE_COMMISSION_FINGERPRINT_HMAC_SECRET` | `%h/.config/ai-bot-v2/credentials/profiled-base-feature-publisher/fingerprint-hmac.cred` | Independent credential-binding fingerprint key; at least 32 UTF-8 bytes and unequal to either exchange credential |

The public binding is immutable for this unit:

- trader ID: `trader-wajidali1984`
- credential reference: `ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY`
- endpoint: signed `GET /fapi/v1/commissionRate` on the official Binance USD-M origin
- REST role: fallback-only behind `BINANCE_REST_FALLBACK_ALLOWED=true`
- rate-limit authority: the host-shared Redis budget; unavailable shared budget fails closed

`READONLY` in the credential reference and `read_only_ref=True` are local
operator provisioning assertions. They are not connector evidence of the
Binance-side permissions on the key. Before this unit is started, the operator
must provision a distinct exchange key and independently verify its Binance
permissions. The safety property established by this code is narrower: the
only exchange-authenticated operation reachable from this service is the
structurally fixed commission-rate GET; no order, leverage, margin, transfer,
cancel, or modification endpoint is reachable.

Create encrypted credential files locally with `systemd-creds encrypt`. Feed
each value through standard input or another protected local source; never put
plaintext values in this repository, shell arguments, the unit, or journal.
Pass `--name=` with the exact protected credential name from the table so the
encrypted payload identity matches the corresponding `LoadCredentialEncrypted`
slot; do not let the shorter output filename become the embedded identity.
At runtime, the loader accepts only systemd's exact fixed mount
`/run/user/<euid>/credentials/ai-bot-v2-profiled-base-feature-publisher.service`.
That directory must be owned by the effective user with mode `0500` and link
count 2; each decrypted credential must be owned by the effective user with
mode `0400` and link count 1. The unit's three `ConditionPathExists` checks
keep an incomplete encrypted source bundle inactive. Invalid, empty,
multiline, oversized, reused, wrongly bound, writable, shared, or hard-linked
runtime credentials cause exit status 78, which `RestartPreventExitStatus`
excludes from restart attempts.

The service writes only these absolute filesystem evidence paths:

- `/home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1`
- `/home/wali/ai_bot_local_data/v2_native_trainer/durable_feature_snapshot_ledger.sqlite3`
- `/home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/profiled_base_publisher_state_v1.json`
- `/home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/profiled_base_publisher_status_v1.json`

The publisher may append an authenticated child record that a separate loader
can evaluate for admission. It grants no trainer-process transition,
checkpoint, optimizer, prediction, paper-trading, risk, allocator,
or live-execution authority, and the unit has no `ExecStartPost`, `OnSuccess`,
or dependency that starts any of those consumers. systemd permits only one
main process for this non-template unit, while the publisher's durable writer
lock independently rejects a second ledger writer.
