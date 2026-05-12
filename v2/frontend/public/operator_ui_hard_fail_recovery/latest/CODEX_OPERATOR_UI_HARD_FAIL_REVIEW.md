CODEX_OPERATOR_UI_HARD_FAIL_REVIEW

Review result: PASS.

Checks:
- The previous UI READY marker was not trusted without screenshots.
- Browser screenshots were captured before and after the remediation.
- Mission Control now leads with a current operator truth command deck instead of raw proof/payload tables.
- Supervisor stale/conflicting state is visible.
- Trainer runtime evidence missing state is visible.
- Static proof fixture status is visible and not represented as live truth.
- Route summaries were added to Monitor Center, Trainer Prediction Monitor, and Signal Explainability.
- Raw process rows and detailed payload freshness table are available but no longer dominate the first screen.
- Live blocked banner remains visible and undismissable.
- No mock `data.jsx` values were imported as runtime truth.
- No live, exchange, Redis mutation, legacy mutation, leverage, margin, or secret action was performed.

Residual risk:
- Current runtime truth remains unfavorable: supervisor is stale/conflicting and trainer runtime evidence is missing.
- This pass fixes operator visibility; it does not remediate the underlying runtime/trainer/supervisor blockers.
