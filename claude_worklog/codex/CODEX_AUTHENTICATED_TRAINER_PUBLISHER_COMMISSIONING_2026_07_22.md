# Authenticated trainer publisher commissioning evidence — 2026-07-22

## Outcome

- Service: `ai-bot-v2-native-cuda-trainer-persistent.service`
- Installed mode: `authenticated-profiled-publisher`
- Immutable code release: `7ff0e617d76bf83d6b69e6b6ec6814a3ec1b249c`
- Final tracked branch head before this evidence page:
  `a29cf7bd9a6e589a2aa9c710fa483ed688f188b7`
- Live start: `2026-07-22 18:51:19 EDT`
- Final observed process: PID `302319`, `active/running`, `NRestarts=0`
- Final observed status time: `2026-07-22T22:59:20.366089Z`
- Classification: `WAITING_EXTERNAL_WITNESS_CONFIGURATION`
- Stored/recomputed status SHA-256:
  `52cc2bec7645db2887b8421c40a76850cc2d551f4150112e8aae902d3e4376c8`
- Local roles loaded: 4
- External witness verifier loaded: 0
- Bearer/provider/exchange/order credentials loaded: 0
- Runtime/optimizer import authorized: false
- Resident Boolean result fields: 18 total, 18 false

The process is online and observable. Signed optimizer execution and
non-serving candidate publication are not complete because the independent
witness bundle is genuinely absent. No local witness, receipt or green status
was fabricated.

## Upstream state

- Coordinator PID `4074206`, `active/running`, `NRestarts=0`
- Coordinator immutable release:
  `37080a1cd015d5d51c0248f7b7e7fabbb9c24253`
- Phase: `HEAD_STAGED`
- Total/admitted examples: 18/18
- Label-unavailable count: 0
- Complete state chain verified: true
- Witness runtime configured: false
- Signed head / external full-consumption acknowledgement / optimizer
  admission: false
- All coordinator checkpoint/model/prediction/paper/live/order/execution
  authorities: false

## Acceptance counts

- Production routes: 2 explicit CLI modes
- Parser flags: 21; publisher requires 18 config values
- Credential files: 4 mandatory local roles + 1 optional public verifier key
- Public verifier environment bindings: 2
- Bearers accepted by trainer: 0
- Service status fields: 16 top-level + 30 resident-result + 10 side-effect
- Focused publisher cases after review fixes: 43 passed
- Final combined regression: 96 passed in 127.35 seconds
- Final regression warnings: 1 existing PyTorch `pynvml` deprecation warning
- Ruff: passed
- Python compilation: passed
- Git diff checks: passed
- Systemd unit parser warnings attributable to this unit: 0
- Offline systemd security exposure: 3.5, `OK`
- Live heartbeat samples retained: four over 90 seconds, plus final fresh sample
- Live PID changes/restarts during monitoring: 0/0
- Blocking production defects remaining in this slice: 0
- External prerequisites remaining: 1 independent witness bundle

## Defects found and closed

1. Arbitrary exception `.reasons` could enter public status. Closed with exact
   error-type and reason-code allowlists plus a secret-marker regression.
2. Cross-mode CLI flags could be silently ignored. Closed with explicit
   irrelevant-argument rejection in both directions.
3. A local status self-hash lacked an explicit provenance qualifier. Closed
   with `local_status_integrity_only=true` and hash coverage.
4. The installed unit still pinned the passive observer, old SHA and null
   logs. Closed with the publisher mode, immutable release, four-only
   credentials, journal logging and sandboxed read/write scopes.
5. The first real start failed before Python with `226/NAMESPACE` because the
   private status root did not yet exist when systemd assembled its mount
   namespace. Closed by running only the directory creation pre-step with `+`
   and declaring the pre-mount path optional. The next start succeeded.

## Pushed checkpoints

1. `a0c0aca90c24d01d2013335e8b5983a8c39f1ce3` — authenticated credential,
   service and CLI boundary
2. `7ff0e617d76bf83d6b69e6b6ec6814a3ec1b249c` — systemd commissioning family
3. `a288ba94c1c93345d94f9b551b3e020ea1328b31` — immutable release pin
4. `6de36d8651814a903225b3611a9557ef6dada93b` — clean-root namespace repair
5. `a29cf7bd9a6e589a2aa9c710fa483ed688f188b7` — master/operator/technical docs

All were pushed to
`origin/codex/trainer-commission-integration-20260722` and the remote head was
verified after each page family.

## Repository files changed in this commissioning slice

1. `v2/backend/app/cli/v2_native_cuda_trainer_persistent_loop.py`
2. `v2/backend/app/services/native_trainer/authenticated_profiled_resident_runtime_credentials_v1.py`
3. `v2/backend/app/services/native_trainer/authenticated_profiled_resident_service_v1.py`
4. `v2/backend/tests/unit/cli/test_v2_native_cuda_trainer_persistent_loop_waiting_mode.py`
5. `v2/backend/tests/unit/services/native_trainer/test_authenticated_profiled_resident_runtime_credentials_v1.py`
6. `v2/backend/tests/unit/services/native_trainer/test_authenticated_profiled_resident_service_v1.py`
7. `claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service`
8. `claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service.d/90-immutable-release.conf`
9. `claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.credentials.md`
10. `claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service.d/80-external-witness-verifier.conf.example`
11. `docs/MASTER_SYSTEM_DOC.md`
12. `docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md`
13. `docs/system_audit_2026_master/components/TRAINER_PPO_MASA_REPLAY_AND_CHECKPOINTS.md`
14. This evidence page.

No repository file was deleted. The worktree-local `.venv` symlink remained
untracked and was never staged.

## External deployment state changed

- Added detached, read-only worktree
  `/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/7ff0e617d76bf83d6b69e6b6ec6814a3ec1b249c`.
- Installed the committed base unit and `90-immutable-release.conf` under
  `/home/wali/.config/systemd/user`.
- Reloaded the user manager and restarted only the native trainer unit.
- Created private `0700` resident root and atomic one-link `0600` status.
- Did not install the optional witness verifier example.
- Did not restart or mutate the coordinator, paper loop, live transport, order
  transport, strategy, allocator, risk, leverage, margin or provider services.

## Commands executed

Source and deployment inspection used `git status`, `git branch`, `git log`,
`git diff`, `git rev-parse`, `git ls-remote`, `git worktree list`, `git ls-tree`,
`rg`, `sed`, `find`, `ls`, `wc`, `stat`, `readlink`, `ps`, `jq`, `systemctl
--user show/cat/status`, `journalctl --user`, and `systemd-analyze`. The exact
mutating and acceptance commands were:

```bash
/home/wali/ai_bot_local_data/deployments/python_envs/6360ea33fcfb9f9a81724989bbd32ace2b02bf7eaa7a8771d64d282f423173f0/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_authenticated_profiled_resident_runtime_credentials_v1.py

/home/wali/ai_bot_local_data/deployments/python_envs/6360ea33fcfb9f9a81724989bbd32ace2b02bf7eaa7a8771d64d282f423173f0/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_profiled_training_observation_coordinator_state_v1.py v2/backend/tests/unit/services/native_trainer/test_profiled_optimizer_external_completion_authorization_journal_v1.py v2/backend/tests/unit/services/native_trainer/test_authenticated_profiled_resident_runtime_v1.py v2/backend/tests/unit/services/native_trainer/test_authenticated_profiled_resident_runtime_credentials_v1.py v2/backend/tests/unit/services/native_trainer/test_authenticated_profiled_resident_service_v1.py v2/backend/tests/unit/cli/test_v2_native_cuda_trainer_persistent_loop_waiting_mode.py

/home/wali/ai_bot_local_data/deployments/python_envs/6360ea33fcfb9f9a81724989bbd32ace2b02bf7eaa7a8771d64d282f423173f0/bin/python -m ruff check v2/backend/app/cli/v2_native_cuda_trainer_persistent_loop.py v2/backend/app/services/native_trainer/authenticated_profiled_resident_runtime_credentials_v1.py v2/backend/app/services/native_trainer/authenticated_profiled_resident_service_v1.py v2/backend/tests/unit/cli/test_v2_native_cuda_trainer_persistent_loop_waiting_mode.py v2/backend/tests/unit/services/native_trainer/test_authenticated_profiled_resident_runtime_credentials_v1.py v2/backend/tests/unit/services/native_trainer/test_authenticated_profiled_resident_service_v1.py

/home/wali/ai_bot_local_data/deployments/python_envs/6360ea33fcfb9f9a81724989bbd32ace2b02bf7eaa7a8771d64d282f423173f0/bin/python -m py_compile v2/backend/app/cli/v2_native_cuda_trainer_persistent_loop.py v2/backend/app/services/native_trainer/authenticated_profiled_resident_runtime_credentials_v1.py v2/backend/app/services/native_trainer/authenticated_profiled_resident_service_v1.py

git diff --check
systemd-analyze --user verify claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service
systemd-analyze security --offline=yes claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service

git add v2/backend/app/cli/v2_native_cuda_trainer_persistent_loop.py v2/backend/app/services/native_trainer/authenticated_profiled_resident_runtime_credentials_v1.py v2/backend/app/services/native_trainer/authenticated_profiled_resident_service_v1.py v2/backend/tests/unit/cli/test_v2_native_cuda_trainer_persistent_loop_waiting_mode.py v2/backend/tests/unit/services/native_trainer/test_authenticated_profiled_resident_runtime_credentials_v1.py v2/backend/tests/unit/services/native_trainer/test_authenticated_profiled_resident_service_v1.py
git commit -m "Commission authenticated profiled trainer service"
git push origin codex/trainer-commission-integration-20260722

git add claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service.d/90-immutable-release.conf claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.credentials.md claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service.d/80-external-witness-verifier.conf.example v2/backend/tests/unit/cli/test_v2_native_cuda_trainer_persistent_loop_waiting_mode.py
git commit -m "Commission profiled trainer systemd boundary"
git push origin codex/trainer-commission-integration-20260722

git add claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service.d/90-immutable-release.conf v2/backend/tests/unit/cli/test_v2_native_cuda_trainer_persistent_loop_waiting_mode.py
git commit -m "Pin trainer publisher immutable release"
git push origin codex/trainer-commission-integration-20260722

git worktree add --detach /home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/7ff0e617d76bf83d6b69e6b6ec6814a3ec1b249c 7ff0e617d76bf83d6b69e6b6ec6814a3ec1b249c
chmod -R a-w /home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/7ff0e617d76bf83d6b69e6b6ec6814a3ec1b249c

install -m 0644 claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service /home/wali/.config/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service
install -m 0644 claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service.d/90-immutable-release.conf /home/wali/.config/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service.d/90-immutable-release.conf
systemctl --user daemon-reload
systemctl --user restart ai-bot-v2-native-cuda-trainer-persistent.service

systemd-run --user --wait --pipe -p ProtectSystem=strict -p 'ReadWritePaths=-/home/wali/ai_bot_local_data/v2_native_trainer/authenticated_profiled_resident_v1' -p 'ExecStartPre=+/usr/bin/install -d -m 0700 /home/wali/ai_bot_local_data/v2_native_trainer/authenticated_profiled_resident_v1' /usr/bin/test -d /home/wali/ai_bot_local_data/v2_native_trainer/authenticated_profiled_resident_v1
systemctl --user stop ai-bot-v2-native-cuda-trainer-persistent.service

git add claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service v2/backend/tests/unit/cli/test_v2_native_cuda_trainer_persistent_loop_waiting_mode.py
git commit -m "Provision trainer status root before sandboxing"
git push origin codex/trainer-commission-integration-20260722

install -m 0644 claude_worklog/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service /home/wali/.config/systemd/user/ai-bot-v2-native-cuda-trainer-persistent.service
systemctl --user daemon-reload
systemctl --user start ai-bot-v2-native-cuda-trainer-persistent.service
systemctl --user is-active ai-bot-v2-native-cuda-trainer-persistent.service

jq -cjS 'del(.status_sha256)' /home/wali/ai_bot_local_data/v2_native_trainer/authenticated_profiled_resident_v1/status.json | sha256sum
sleep 35

git add docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/components/TRAINER_PPO_MASA_REPLAY_AND_CHECKPOINTS.md
git commit -m "Document commissioned trainer publisher"
git push origin codex/trainer-commission-integration-20260722
```

Repeated `pytest`, Ruff, compilation, diff, systemd, PID/restart, status-field,
canonical-hash, unit-file `cmp`, release-cleanliness and remote-head checks were
run after each affected page. Tool polling commands did not mutate state.

## Remaining path

Operationally online is achieved. Cryptographically authorized candidate
publication has no honest calendar ETA until an external witness endpoint and
its independently controlled credentials exist. After those are supplied and
the coordinator/trainer drop-ins are reviewed, the expected mechanical path is
one coordinator cycle plus one trainer cycle (nominally within about 60
seconds), followed by at least 30–60 minutes of receipt, candidate-artifact,
restart-recovery and false-downstream-authority validation before calling the
signed publisher complete.
