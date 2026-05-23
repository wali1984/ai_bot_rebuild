# V2 AI Throughput Acceleration and Resource Plan

GO/NO-GO: V2_AI_THROUGHPUT_ACCELERATION_AND_RESOURCE_PLAN_READY

live_gate=blocked_human_only. live_symbols=[]. approves_live=false. approves_canary=false. approves_legacy_shutdown=false. approves_redis_trim=false.

## Phase 1 - Local resource inventory
- cpu: AMD Ryzen 9 9950X 16-Core Processor
- logical_cpus: 32 | physical_cores_observed: 16 | loadavg: [15.25, 11.62, 10.94]
- mem_total_gib: 123.38 | mem_available_gib: 71.63 | swap_total_gib: 8.0
- disk_free_gib: 669.97
- gpu: NVIDIA GeForce RTX 5080 | mem_total_mib=16303 used=2339 driver=580.126.09
- redis_used: 7.78G | redis_max: 8.00G

## Phase 2 - Local vs cloud execution map
- claude_code_terminal_local: location=local_terminal cpu=True gpu=False bottleneck=AI_MODEL_LATENCY
- claude_web_cloud_background_agents: location=anthropic_cloud cpu=False gpu=False bottleneck=TASK_WAITING_FOR_REVIEW
- codex_cli_local: location=local_terminal cpu=True gpu=False bottleneck=AI_MODEL_LATENCY
- codex_cloud_web_app: location=openai_cloud cpu=False gpu=False bottleneck=TASK_WAITING_FOR_REVIEW
- systemd_local_v2_runtime: location=local_systemd cpu=True gpu=False bottleneck=LOCAL_CPU
- python_local_batch_jobs: location=local_terminal cpu=True gpu=False bottleneck=LOCAL_CPU
- gpu_local_native_training_or_eval: location=local_gpu cpu=True gpu=True bottleneck=LOCAL_GPU
- external_cloud_api_data_feeds: location=external_cloud cpu=False gpu=False bottleneck=NETWORK

## Phase 3 - Throughput SLA
- claude_implementation_lanes_min_active_when_work_exists: 3
- codex_review_lanes_min_active_when_work_exists: 3
- replay_evaluator_jobs: continuous
- frontend_test_jobs: parallel_resource_capped
- max_writers_per_file_lock_group: 1
- codex_takeover_if_claude_task_stale: True
- max_pending_minutes_for_automatable_task: 10

## Phase 4 - Parallel lane matrix
- edge_proof_and_replay (claude): cpu=low gpu=none parallel=True locks=2
- false_negative_analysis (claude): cpu=low gpu=none parallel=True locks=1
- dataset_builder (claude): cpu=medium gpu=none parallel=True locks=1
- baseline_model_evaluator (claude): cpu=medium gpu=optional_local_gpu_for_future_models parallel=True locks=1
- full_observation_feature_work (claude): cpu=medium gpu=none parallel=True locks=2
- website_report_truth (claude): cpu=low gpu=none parallel=True locks=3
- altdata_symbol_universe (claude): cpu=medium gpu=none parallel=True locks=2
- codex_review_takeover (codex): cpu=low gpu=none parallel=True locks=2

## Phase 5 - Local speedups
- [PLANNED] pytest_xdist_for_safe_tests: Parallelize independent unit tests with pytest -n auto.
- [PLANNED] split_slow_vs_focused_tests: Tag slow tests so each war-room cycle is bounded.
- [PLANNED] vite_npm_cache_reuse: Reuse Vite/npm caches between builds.
- [PLANNED] precomputed_file_indexes: Maintain an mtime-indexed packet inventory.
- [PLANNED] redis_scan_instead_of_keys: Use SCAN over KEYS for inspection scripts.
- [PLANNED] report_center_incremental_indexing: Only re-summarize changed packets.
- [ACTIVE] replay_miner_incremental_timeline_append: Append-only timeline; no rewrite of prior history.
- [PLANNED] cpu_affinity_for_batch_jobs: Pin heavy batch builds to a subset of cores.
- [ACTIVE] avoid_stopping_v2_during_builds: Builds and tests do not require stopping daemons.
- [PLANNED] isolate_heavy_training_eval_from_runtime: V2-native baseline experiments run as subprocess jobs.

## Phase 6 - GPU usage plan
- gpu_available: True
- default_runlevel: OFF
- activation_requires: operator_explicit_decision

## Phase 7 - Cloud acceleration options
- codex_fast_mode_for_supported_models: Reduces per-turn latency on Codex review tasks.
- codex_non_interactive_exec: Scriptable parallel reviews via codex exec.
- codex_cloud_web_app_tasks: Run additional review lanes in OpenAI cloud while local CLI lanes are busy.
- claude_code_background_agents_and_routines: Recurring tasks can run as background routines.
- claude_code_local_terminal_multi_pane: Disjoint file-lock groups enable parallel lane work.
- cloud_runner_for_isolated_ci_gpu: Long-running training/evaluation can run on cloud GPU.

## Phase 8 - High-throughput scheduler design
- scheduler: V2_HIGH_THROUGHPUT_AI_WAR_ROOM_SCHEDULER
  - responsibility: keep_3_plus_claude_lanes_active_when_automatable_work_exists
  - responsibility: keep_3_plus_codex_lanes_active_when_review_work_exists
  - responsibility: enforce_file_locks
  - responsibility: monitor_stale_tasks
  - responsibility: redispatch_stale_tasks
  - responsibility: codex_takeover_safe_scoped_work
  - responsibility: stop_on_safety_drift
  - responsibility: show_utilization_dashboard
- implementation_status: DESIGN_ONLY - operator decision required before installing the scheduler daemon. The war-room utilization status and Codex governor already publish the lane-level signal the scheduler would consume.

## Phase 9 - Operator dashboard (public mirror)
- public_path: v2/frontend/public/v2_ai_throughput_acceleration/latest/operator_dashboard_payload.json
- controls_present: False
- fake_readiness: False

## Safety scoreboard
- approves_canary: False
- approves_legacy_shutdown: False
- approves_live: False
- approves_redis_trim: False
- live_gate: blocked_human_only
- live_symbols: []
- no_legacy_mutation: True
- no_raw_secret_exposure: True

## What this packet did NOT do
- Did not modify /home/wali/Desktop/AI BOT.
- Did not stop legacy or V2 runtime.
- Did not write any old Redis key.
- Did not call the exchange.
- Did not change leverage or margin mode.
- Did not enable production trading.
- Did not approve legacy shutdown or Redis trim.
- Did not expose any raw API key.
- Did not install the high-throughput scheduler daemon.
- Did not start any GPU job.
