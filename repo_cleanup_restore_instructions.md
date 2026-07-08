# Restore Instructions — Repo Cleanup 2026-07-01

## Archive Location

```
/home/wali/AI_BOT_REBUILD_REPO_CLEANUP_ARCHIVE/20260701_184046/files/
```

## What Was Archived

| Source Path | Size | Archive Subdir |
|---|---|---|
| goal_state/V2_ACTIVE_PAPER_RUNTIME_OWNER_CUTOVER_* | 572K | files/goal_state/ |
| goal_state/V2_ADAPTIVE_CAPITAL_OUT_OF_SAMPLE_EVIDENCE_* | 539M | files/goal_state/ |
| goal_state/V2_CHALLENGER_BLIND_LOCKBOX_* | 1.9M | files/goal_state/ |
| goal_state/V2_CLAUDE_CONTINUOUS_*.premature-complete.* | 204K | files/goal_state/ |
| goal_state/V2_CLAUDE_PERFORMANCE_REGRESSION_RECOVERY_VERIFIER | 32K | files/goal_state/ |
| recorded_state_verification_pass2a/ | 13M | files/recorded_state_verification_pass2a/ |
| recorded_state_verification_pass2b/ | 2.2M | files/recorded_state_verification_pass2b/ |
| recorded_state_verification_pass3a/ | 2.2M | files/recorded_state_verification_pass3a/ |
| recorded_state_verification_pass3b/ | 2.2M | files/recorded_state_verification_pass3b/ |
| recorded_state_verification_pass3c/ | 2.2M | files/recorded_state_verification_pass3c/ |
| recorded_state_verification_pass4a/ | 18M | files/recorded_state_verification_pass4a/ |
| pipeline_trust_quarantine/ | 17M | files/pipeline_trust_quarantine/ |
| screenshots/ (136 files) | 177M | files/screenshots/ |
| v2/frontend/public/v2_zero_exception_* | 740K | files/v2_frontend_public_old/ |
| v2/frontend/public/historical_30d_replay_* | 156K | files/v2_frontend_public_old/ |
| v2/frontend/public/8h_trade_readiness/ | 84K | files/v2_frontend_public_old/ |
| v2/frontend/public/api/ | 24K | files/v2_frontend_public_old/ |

## Restore a specific goal_state dir

```bash
ARCHIVE="/home/wali/AI_BOT_REBUILD_REPO_CLEANUP_ARCHIVE/20260701_184046/files"
REPO="/home/wali/Desktop/AI BOT REBUILD"

# Example: restore V2_ACTIVE_PAPER_RUNTIME_OWNER_CUTOVER
rsync -a "$ARCHIVE/goal_state/V2_ACTIVE_PAPER_RUNTIME_OWNER_CUTOVER_CUDA_SIGNAL_CHAIN_AND_COMPOUNDING_REPAIR/" \
  "$REPO/goal_state/V2_ACTIVE_PAPER_RUNTIME_OWNER_CUTOVER_CUDA_SIGNAL_CHAIN_AND_COMPOUNDING_REPAIR/"
```

## Restore screenshots

```bash
ARCHIVE="/home/wali/AI_BOT_REBUILD_REPO_CLEANUP_ARCHIVE/20260701_184046/files"
REPO="/home/wali/Desktop/AI BOT REBUILD"
rsync -a "$ARCHIVE/screenshots/" "$REPO/screenshots/"
```

## Restore recorded_state_verification dirs

```bash
ARCHIVE="/home/wali/AI_BOT_REBUILD_REPO_CLEANUP_ARCHIVE/20260701_184046/files"
REPO="/home/wali/Desktop/AI BOT REBUILD"
for dir in recorded_state_verification_pass2a recorded_state_verification_pass2b \
            recorded_state_verification_pass3a recorded_state_verification_pass3b \
            recorded_state_verification_pass3c recorded_state_verification_pass4a \
            pipeline_trust_quarantine; do
  rsync -a "$ARCHIVE/$dir/" "$REPO/$dir/"
done
```

## Restore old frontend public dirs

```bash
ARCHIVE="/home/wali/AI_BOT_REBUILD_REPO_CLEANUP_ARCHIVE/20260701_184046/files/v2_frontend_public_old"
REPO="/home/wali/Desktop/AI BOT REBUILD"
for dir in v2_zero_exception_parity_codex_review_burndown_20260531 historical_30d_replay_and_paper_proof 8h_trade_readiness api; do
  rsync -a "$ARCHIVE/$dir/" "$REPO/v2/frontend/public/$dir/"
done
```

## What was DELETED without archive (cache artifacts)

These are all regeneratable:
- 620 `__pycache__/` directories (auto-created by Python on next run)
- 6245 `*.pyc` files (auto-created by Python on next run)
- 2 `.pytest_cache/` directories (auto-created by pytest on next run)
- `.coverage` files (auto-created by pytest-cov)
- `htmlcov/` directories
- `playwright-report/` directories
- `test-results/` directories
- `*.tsbuildinfo` files
- `.DS_Store` files

To regenerate all Python caches:
```bash
cd /home/wali/Desktop/AI BOT REBUILD
.venv/bin/python -m py_compile v2/backend/app/main.py
# Python auto-creates __pycache__ on import
```
