# Codex Review: V2 AI Throughput Acceleration and Resource Plan

GO/NO-GO: `V2_AI_THROUGHPUT_ACCELERATION_PLAN_CODEX_PASS`

This review supersedes the earlier failed review after the CLI command
remediation passed. It does not approve scheduler installation by itself,
GPU training, Codex Fast mode cost changes, live trading, canary, legacy
shutdown, Redis trim, or symbol adoption.

## Verdict

PASS. The plan now separates local compute from cloud AI inference, documents
the installed Codex CLI command forms accurately, preserves safety gates, and
provides a realistic path to higher Claude/Codex utilization.

## Verified

- Local hardware inventory exists and matches spot checks:
  AMD Ryzen 9 9950X, 32 logical CPUs / 16 cores, 123 GiB RAM, RTX 5080 with
  16303 MiB VRAM, and about 671 GiB free on repo disk.
- Execution modes correctly distinguish local tool execution from cloud model
  inference. Claude Code local terminal uses Anthropic cloud inference; Codex
  CLI local terminal uses OpenAI cloud inference.
- The plan does not claim local GPU accelerates Claude/Codex cloud reasoning.
  `gpu_speeds_claude_or_codex_cloud_reasoning=false` is explicit.
- GPU use is limited to local V2-native training/evaluation experiments, with
  default runlevel `OFF` and `operator_explicit_decision` required.
- Claude/Codex utilization targets exist:
  three active Claude implementation lanes and three active Codex review lanes
  when work exists.
- Parallel lane matrix exists with lane-level file locks and
  `max_writers_per_file_lock_group=1`.
- Scheduler design includes stale task monitoring, redispatch, file-lock
  enforcement, and safety-drift stop signals.
- Scheduler remains design-only in this plan packet until the separate
  scheduler implementation packet is created.
- Valid installed Codex command forms are documented and used:
  `codex review [OPTIONS] [PROMPT]`,
  `codex exec review [OPTIONS] [PROMPT]`, and
  `codex exec [OPTIONS] [PROMPT]`.
- Path/scope is embedded in review prompts rather than passed as an invalid
  review flag argument.
- Claude background/routine and multi-pane options are documented as
  operator/subscription-dependent and bound to the same no-live/no-old-Redis/
  no-shutdown safety contract.
- Operator cost decisions remain visible for edge thresholds, paid data
  sources, sample-count thresholds, scheduler install, and Codex fast-mode
  selection.

## Safety Scan

Scoped scans across the throughput packet and public mirror found no
executable old Redis write, no exchange mutation, no truthy approval, no
non-empty live symbols, and no raw secret material. The remaining mutation
words are safety-scan command strings or operator-decision text.

## Verification Evidence

```text
jq empty throughput/remediation JSON payloads
codex --version
codex --help
codex review --help
codex exec --help
codex exec review --help
negative old-form probe -> rejected by installed CLI
nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version --format=csv,noheader,nounits
lscpu
free -h
df -h .
```

Results: JSON validation passed; hardware spot checks matched the plan; the
CLI remediation review emitted
`V2_AI_THROUGHPUT_ACCELERATION_CLI_COMMAND_REMEDIATION_CODEX_PASS`.

## Safety Scoreboard

- did_not_modify_legacy = true
- did_not_stop_v2_runtime = true
- did_not_write_old_redis = true
- did_not_call_exchange_mutation = true
- did_not_enable_live = true
- did_not_create_approvals = true
- did_not_install_scheduler_in_plan_review = true
- did_not_dispatch_gpu_training = true
- did_not_enable_codex_fast_mode = true
- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
