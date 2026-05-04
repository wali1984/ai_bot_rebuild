CODEX_DIRTY_TREE_DISPATCH_HOLD_RECOVERY_BLOCKED

The recovery is blocked because `git status --short` returned an empty dirty set, while the trigger report requires the dirty set to equal exactly twenty-eight scoped paths before audit, scan, stage, commit, and push may proceed. Since that precondition failed, Codex did not run the scoped audit or secret scan, did not stage files, did not commit, and did not push.
