# Codex Review: V2 GitHub-Only Credential Purge

GO/NO-GO: `V2_GITHUB_ONLY_CREDENTIAL_PURGE_CODEX_FAIL`

This review covers the GitHub-only credential purge packet. It does not approve
live trading, canary, legacy shutdown, Redis trim, exchange mutation, Git
history rewrite, or local credential deletion.

## Blocking Findings

1. **The packet is an audit, not a completed purge.**

   The READY packet still reports unresolved Git-visible findings:

   ```text
   tracked_secret_findings_count=41931
   public_payload_secret_findings_count=975
   worklog_secret_findings_count=19246
   files_remediated=0
   ```

   Codex cannot verify that raw credentials are absent from Git-tracked files,
   public payloads, or worklog artifacts while the packet's own scanner reports
   nonzero findings and no remediation.

2. **Git-history rewrite is required but not resolved.**

   The status payload reports:

   ```text
   git_history_rewrite_required=true
   git_history_rewrite_status=OPERATOR_DECISION_REQUIRED_GIT_HISTORY_REWRITE
   ```

   This is correctly operator-gated and was not auto-run, but it means the
   purge is not complete.

3. **The GO/NO-GO marker says READY despite unresolved findings.**

   `GO_NO_GO.md` says `V2_GITHUB_ONLY_CREDENTIAL_PURGE_READY`, but the current
   evidence does not satisfy the Codex review contract that raw credentials are
   absent from Git-visible/public surfaces.

## Fix Applied During Review

- Hardened `.gitignore` for future local-only env/key/checkpoint/model dumps:
  `*.env`, PEM/key bundle patterns, credential-dump patterns, and common model
  checkpoint extensions are now ignored, while example env files remain allowed.

## Verified Safe

- Local runtime vaults were not deleted.
- `.local_secrets/` remains ignored and local. `git ls-files` reports no tracked
  `.local_secrets`, `.local_models`, or env files from the checked patterns.
- `.local_secrets` values were not read or printed during this review.
- The packet correctly marks Git history rewrite as
  `OPERATOR_DECISION_REQUIRED_GIT_HISTORY_REWRITE`; no rewrite was run.
- Safety fields remain blocked:
  `live_gate=blocked_human_only`, `live_symbols=[]`,
  `approves_live=false`, `approves_canary=false`,
  `approves_legacy_shutdown=false`, and `approves_redis_trim=false`.
- Scoped review found no old Redis write action, exchange mutation action, or
  live/shutdown approval in the credential-purge packet.

## Probe Evidence

```text
git check-ignore -v .local_secrets/live_credentials.env
git check-ignore -v .local_secrets/live_canary_credentials.env
git check-ignore -v .local_models/model.ckpt
```

Result: paths are ignored; values were not read.

```text
git ls-files .local_secrets .local_models '*.env' 'v2/.env.local'
```

Result: no tracked local vault/env files were listed.

High-confidence raw-secret path scan, excluding local vault/model and dependency
directories, returned one test fixture file containing documented fake example
tokens used to validate redaction behavior:

```text
v2/backend/tests/unit/services/report_center/test_report_center.py
```

## Required Remediation Before Pass

1. Classify the current scanner findings into confirmed secrets vs false
   positives without printing raw values.
2. Remove confirmed raw credentials from Git-tracked files, public payloads, and
   worklog artifacts, replacing them with env-var names or redacted placeholders.
3. Regenerate the purge packet with zero unresolved confirmed Git-visible and
   public-payload secret findings.
4. Keep local runtime vaults untouched.
5. Keep Git history rewrite operator-gated unless the operator explicitly
   approves it.

## Safety Scoreboard

- did_not_delete_local_credentials = true
- did_not_read_local_secret_values = true
- did_not_modify_legacy = true
- did_not_stop_v2_runtime = true
- did_not_write_old_redis = true
- did_not_call_exchange_mutation = true
- did_not_enable_live = true
- did_not_create_approvals = true
- live_gate = blocked_human_only
- live_symbols = []

