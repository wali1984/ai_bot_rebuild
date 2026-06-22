# Paper Runtime Wiring Report

Generated at: 2026-06-17T15:13:35-04:00

Command:

```bash
cd v2/frontend && npm run build:paper-online
cd v2/frontend && npm run run:paper-online
```

Runtime outputs:

- `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json`
- `v2/frontend/public/operator_runtime/paper_online/latest/paper_positions.json`
- `v2/runtime/paper_online/latest/paper_runtime_status.json`
- `v2/runtime/paper_online/latest/paper_positions.json`

Website visibility:

- Mission Control reads the paper runtime payload.
- Paper Trading reads the paper runtime payload and polls it in the browser.
- Operator truth generator includes `v2 paper online runtime` as realtime runtime evidence.
- Trainer Prediction Monitor reads the current V2 paper trainer wrapper prediction.
- Signal Explainability reads the current V2 paper signal lineage.
- Risk Control reads current V2 paper risk decisions.
