# Top Live Blockers Burn-Down

Generated at: 2026-05-13T06:26:43.149Z

Full live ready: `false`

Live gate: `blocked_human_only`

| status | count |
| --- | --- |
| BLOCKED | 4 |
| MISSING_EVIDENCE | 4 |
| PASS | 9 |

| blocker | status | next_remediation | owner | required_for_tiny_canary |
| --- | --- | --- | --- | --- |
| script migration incomplete | BLOCKED | Continue P0/P1 wrappers and ports. | primary_migration | partial; P0 safety rows required first |
| trainer parity not fully proven | BLOCKED | Prove legacy PPO/MASA parity through V2 bridge. | primary_trainer_parity | true |
| legacy still owns live execution | BLOCKED | Keep legacy read-only observed while V2 execution remains paper-only. | primary_migration | true |
| paper/shadow 6h/24h proof missing | MISSING_EVIDENCE | continue primary burn-down task | Claude/Codex | true |
| read-only account verification missing | MISSING_EVIDENCE | Add read-only account status payload before canary. | primary_live_gate | true |
| exchange trade permission unknown | MISSING_EVIDENCE | Confirm trade permission state manually/read-only. | primary_live_gate | true |
| isolated margin verification missing | PASS | Keep isolated-only policy in guard. | primary_risk | true |
| leverage cap verification missing | PASS | Keep 1x cap unless human approval changes it. | primary_risk | true |
| stop/kill switch runtime proof | PASS | Continue runtime assertions. | primary_risk | true |
| daily/weekly loss gate runtime proof | MISSING_EVIDENCE | Add weekly loss gate runtime evidence. | primary_risk | true |
| Admin AI cannot enable live | PASS | Keep Admin AI read-only/non-live. | support_ui | true |
| dangerous controls disabled | PASS | Continue browser audits. | support_ui | true |
| stale signal blocks | PASS | Keep stale-signal runtime tests. | primary_risk | true |
| missing attribution blocks | PASS | Continue attribution blocker tests. | primary_risk | true |
| duplicate execution dedupe | PASS | Feed dedupe state into V2 data plane. | primary_migration | true |
| old Redis write isolation | PASS | Keep legacy Redis write ban. | primary_safety | true |
| V2 data-plane independence | BLOCKED | Enable V2 durable DB/bounded Redis only after safe config. | primary_data_plane | true |
