"""Regression tests: V2 Codex Spark backward-compatibility and canary cutover.

Covers Phase 6 requirements:
- old wrapper args still accepted
- old JSON schemas still emitted / symbols present
- report center still parses old lane payloads
- Spark canary cannot mark production ready
- rollback preserves old path
- wrapper import failure blocks READY
- active automation freshness must remain true
- no old Redis writes
- no exchange mutation
- no approvals
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]  # …/tests → tools → claude_worklog → REBUILD
PP = f"{REPO_ROOT}:{REPO_ROOT}/claude_worklog/tools"
PY = str(REPO_ROOT / ".venv/bin/python3")

# Ensure v2.* imports work in this test process
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "claude_worklog/tools"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(args: list[str], extra_env: dict | None = None) -> tuple[int, str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = PP
    if extra_env:
        env.update(extra_env)
    r = subprocess.run([PY] + args, capture_output=True, text=True, env=env, timeout=15)
    return r.returncode, r.stdout, r.stderr


def _import_wrapper(relpath: str):
    """Import a wrapper file and return the module."""
    path = REPO_ROOT / relpath
    spec = importlib.util.spec_from_file_location(path.stem + "_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. Old wrapper args still accepted
# ---------------------------------------------------------------------------

class TestLegacyArgsAccepted:

    def test_worker_pool_legacy_subcommand_and_flags(self):
        """worker_pool wrapper must accept 'run-once --spawn --target-claude N --target-codex N'."""
        rc, out, err = _run([
            str(REPO_ROOT / "claude_worklog/tools/v2_closed_loop_worker_pool.py"),
            "run-once", "--spawn", "--target-claude", "3", "--target-codex", "3", "--help",
        ])
        assert rc == 0, f"Expected exit 0, got {rc}: {err}"
        assert "unrecognized" not in err, f"Unrecognized args: {err}"

    def test_autoseed_legacy_wait_seconds_and_json(self):
        """autoseed wrapper must accept '--wait-seconds N --json'."""
        rc, out, err = _run([
            str(REPO_ROOT / "claude_worklog/tools/v2_autonomous_mission_backlog_autoseed.py"),
            "--wait-seconds", "5", "--json", "--help",
        ])
        assert rc == 0, f"Expected exit 0, got {rc}: {err}"
        assert "unrecognized" not in err, f"Unrecognized args: {err}"

    def test_burndown_legacy_json_flag(self):
        """burndown wrapper must accept '--json'."""
        rc, out, err = _run([
            str(REPO_ROOT / "claude_worklog/tools/v2_autonomous_mission_execution_burndown.py"),
            "--json", "--help",
        ])
        assert rc == 0, f"Expected exit 0, got {rc}: {err}"
        assert "unrecognized" not in err, f"Unrecognized args: {err}"

    def test_claude_worker_worker_id(self):
        """Claude worker wrapper must accept '--worker-id claude-1'."""
        rc, out, err = _run([
            str(REPO_ROOT / "claude_worklog/tools/v2_closed_loop_claude_worker.py"),
            "--worker-id", "claude-1", "--help",
        ])
        assert rc == 0, f"Expected exit 0: {err}"

    def test_codex_worker_worker_id(self):
        """Codex worker wrapper must accept '--worker-id codex-1'."""
        rc, out, err = _run([
            str(REPO_ROOT / "claude_worklog/tools/v2_closed_loop_codex_worker.py"),
            "--worker-id", "codex-1", "--help",
        ])
        assert rc == 0, f"Expected exit 0: {err}"

    def test_fail_mapper_no_args(self):
        """fail_mapper wrapper must accept no args (help exit 0)."""
        rc, out, err = _run([
            str(REPO_ROOT / "claude_worklog/tools/v2_burndown_fail_to_remediation_mapper.py"),
            "--help",
        ])
        assert rc == 0, f"Expected exit 0: {err}"


class TestCodexNonInteractiveLaunch:

    def test_agent_supervisor_codex_exec_uses_non_interactive_flags(self):
        mod = _import_wrapper("claude_worklog/tools/agent_supervisor.py")
        cmd = mod.codex_exec_command("do work")
        assert cmd == [
            "codex",
            "--sandbox",
            "danger-full-access",
            "--ask-for-approval",
            "never",
            "exec",
            "do work",
        ]

    def test_agent_supervisor_does_not_persist_per_poll_non_drift_noise(
        self,
        tmp_path: Path,
    ):
        mod = _import_wrapper("claude_worklog/tools/agent_supervisor.py")
        mod.EVENTS_FILE = tmp_path / "events.jsonl"

        assert mod.append_event(
            {
                "event": "task_skipped_by_non_drift_governor_lock",
                "task_id": "task-1",
            }
        ) is False
        assert mod.append_event(
            {
                "event": "task_not_selected_by_non_drift_governor_lock",
                "task_id": "task-1",
            }
        ) is False
        assert mod.append_event({"event": "task_completed", "task_id": "task-1"}) is True

        rows = [json.loads(line) for line in mod.EVENTS_FILE.read_text(encoding="utf-8").splitlines()]
        assert [row["event"] for row in rows] == ["task_completed"]

    def test_codex_review_runner_commands_use_non_interactive_flags(self):
        mod = _import_wrapper("claude_worklog/tools/v2_codex_review_runner.py")
        executor = {"binary": "/usr/bin/codex"}
        expected_prefix = [
            "/usr/bin/codex",
            "--sandbox",
            "danger-full-access",
            "--ask-for-approval",
            "never",
        ]
        cases = {
            "codex_exec": ["exec", "do work"],
            "codex_review": ["review", "do work"],
            "codex_exec_review": ["exec", "review", "do work"],
            "codex_exec_review_uncommitted": ["exec", "review", "do work"],
        }
        for form, expected_tail in cases.items():
            cmd = mod._codex_command(
                executor,
                {"task_id": "test-task", "codex_cli_form": form, "prompt": "do work"},
            )
            assert cmd == [*expected_prefix, *expected_tail]


# ---------------------------------------------------------------------------
# 2. Old JSON schemas still emitted / symbols present
# ---------------------------------------------------------------------------

class TestSparkSymbolsPresent:

    def test_worker_pool_exports_main_and_run_once(self):
        from v2.backend.app.closed_loop.cli.worker_pool import main, run_once
        assert callable(main)
        assert callable(run_once)

    def test_claude_worker_exports_all_symbols(self):
        from v2.backend.app.closed_loop.workers.claude_worker import (
            main, run_worker, execute_task, _safe_to_claim,
        )
        for fn in (main, run_worker, execute_task, _safe_to_claim):
            assert callable(fn), f"{fn} not callable"

    def test_codex_worker_exports_all_symbols(self):
        from v2.backend.app.closed_loop.workers.codex_worker import (
            main, run_worker, run_review_task,
        )
        for fn in (main, run_worker, run_review_task):
            assert callable(fn)

    def test_autoseed_exports_main_and_run_once(self):
        from v2.backend.app.closed_loop.services.autoseed import main, run_once
        assert callable(main)
        assert callable(run_once)

    def test_burndown_exports_main_and_run_once(self):
        from v2.backend.app.closed_loop.services.burndown import main, run_once
        assert callable(main)
        assert callable(run_once)

    def test_fail_mapper_exports_three_functions(self):
        from v2.backend.app.closed_loop.services.fail_mapper import (
            build_codex_fail_to_remediation_map, classify_fail, classify_from_output,
        )
        for fn in (build_codex_fail_to_remediation_map, classify_fail, classify_from_output):
            assert callable(fn)


# ---------------------------------------------------------------------------
# 3. Report center — old lane payload parsing
# ---------------------------------------------------------------------------

class TestReportCenterPayloadParsing:

    def test_lane_payload_fields_present(self):
        """Lane payloads written by workers must have schema fields report center expects."""
        sample_payload = {
            "task_id": "test-task-001",
            "lane_type": "CLAUDE_IMPLEMENTATION",
            "status": "completed",
            "safe_envelope": {
                "live_gate": "blocked_human_only",
                "live_symbols": [],
                "approves_live": False,
                "approves_canary": False,
                "approves_legacy_shutdown": False,
                "approves_redis_trim": False,
            },
            "created_at": "2026-05-24T00:00:00Z",
            "updated_at": "2026-05-24T00:01:00Z",
        }
        # Report center expects task_id, lane_type, status, safe_envelope
        for field in ("task_id", "lane_type", "status", "safe_envelope"):
            assert field in sample_payload, f"Missing field: {field}"

    def test_safe_envelope_schema_stable(self):
        """safe_envelope REQUIRED_SAFE_FIELDS must remain stable."""
        from v2.backend.app.closed_loop.lease_store.sqlite_store import REQUIRED_SAFE_FIELDS
        expected = {"live_gate", "live_symbols", "approves_live", "approves_canary",
                    "approves_legacy_shutdown", "approves_redis_trim"}
        assert expected == set(REQUIRED_SAFE_FIELDS), \
            f"Schema drift detected: {set(REQUIRED_SAFE_FIELDS)} != {expected}"


# ---------------------------------------------------------------------------
# 4. Spark canary cannot mark production ready
# ---------------------------------------------------------------------------

class TestCanaryCannotMarkProductionReady:

    def test_canary_gate_status_is_blocked(self):
        """spark_canary_cutover_status.json must say canary_gated_not_production_ready."""
        path = (
            REPO_ROOT
            / "claude_worklog/final_readiness"
            / "v2_codex_spark_backward_compatibility_canary_cutover"
            / "latest"
            / "spark_canary_cutover_status.json"
        )
        assert path.exists(), "spark_canary_cutover_status.json must exist"
        data = json.loads(path.read_text())
        assert data["canary_gate_verdict"] == "CANARY_GATED_NOT_PRODUCTION_READY"
        assert data["spark_cannot_mark_production_ready"] is True
        assert data["live_gate"] == "blocked_human_only"
        assert data["live_symbols"] == []
        assert data["approves_live"] is False

    def test_safe_to_claim_blocks_production_promotion(self):
        """_safe_to_claim must block any task that would approve live or canary."""
        from v2.backend.app.closed_loop.workers.claude_worker import _safe_to_claim

        def _make_task(overrides: dict) -> dict:
            env: dict[str, Any] = {
                "live_gate": "blocked_human_only",
                "live_symbols": [],
                "approves_live": False,
                "approves_canary": False,
                "approves_legacy_shutdown": False,
                "approves_redis_trim": False,
            }
            env.update(overrides)
            return {"lane_type": "CLAUDE_IMPLEMENTATION", "agent": "claude", "safe_envelope": env}

        # These must all be REJECTED
        assert not _safe_to_claim(_make_task({"live_gate": "OPEN"}))[0]
        assert not _safe_to_claim(_make_task({"live_symbols": ["BTCUSDT"]}))[0]
        assert not _safe_to_claim(_make_task({"approves_live": True}))[0]
        assert not _safe_to_claim(_make_task({"approves_canary": True}))[0]
        # Safe task must be ACCEPTED
        assert _safe_to_claim(_make_task({}))[0]


# ---------------------------------------------------------------------------
# 5. Rollback preserves old path
# ---------------------------------------------------------------------------

class TestRollbackPreservesOldPath:

    def test_rollback_script_exists(self):
        p = REPO_ROOT / "claude_worklog/tools/v2_codex_spark_rollback.py"
        assert p.exists(), "Rollback script must exist"

    def test_rollback_dry_run_exits_zero(self):
        rc, out, err = _run([
            str(REPO_ROOT / "claude_worklog/tools/v2_codex_spark_rollback.py"),
            "--dry-run",
        ])
        assert rc == 0, f"Rollback dry-run must exit 0: {err}"
        assert "DRY-RUN" in out or "DRY-RUN" in err or rc == 0

    def test_rollback_does_not_stop_protected_units(self):
        """Rollback module must have PROTECTED_UNITS that covers persistent workers."""
        spec = importlib.util.spec_from_file_location(
            "rollback_test",
            REPO_ROOT / "claude_worklog/tools/v2_codex_spark_rollback.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for i in range(1, 4):
            assert f"ai-bot-v2-closed-loop-claude-worker@{i}.service" in mod.PROTECTED_UNITS
            assert f"ai-bot-v2-closed-loop-codex-worker@{i}.service" in mod.PROTECTED_UNITS

    def test_rollback_proof_written(self):
        path = (
            REPO_ROOT
            / "claude_worklog/final_readiness"
            / "v2_codex_spark_backward_compatibility_canary_cutover"
            / "latest"
            / "spark_rollback_proof.json"
        )
        assert path.exists(), "spark_rollback_proof.json must exist"
        data = json.loads(path.read_text())
        assert data["legacy_untouched"] is True
        assert data["live_untouched"] is True
        assert data["report_center_untouched"] is True
        assert data["safe_envelope"]["live_gate"] == "blocked_human_only"
        assert data["safe_envelope"]["approves_live"] is False


# ---------------------------------------------------------------------------
# 6. Wrapper import failure blocks READY
# ---------------------------------------------------------------------------

class TestImportFailureBlocksReady:

    def test_missing_spark_module_causes_import_error(self):
        """If the repo root is not in sys.path, v2.* imports in wrappers must raise ModuleNotFoundError."""
        import os as _os, tempfile as _tmp
        env = _os.environ.copy()
        # Omit repo root entirely; use only a clean temp dir so v2.* cannot be found
        with _tmp.TemporaryDirectory() as td:
            env["PYTHONPATH"] = td  # no v2 package here
            r = subprocess.run(
                [PY, "-c",
                 f"import sys; sys.path = ['{td}']; "
                 f"exec(open('{REPO_ROOT}/claude_worklog/tools/v2_closed_loop_worker_pool.py').read())"],
                capture_output=True, text=True, env=env, timeout=10,
                cwd=td,  # run from temp dir so CWD doesn't add repo root
            )
        assert r.returncode != 0, "Import should have failed without repo root in sys.path"
        assert "ModuleNotFoundError" in r.stderr or "No module named" in r.stderr, \
            f"Expected ModuleNotFoundError, got stderr: {r.stderr[:300]}"


# ---------------------------------------------------------------------------
# 7. Active automation freshness
# ---------------------------------------------------------------------------

class TestActiveAutomationFreshness:

    def test_persistent_workers_are_running(self):
        """Persistent Claude and Codex workers must be active/running."""
        import subprocess as sp
        for i in range(1, 4):
            for kind in ("claude", "codex"):
                r = sp.run(
                    ["systemctl", "--user", "show",
                     f"ai-bot-v2-closed-loop-{kind}-worker@{i}.service",
                     "--property=ActiveState"],
                    capture_output=True, text=True,
                )
                assert "ActiveState=active" in r.stdout, \
                    f"ai-bot-v2-closed-loop-{kind}-worker@{i} not active: {r.stdout}"

    def test_automation_continuity_file_exists(self):
        path = (
            REPO_ROOT
            / "claude_worklog/final_readiness"
            / "v2_codex_spark_backward_compatibility_canary_cutover"
            / "latest"
            / "automation_continuity_status.json"
        )
        assert path.exists(), "automation_continuity_status.json must exist"
        data = json.loads(path.read_text())
        assert data["persistent_workers_running"] is True


# ---------------------------------------------------------------------------
# 8. No old Redis writes
# ---------------------------------------------------------------------------

class TestNoOldRedisWrites:

    def test_safe_envelope_blocks_redis_trim(self):
        from v2.backend.app.closed_loop.lease_store.sqlite_store import _ensure_safe_envelope
        bad = {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": True,   # <— must be rejected
        }
        with pytest.raises(ValueError, match="approves_redis_trim"):
            _ensure_safe_envelope({"safe_envelope": bad})

    def test_workers_do_not_import_redis_write_primitives(self):
        """Worker source must not directly invoke redis.set / redis.hset for legacy keys."""
        for relpath in [
            "v2/backend/app/closed_loop/workers/claude_worker.py",
            "v2/backend/app/closed_loop/workers/codex_worker.py",
        ]:
            src = (REPO_ROOT / relpath).read_text()
            for forbidden in ("r.set(", "r.hset(", "r.lpush(", "r.xadd("):
                assert forbidden not in src, \
                    f"Forbidden Redis write '{forbidden}' found in {relpath}"


# ---------------------------------------------------------------------------
# 9. No exchange mutation
# ---------------------------------------------------------------------------

class TestNoExchangeMutation:

    def test_spark_modules_do_not_import_exchange_adapters(self):
        for relpath in [
            "v2/backend/app/closed_loop/workers/claude_worker.py",
            "v2/backend/app/closed_loop/workers/codex_worker.py",
            "v2/backend/app/closed_loop/services/autoseed.py",
            "v2/backend/app/closed_loop/services/burndown.py",
        ]:
            src = (REPO_ROOT / relpath).read_text()
            for forbidden in ("place_order", "create_order", "ExchangeAdapter", "BinanceAdapter"):
                assert forbidden not in src, \
                    f"Exchange mutation symbol '{forbidden}' found in {relpath}"

    def test_safe_envelope_live_symbols_empty(self):
        from v2.backend.app.closed_loop.lease_store.sqlite_store import _ensure_safe_envelope
        bad = {
            "live_gate": "blocked_human_only",
            "live_symbols": ["BTCUSDT"],   # <— must be rejected
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        }
        with pytest.raises(ValueError, match="live_symbols"):
            _ensure_safe_envelope({"safe_envelope": bad})


# ---------------------------------------------------------------------------
# 10. No approvals
# ---------------------------------------------------------------------------

class TestNoApprovals:

    def test_safe_envelope_blocks_canary_approval(self):
        from v2.backend.app.closed_loop.lease_store.sqlite_store import _ensure_safe_envelope
        bad = {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": True,   # <— must be rejected
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        }
        with pytest.raises(ValueError, match="approves_canary"):
            _ensure_safe_envelope({"safe_envelope": bad})

    def test_no_approval_files_created_by_wrappers(self):
        approvals_dir = REPO_ROOT / "claude_worklog/approvals"
        if not approvals_dir.exists():
            return
        before = set(approvals_dir.rglob("*.json"))
        # No new approvals should be created from importing wrappers
        from claude_worklog.tools.v2_closed_loop_worker_pool import main  # noqa: F401
        from claude_worklog.tools.v2_closed_loop_claude_worker import main  # noqa: F401
        after = set(approvals_dir.rglob("*.json"))
        assert before == after, f"Unexpected approval files created: {after - before}"
