# V2 Nansen Free-Tier Endpoint Allowlist Remediation

Generated: `2026-05-21T05:45:41Z`

GO/NO-GO: `V2_NANSEN_FREE_TIER_ENDPOINT_ALLOWLIST_REMEDIATION_READY`

## Scope

Patch-only remediation of the Codex fail blocker
`NANSEN_CLIENT_ENDPOINT_OVERRIDE_CAN_REACH_UNREVIEWED_OR_PAID_ENDPOINT`
on `v2/backend/app/services/alternative_data/nansen_client.py`.

This packet:

- does NOT implement LunarCrush
- does NOT call any paid Nansen endpoint
- does NOT expose the raw `NANSEN_API_KEY` value
- does NOT modify legacy code, legacy runtime, or any legacy Redis key
- does NOT enable live or canary trading
- does NOT change leverage or margin
- does NOT create approvals
- does NOT allow alternative data to override the strict paper-fill gate

`live_gate=blocked_human_only`, `live_symbols=[]`, and
`live_enabled=false` are unchanged.

## Codex Fail Blocker

From the prior Codex review:

> The `NansenClient` constructor still allows callers to override
> `smart_money_endpoint` and `api_base_url`. Codex proved, without
> making a real network call, that a directly constructed client can
> target a non-default endpoint while using the same `apikey` auth
> header.

Proof from Codex:

> - constructed `NansenClient(smart_money_endpoint="/api/v1/paid/not-reviewed")`
> - observed called URL: `https://api.nansen.ai/api/v1/paid/not-reviewed?symbol=BTCUSDT`
> - source status: `API_OK`

## Source Patch

File:
[v2/backend/app/services/alternative_data/nansen_client.py](v2/backend/app/services/alternative_data/nansen_client.py)

### 1. Constructor refuses both override kwargs

The constructor signature no longer accepts `api_base_url` or
`smart_money_endpoint`. A caller that tries either will raise
`TypeError: unexpected keyword argument 'smart_money_endpoint'`. The
base URL is the module-level constant
`NANSEN_API_BASE_URL_DOCUMENTED` and is never read from caller
input.

### 2. Endpoint allowlist by ID

```python
DEFAULT_ENDPOINT_ID = "smart_money_holdings_free"
FREE_ENDPOINT_PATHS = {
    "smart_money_holdings_free": "/api/v1/smart-money/holdings",
}
PAID_ENDPOINT_PATHS = {}  # empty today; reserved for future
PAID_ENABLED_ENV_VAR = "ALT_DATA_ENABLE_PAID"
```

Callers select an endpoint by ID via `endpoint_id="..."`. Public
helpers `is_free_endpoint`, `is_paid_endpoint`, and
`is_allowlisted_endpoint` expose the contract.

### 3. New refusal sentinels

```python
SOURCE_STATUS_ENDPOINT_NOT_ALLOWLISTED = "NANSEN_ENDPOINT_NOT_ALLOWLISTED"
SOURCE_STATUS_PAID_ENDPOINT_DISABLED  = "NANSEN_PAID_ENDPOINT_DISABLED"
```

### 4. `fetch_symbol` short-circuit

The first step inside `fetch_symbol` is now an endpoint decision:

```python
endpoint_path, endpoint_refusal = self._endpoint_decision()
if endpoint_refusal is not None:
    return self._result(... source_status=endpoint_refusal)
```

This runs BEFORE the key-presence check and BEFORE any HTTP. The
refusal never sets `rate_limit.last_request_ms`, so the CLI status
field `network_call_attempted` stays `False` for these paths.

### 5. URL construction

```python
def _build_url(self, symbol, endpoint_path):
    return f"{NANSEN_API_BASE_URL_DOCUMENTED}{endpoint_path}?symbol={symbol}"
```

The base URL is taken from the module-level constant only — never
from instance state or caller input.

### 6. Status payload surfaces the contract

The aggregate status payload now carries:

- `endpoint_allowlist_enforced: true`
- `constructor_accepts_api_base_url_override: false`
- `constructor_accepts_smart_money_endpoint_override: false`
- `free_endpoint_ids_allowed: ["smart_money_holdings_free"]`
- `paid_endpoint_ids_registered: []`
- `paid_endpoints_env_var: "ALT_DATA_ENABLE_PAID"`
- `paid_endpoints_env_value: false`

The per-symbol payload carries the same `endpoint_allowlist_enforced`
and `constructor_accepts_*_override` flags.

## Auth Header

The auth header name remains `apikey` and is never emitted in any
payload. The raw key is loaded only inside `fetch_symbol`, used to
populate the header, then released via `del key`. The
`credential_in_payload` field stays `"NEVER"` on all paths,
including the new refusal paths.

## Allowed Writes (Unchanged)

`_safe_redis_set` continues to refuse any key outside:

- `v2:altdata:nansen:status`
- `v2:altdata:nansen:symbol:{symbol}`

## Regression Tests

File:
[v2/backend/tests/integration/cli/test_v2_nansen_altdata_ingestor.py](v2/backend/tests/integration/cli/test_v2_nansen_altdata_ingestor.py)

10 new tests, each designed to fail under the prior code shape and
pass under the patched code:

- `test_constructor_refuses_smart_money_endpoint_override` — exact
  Codex proof reversed: `NansenClient(smart_money_endpoint=...)`
  raises `TypeError`.
- `test_constructor_refuses_api_base_url_override` — same for
  `api_base_url`.
- `test_endpoint_allowlist_blocks_unknown_endpoint_id_before_http` —
  unknown ID emits `NANSEN_ENDPOINT_NOT_ALLOWLISTED` with zero HTTP
  calls.
- `test_paid_endpoint_unreachable_when_paid_disabled` — temporarily
  registers a paid ID; client refuses with
  `NANSEN_PAID_ENDPOINT_DISABLED` and zero HTTP calls.
- `test_paid_endpoint_disabled_when_env_var_not_true` —
  `ALT_DATA_ENABLE_PAID=false` keeps paid disabled.
- `test_free_endpoint_id_reaches_documented_base_url_only` — when
  the free ID is used, the URL passed to `http_get` starts with
  `https://api.nansen.ai`. Attacker-supplied hosts cannot appear.
- `test_raw_key_never_appears_in_payload` — even on refusal paths,
  the sentinel key value never appears in the serialized payload.
- `test_no_legacy_redis_or_exchange_writes_on_refusal_paths` —
  refusal-path payloads still pin
  `writes_legacy_redis=false`,
  `writes_exchange_orders=false`,
  `approves_live=false`,
  `approves_canary=false`,
  `live_gate=blocked_human_only`,
  `live_symbols=[]`.
- `test_module_allowlist_contains_only_free_smart_money_holdings_today` —
  pins the current allowlist contract so a future change must
  update this test.
- `test_status_payload_surfaces_endpoint_allowlist_contract` — the
  CLI status mirrors expose the allowlist contract end-to-end.

## Source-Level Grep Proof

After the patch, the following attribute and kwarg names are absent
from the active Nansen client logic:

- `self._api_base_url`: 0 hits
- `self._smart_money_endpoint`: 0 hits

The only remaining references to those tokens are inside the new
test names (`test_constructor_refuses_smart_money_endpoint_override`)
and the regression assertions, neither of which is reachable from
production. The LunarCrush client retains its own
`api_base_url`/`social_endpoint` shape; the user explicitly stated
LunarCrush is out of scope for this packet, so it is unmodified.

## Validation

| Check | Result |
| ----- | ------ |
| Focused Nansen tests | PASS (30 of 30) |
| `py_compile` of patched client | PASS |
| Raw credential scan on patched files | PASS (0 hits outside `.local_secrets`) |
| Old Redis write scan on patched files | PASS (0 hits) |
| Exchange-mutation scan on patched files | PASS (0 hits) |
| Approval drift scan | PASS |
| JSON validation of refreshed Nansen payloads + remediation status | PASS |
| Status-refresh via patched code with daily budget 0 and no key | PASS (no provider network call) |

## Refreshed Status Mirrors

The existing Nansen client status mirrors were re-rendered using
the patched code with `NANSEN_API_KEY` absent and
`ALT_DATA_ENABLE_PAID` unset; the new fields are now surfaced in
all three mirrors:

- `claude_worklog/final_readiness/v2_nansen_altdata_client/latest/v2_nansen_altdata_status.json`
- `v2/frontend/public/operator_runtime/v2_nansen_altdata_client/latest/v2_nansen_altdata_status.json`
- `v2/frontend/public/v2_nansen_altdata_client/latest/operator_dashboard_payload.json`

All three report:

- `go_no_go: V2_NANSEN_FREE_TIER_CLIENT_PAPER_SHADOW_READY`
- `endpoint_allowlist_enforced: true`
- `constructor_accepts_api_base_url_override: false`
- `constructor_accepts_smart_money_endpoint_override: false`
- `paid_endpoints_enabled: false`
- `free_endpoint_ids_allowed: ["smart_money_holdings_free"]`
- `paid_endpoint_ids_registered: []`
- `paid_endpoints_env_var: ALT_DATA_ENABLE_PAID`
- `paid_endpoints_env_value: false`
- `key_present: false`
- `network_call_attempted: false`
- `credential_in_payload: NEVER`
- `live_gate: blocked_human_only`
- `live_symbols: []`

## Safety Posture

All safety invariants from the prior Codex PASS portion of the
review are preserved or strengthened:

- raw API key never emitted
- auth header name remains `apikey`
- allowed writes restricted to `v2:altdata:nansen:status` and
  `v2:altdata:nansen:symbol:{symbol}`
- alternative data may not override the strict paper-fill gate
- alternative data may not authorize live or canary
- alternative data may not place orders
- `live_gate=blocked_human_only`
- `live_symbols=[]`
- no provider failure can stop the V2 runtime (provider errors are
  classified into source-status sentinels and never re-raised)

## Final Decision

`V2_NANSEN_FREE_TIER_ENDPOINT_ALLOWLIST_REMEDIATION_READY`
