# Claude Autonomy Authority Model

- L0 observe only
- L1 docs/tests/reports
- L2 V2 non-execution code
- L3 V2 monitoring/risk/audit code with tests
- L4 V2 paper/replay strategy experiments
- L5 propose live/capital changes; human approval required
- L6 live autonomous changes; disabled

Assignments:

- Claude in V2: `L4`
- Codex in V2: `L3 review/audit`
- Claude on legacy live bot: `L0`
- Codex on legacy live bot: `L0`
- Live/capital: `L5 human approval required`
- L6: `disabled`

Claude may autonomously modify V2 code, docs, tests, monitors, paper/replay, GUI, trainer wrappers, risk gateway, migration tasks, and validation artifacts.

Claude may not autonomously modify legacy live bot, mutate legacy Redis, take exchange/capital actions, change margin/leverage, approve final live/capital gate, hide missing evidence, or mark stale data current.
