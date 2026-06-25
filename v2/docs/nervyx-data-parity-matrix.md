# NERVYX Data Parity Matrix

- Generated at: `2026-06-23T20:57:22Z`
- Status: UNPROVEN / IN PROGRESS.
- Required result remains: 100% classified, 0 unexplained fields, 0 unintentionally removed fields, 0 incompatible type changes.

This initial matrix records the sources that must be fully enumerated. A later pass must expand every endpoint/event/model field into the table below.

## 2026-06-23 Automated Inventory Baseline

Artifact:

- `artifacts/nervyx-data-surface-inventory.json`
- `artifacts/nervyx-data-surface-inventory-summary.json`

Read-only inventory command: `../.venv/bin/python scripts/nervyx_data_surface_inventory.py`

| Inventory area | Count | Current interpretation |
|---|---:|---|
| OpenAPI operation responses | 118 | Captured from `docs/nervyx-openapi-after.json`; not yet permission/classification complete |
| OpenAPI component fields | 91 | Captured component schema property paths; nested `$ref` expansion remains limited |
| Backend route surfaces | 152 | Captured FastAPI route decorators from `backend/app/api` and `backend/app/main.py`, including HTTP and WebSocket decorators |
| Backend route methods | 112 GET / 26 POST / 4 PUT / 4 DELETE / 6 WEBSOCKET | Captured route method distribution; does not yet prove role access or rendered field parity |
| Backend Redis/read-model key literals | 1163 | Captured `v2:` / `audit:` / `readonly_market_exchange_data_plane` key literals from API/service/CLI source; live Redis value expansion still pending |
| Backend read-model key categories | 57 | Top categories include market, paper, altdata, features, prediction, trainer, risk, signals, orchestrator, liquidations, portfolio, audit, and live gate |
| Frontend realtime resource subscriptions | 112 | Captured `useRealtimeResource` call sites, URLs/sources when statically literal, stale thresholds, HTTP fallback flags, and generic payload hints |
| Frontend TypeScript interfaces | 483 | Captured interface field names from `frontend/src`, excluding generated bundles |
| Frontend TypeScript interface fields | 5282 | Source-model field baseline for web parity review |
| Swift Codable models | 76 | Captured `Codable`/`Decodable`/`Encodable` structs from `mobile/Sources/AIBotV2*` |
| Swift Codable fields | 474 | Native model field baseline for iOS/watchOS parity review |
| Swift API endpoints | 26 | Captured `APIEndpoints.swift` constants: 23 HTTP paths and 3 WebSocket/resource stream paths |
| Runtime snapshot samples | 500 | Sampled JSON payloads from public runtime/operator-runtime folders under size limits |
| Runtime snapshot top-level fields | 12349 | Top-level field baseline from sampled runtime snapshot JSON |

This baseline moves the data-preservation gate from a placeholder to a repeatable inventory input. It still does not satisfy the final parity requirement because every field still needs permission, source service, unit, null behavior, freshness threshold, destination, formatter, evidence/detail location, test status, and intentional-removal classification.

## 2026-06-23 Current Inventory Refresh

Read-only inventory command: `../.venv/bin/python scripts/nervyx_data_surface_inventory.py`

| Inventory area | Count |
|---|---:|
| OpenAPI operation responses | 118 |
| OpenAPI component fields | 91 |
| Backend route surfaces | 152 |
| Backend Redis/read-model key literals | 1163 |
| Backend read-model key categories | 57 |
| Frontend realtime resource subscriptions | 112 |
| Frontend TypeScript interfaces | 483 |
| Frontend TypeScript interface fields | 5282 |
| Swift Codable models | 76 |
| Swift Codable fields | 474 |
| Swift API endpoints | 26 |
| Runtime snapshot samples | 500 |
| Runtime snapshot top-level fields | 12349 |

The refreshed artifact status is `IN_PROGRESS_NOT_FULL_PARITY`. It is a current source and snapshot inventory, not final field-level parity proof. The known gaps remain permission classification, unit/null/freshness/formatter/destination accounting, live WebSocket frame validation, direct live Redis value expansion, and native rendered iOS/watchOS validation.

## 2026-06-23 Expanded Inventory Refresh

The inventory script now captures additional parity inputs beyond the earlier
OpenAPI/frontend/Swift/runtime sample:

- Backend route decorators: `artifacts/nervyx-data-surface-inventory.json.backend_route_surfaces`
- Backend Redis/read-model key literals: `artifacts/nervyx-data-surface-inventory.json.backend_read_model_keys`
- Swift endpoint constants: `artifacts/nervyx-data-surface-inventory.json.swift_api_endpoints`

Representative backend read-model categories from the refreshed artifact:

| Category | Key literal count |
|---|---:|
| `market` | 285 |
| `paper` | 175 |
| `altdata` | 107 |
| `features` | 101 |
| `prediction` | 71 |
| `trainer` | 71 |
| `risk` | 52 |
| `signals` | 41 |
| `orchestrator` | 34 |
| `liquidations` | 16 |
| `portfolio` | 10 |
| `audit` | 9 |

This is stronger evidence for source coverage, but it is still not complete
field parity. The key inventory enumerates source literals; it does not yet
connect each key to every runtime field, permission, frontend destination,
mobile destination, formatter, stale/null behavior, and test result.

## Added Open Requirements

- Position entry, close/exit, and mark prices must render from real backend/trading-read-model values only. Missing, null, decode failure, stale, or unavailable prices must not be converted to `0`.
- Position mark price must be realtime on every website and app surface through the resource WebSocket, with API fallback only marked as fallback and with visible stale/unavailable states.
- Website and app position views for bot active, open, closed, and historical positions must include AI reasoning sourced from actual prediction, signal, and trainer evidence that already exists in backend payloads.
- Native app parity must expand beyond the current limited cards by adding all useful backend cards/panels in structured sections, using modern Swift async/await realtime loading, no placeholder comments or placeholder values, and no manual refresh requirement for data to appear.

| Source area | Inventory mechanism | Current status | Blocker |
|---|---|---|---|
| OpenAPI | `docs/nervyx-openapi-before.json`, `docs/nervyx-openapi-after.json`, `artifacts/nervyx-data-surface-inventory.json` | baseline captured | compatibility still UNPROVEN because merge-base raw capture is shimmed/partial |
| realtime events | `useRealtimeResource`, backend `/api/v2/ws/resource`, native resource WS clients | 112 frontend resource subscriptions inventoried | live frame field accounting and native resource-client parity pending |
| Redis-backed read models | public/operator runtime payload folders and backend read adapters | 500 runtime JSON snapshots sampled | direct Redis key/value field extraction pending |
| Swift Codable models | `mobile/Sources/AIBotV2`, `mobile/Sources/AIBotV2Core` | 76 Codable/Decodable/Encodable models inventoried | destination parity against web/OpenAPI pending |

| Backend field name | Endpoint | Realtime topic | Source service | Expected type | Unit | Null behavior | Freshness threshold | Public | Trader | Admin | Superadmin | Web destination | iOS destination | watchOS destination | Evidence/detail destination | Formatter | Tested | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `_INVENTORY_PENDING` | all | all | all | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | pending | pending | pending | pending | pending | no | UNPROVEN |
| `positions[].entry_price` | `/api/v2/account/positions`, `/api/v2/portfolio`, `/api/v2/mobile/positions`, `/api/v2/paper/status` | `/api/v2/ws/resource` account/paper resources | trader repository + Redis paper read model | `number|null` | quote currency price | `null` means no positive recorded entry price; never coerced to zero | account stream 24s stale threshold; paper activity row age shown separately | hidden unless route allows | portfolio/positions cards | paper status/diagnostics | paper status/diagnostics | `/portfolio`, `/admin/paper-trading` | `PositionsView` price detail | synced position payload when present | entry source tooltip/detail | price formatter, unavailable on null | yes, focused | PARTIAL: field classified for touched surfaces |
| `positions[].entry_price_source` | same as `entry_price` | same | read-only presentation adapter | `string|null` | source field name | `null` means unavailable source | same as entry price | hidden unless route allows | `/portfolio` Entry Source | `/admin/paper-trading` title/details | `/admin/paper-trading` title/details | position card/source tooltip | `PositionsView` Entry Source | not synced | rendered-field evidence | runtime text formatter | yes, focused | PARTIAL |
| `positions[].mark_price` | `/api/v2/account/positions`, `/api/v2/portfolio`, `/api/v2/mobile/positions`, `/api/v2/paper/status` | market/account resource websocket; API fallback | public market WS/REST mark projection, stored paper mark fallback | `number|null` | quote currency price | `null` means no live/stored positive mark; never coerced to zero | >90s marked stale | hidden unless route allows | `/portfolio` Mark | `/admin/paper-trading` Mark | `/admin/paper-trading` Mark | `PositionsView`, watch position row | watch row if present | mark source/age fields | price formatter, unavailable on null | yes, focused | PARTIAL |
| `positions[].mark_price_age_seconds` | same as `mark_price` | same | mark-price candidate selector | `number|null` | seconds | `null` means freshness unavailable | >90s stale | hidden unless route allows | `/portfolio` Mark Age | `/admin/paper-trading` title/detail | `/admin/paper-trading` title/detail | `PositionsView` Mark Age | watch sync payload if present | rendered-field evidence | age formatter | yes, focused | PARTIAL |
| `positions[].mark_price_stale` | same as `mark_price` | same | mark-price candidate selector | `boolean` | state | `false` only when backend has no stale proof; stale age still shown when present | >90s true | hidden unless route allows | warning color | warning color | warning color | warning color | warning color | rendered-field evidence | state color | yes, focused | PARTIAL |
| `positions[].decision_reasoning` | `/api/v2/account/positions`, `/api/v2/portfolio`, `/api/v2/mobile/positions`, `/api/v2/paper/status` | account/paper resource websocket | Redis signal read model + paper ledger row fallback | `object|null` | decision evidence | `null` means no matching signal or ledger decision basis available | inherits source signal/ledger timestamp when present | hidden unless route allows | AI Reasoning / AI Basis | AI Basis | AI Basis | `PositionsView` AI Reasoning | watch row reason snippet | evidence/detail destination | public runtime text formatter | yes, focused | PARTIAL |
| `closed_trades[].entry_price` | `/api/v2/paper/status` | paper status resource | Redis `v2:paper:closed_trades` | `number|null` | quote currency price | zero/negative ledger values are treated as unavailable unless another positive recorded entry field exists | ledger timestamp | hidden | n/a | `/admin/paper-trading` history | `/admin/paper-trading` history | history table | pending richer app history surface | n/a | entry source title | price formatter | yes, focused | PARTIAL |
| `closed_trades[].exit_price` | `/api/v2/paper/status` | paper status resource | Redis `v2:paper:closed_trades` | `number|null` | quote currency price | zero/negative ledger values are treated as unavailable unless another positive recorded exit/close field exists | ledger timestamp | hidden | n/a | `/admin/paper-trading` history | `/admin/paper-trading` history | history table | pending richer app history surface | n/a | exit source title | price formatter | yes, focused | PARTIAL |
| `closed_trades[].decision_reasoning` | `/api/v2/paper/status` | paper status resource | Redis signal read model + closed-trade ledger row fallback | `object|null` | decision evidence | `null` means no matching signal or ledger decision basis available | inherits source signal/ledger timestamp when present | hidden | n/a | AI Basis | AI Basis | history table | pending richer app history surface | n/a | evidence/detail destination | public runtime text formatter | yes, focused | PARTIAL |
