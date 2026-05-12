# Function And Control Audit

Generated at: 2026-05-12T20:52:50Z

The crawler inspected links, buttons, inputs, and route navigation. Any control implying live enablement, order placement, cancellation, leverage/margin changes, API key activation, Redis trim approval, or paper-to-live switching must be disabled or approval-gated.

- Dangerous controls detected by label: 8
- Dangerous controls enabled: 0
- Public internal links checked: 45
- Local internal links checked: 45

Classification policy:

- `safe_read_only`: navigation, filters, evidence tabs, source links.
- `safe_paper_only`: paper/replay view commands that do not touch exchanges.
- `requires_validation`: settings validation and staged changes.
- `requires_explicit_human_approval`: live/canary/leverage/margin/API-key operations.
- `disabled_live_action`: live controls shown but disabled.
- `broken`: failed links or handlers.
- `missing_handler`: visible controls that do not produce a useful state.
