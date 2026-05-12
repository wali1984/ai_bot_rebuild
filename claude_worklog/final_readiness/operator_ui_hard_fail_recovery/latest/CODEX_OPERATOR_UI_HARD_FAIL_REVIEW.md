CODEX_OPERATOR_UI_HARD_FAIL_REVIEW

Review result: PASS.

Checks:
- The previous UI READY marker was not trusted without screenshots.
- Browser screenshots were captured for the required acceptance routes.
- Mission Control now leads with a current operator truth command deck instead of raw proof/payload tables.
- Admin navigation is grouped, styled, active-route aware, and includes warning counts.
- Mission Control includes critical system cards for paper/shadow, trainer, orchestrator, risk gateway, execution, Redis/V2 data plane, Postgres/audit, and live block.
- Paper Trading, Replay, and Live Readiness are no longer placeholder-only shells.
- Supervisor stale/conflicting state is visible.
- Trainer runtime evidence missing state is visible.
- Static proof fixture status is visible and not represented as live truth.
- Route summaries were added to Monitor Center, Trainer Prediction Monitor, and Signal Explainability.
- Route summaries were also added to Risk Control, Config Admin, Build Validation, Claude Admin AI, Mobile/iPhone Readiness, Paper Trading, Replay, and Live Readiness.
- Raw process rows and detailed payload freshness table are available but no longer dominate the first screen.
- TradingView is the primary chart widget and now has a visible loading/fallback state instead of an unlabeled blank panel.
- Live blocked banner remains visible and undismissable.
- No mock `data.jsx` values were imported as runtime truth.
- No live, exchange, Redis mutation, legacy mutation, leverage, margin, or secret action was performed.

Residual risk:
- Current runtime truth remains unfavorable: supervisor is stale/conflicting and trainer runtime evidence is missing.
- This pass fixes operator visibility; it does not remediate the underlying runtime/trainer/supervisor blockers.
