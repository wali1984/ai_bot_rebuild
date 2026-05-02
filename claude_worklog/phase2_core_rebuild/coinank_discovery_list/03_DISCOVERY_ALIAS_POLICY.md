# Discovery and Alias Policy

CoinAnk identities are discovery/alias evidence only.

- They never enter `eligible_for_training`, `training_active`, `eligible_for_paper`, `paper_trading`, `shadow_candidate`, or `live_blocked` automatically.
- They may move out of `discovered` only via auditable manual override, or after `confirm_coinank_against_usdm` returns a confirmed Binance USD-M identity.
- After confirmation, the promoted identity is the Binance USD-M `SymbolIdentity`, not the CoinAnk discovery record.

Alias responsibility:
- The CoinAnk identity contributes its `source_symbol` and `coinank_raw.symbol` to the alias set of the confirmed USD-M identity at registration time.
- The CoinAnk identity itself remains in the registry as a separate record so that auditors can trace the discovery path.

Match-collapse policy:
- `match_cross_source_symbol(coinank_id, any_other_id)` may return at most `low` (alias intersection); never `medium` or `high` because CoinAnk's `contract_family=unknown` and unique `COINANK-DISC-` prefix prevent collapse.
- The alias registry must record CoinAnk as a discovery channel separate from `binance_usdm`, `binance_coinm`, `coinapi_ws`, `coinapi_rest`, `kucoin`.

Auditing:
- Every promotion of a CoinAnk-derived alias must log: original CoinAnk `canonical_symbol_id`, confirming USD-M `canonical_symbol_id`, flags evaluated by `confirm_coinank_against_usdm`, operator (if manual override), timestamp.

PHASE2_COINANK_DISCOVERY_ALIAS_POLICY_READY
