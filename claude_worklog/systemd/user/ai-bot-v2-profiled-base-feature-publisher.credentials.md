# Profiled base-feature publisher credential contract

This is a deployment contract, not an activation instruction. Installing,
enabling, or starting the unit remains an explicit operator action.

The service imports one optional, all-or-nothing bundle of exactly three
systemd credentials. It does not load a repository `.env`, a service
`EnvironmentFile`, generic `BINANCE_*` variables, or secrets from command-line
arguments. If no imported credential matches, the process remains online in
`MASKED_COST_OBSERVATION` mode. If any credential is imported, all three must
pass the strict binding below; partial or malformed bundles fail closed.

| Protected credential name | systemd credential-store identity | Purpose |
| --- | --- | --- |
| `ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_KEY` | exact same name imported by `ImportCredential=` | Account-specific key for the signed read-only Binance USD-M commission-rate GET |
| `ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_SECRET` | exact same name imported by `ImportCredential=` | Account-specific signing secret for that GET |
| `PROFILED_BASE_COMMISSION_FINGERPRINT_HMAC_SECRET` | exact same name imported by `ImportCredential=` | Independent credential-binding fingerprint key; at least 32 UTF-8 bytes and unequal to either exchange credential |

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

Create encrypted credential-store entries locally with `systemd-creds
encrypt`. Feed each value through standard input or another protected local
source; never put plaintext values in this repository, shell arguments, the
unit, or journal. Pass `--name=` with the exact protected credential name from
the table and install it under a systemd encrypted credential store searched
by `ImportCredential=` (for example `/etc/credstore.encrypted/` on this host).
Do not let a shorter output filename become the embedded identity.
At runtime, the loader accepts only systemd's exact fixed mount
`/run/user/<euid>/credentials/ai-bot-v2-profiled-base-feature-publisher.service`.
That directory, when created by systemd for at least one imported credential,
must be owned by the effective user with mode `0500` and link count 2; each
decrypted credential must be owned by the effective user with mode `0400` and
link count 1. Exact absence of the final per-unit directory means no credential
was imported and selects masked mode. An existing empty or partial directory,
or invalid, multiline, oversized, reused, wrongly bound, writable, shared, or
hard-linked runtime credential causes exit status 78, which
`RestartPreventExitStatus` excludes from restart attempts.

Masked mode still captures and durably appends the authenticated 35-field
OHLCV parent after its prospective decision time. The required four-field cost
bundle is reported with missing mask `[1,1,1,1]`, stale mask `[0,0,0,0]`, and
source-availability mask `[0,0,0,0]`. It emits no cost values or receipts, is
never trainer-admission eligible, and is never retrospectively enriched. Once
a complete safe bundle is imported and the service is restarted, only a new
finalized decision window may produce the exact trainer-admissible 35+4 pair.
Before appending a masked parent, the publisher durably writes a canonical,
self-hashed recovery intent bound to the parent ID, record hash, finalized
window fingerprint, capture policy, transform configuration, and cost-mask
binding. A restart or state-file loss authenticates the exact committed ledger
parent against that receipt instead of rebuilding its timestamped identity.
An intent whose parent never committed grants no recovery or trainer authority.

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
