# Subsystem Visibility Matrix

Every V2 subsystem maps to a (route, panel, real-source) triple. If the
payload is absent or stale, the panel renders an explicit MISSING /
STALE chip with the exact source string. No fabricated values.

| Subsystem | State | Route | Real source | Render on missing |
|---|---|---|---|---|
| live_gate | `blocked_human_only` | every page | constant invariant in every V2 status payload | banner blocks page until value present |
| shutdown | `blocked` | /risk, /automation, /admin/approval-status | absence of any SHUTDOWN_ACCEPTANCE marker | BLOCKED panel with audit pointer |
| full_observation_builder | `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` | /bot-intelligence, /automation | `full_observation_builder_status.json` | MISSING chip with explicit blocker source; never a fabricated dim |
| checkpoint_compatibility_claimed | `false` | /bot-intelligence, /admin/codex-reviews | builder status + every Codex review packet | warning chip if any payload asserts true without operator approval |
| policy_architecture_parity_claimed | `false` | /bot-intelligence | policy contract + Codex policy review | chip remains false |
| v2_trainer_feed | heartbeat present | /bot-intelligence | `v2:trainer:heartbeat` | STALE chip with last-seen UTC |
| v2_predictions | per-symbol | /bot-intelligence | `v2:prediction:{symbol}:1m` | MISSING per absent symbol |
| v2_paper_positions_intents_ledger | live | /paper | `v2:paper:positions` / `:intents` / `:intents_held_by_paper_fill_gate` / `:ledger` | empty-state panel |
| v2_position_price_track_history | recorder running; `entry_price` often null upstream | /paper, /bot-intelligence | `v2:paper:position_price_track:{symbol}` + `:position_history:{symbol}` | `MISSING_ENTRY_PRICE` blocker — never fabricate MFE/MAE/ROE |
| v2_orchestrator_decisions | live | /bot-intelligence, /risk | `v2:orchestrator:decisions` | STALE chip |
| v2_risk_decisions | live | /risk | `v2:risk:decisions` | EMPTY panel; never a fabricated allow/block |
| v2_market_liquidations_wss | daemon active, heartbeat fresh | /market (tape), /risk (health) | `v2:market:liquidations:heartbeat` + `:latest:{symbol}` + `:aggregate:{symbol}` | RED chip if TTL ≤ 0 |
| binance_top10_dashboards | 6 dashboards published | /market | `v2:dashboards:binance_top10:*` + public mirror | PARTIAL chip per dashboard with explicit source_status sentinel |
| nansen_altdata | key absent or API_FORBIDDEN_403; scores null | /market, /bot-intelligence | `v2:altdata:nansen:status` + `:symbol:{symbol}` | STATUS panel renders KEY_MISSING_NO_NETWORK or API_FORBIDDEN_403 with rate_limit_state |
| lunarcrush_altdata | key absent or API_FORBIDDEN_403; scores null | /market, /bot-intelligence | `v2:altdata:lunarcrush:status` + `:symbol:{symbol}` | same as Nansen |
| arkham_future | future-only placeholder | /market (badge) | `v2:altdata:arkham:status` | FUTURE_ONLY badge |
| alt_data_symbol_universe_scoring | MISSING_PROVIDER_DATA_SAFE | /market | `v2:symbol_universe:altdata_candidates` | must show `paper_symbols_expanded=false`, `live_symbols=[]`, `may_not_override_strict_paper_fill_gate=true`, `may_not_authorize_live_or_canary=true` |
| war_room_8h_daemon | timer active + enabled; heartbeat fresh | /automation | `v2:war_room:heartbeat` + war-room public payload | timeline must show cycle_id and tier flags |
| continuous_remediation_governor | READY | /automation, /risk | `codex_5m_status.json` | go_no_go + fail_blockers visible |
| legacy_log_observer | read-only observer running | /automation | governor.summary | STALE chip if older than 600s |
| codex_review_queue | war-room cycle review queued | /admin/codex-reviews | `codex_review_queue.json` | must show no approvals, no policy port, no checkpoint compatibility claim |

## Persistent must-show on every route

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_real / approves_canary / approves_legacy_shutdown / approves_redis_trim = false`
- `shutdown_status = blocked`
- `checkpoint_compatibility_claimed = false`
- `policy_architecture_parity_claimed = false`
- No mock data ever rendered as current truth
- No static proof fixture ever rendered as primary truth
- Missing provider data NEVER converted to a numeric score
