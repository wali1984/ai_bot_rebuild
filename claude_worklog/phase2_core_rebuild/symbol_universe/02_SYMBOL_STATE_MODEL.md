# Symbol State Model

States:
- `discovered`
- `observed`
- `eligible_for_training`
- `training_active`
- `eligible_for_paper`
- `paper_trading`
- `shadow_candidate`
- `live_blocked`
- `disabled`
- `removed`
- `manual_override`

Manual overrides:
- `force_observe`
- `force_train`
- `force_disable`
- `force_paper`
- `force_shadow_candidate`
- `remove`
- `set_priority`
- `set_max_risk`
- `pause_symbol`

Default rule:
Non-trading symbols can be discovered but cannot enter active states without an explicit manual override.

Live trading remains blocked by default.

SYMBOL_STATE_MODEL_READY
