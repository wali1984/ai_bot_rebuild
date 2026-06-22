"""Smoke + safety tests for the Phase B v2 landing routes.

All tests use an in-memory fake Redis (monkey-patched into
`app.api.v2._common.get_redis`) so they never touch a real Redis. Tests
NEVER hit a real legacy bot, exchange, trainer subprocess, or Ollama
daemon.

Coverage:
- B1 audit-ledger/summary: shape + missing-redis + stale-tail
- B2 audit-ledger/tail: shape + public RBAC denial (403)
- B3 codex/reviews/latest: shape + zero defaults
- B4 trainer/summary: stub-mode + cache + audit write + argv validator
- B5 ollama/health: shape + transport error -> ready=false
- B6 replay/status: shape + missing keys
- B7 live-readiness/gates: shape + G8 ALWAYS blocked without approval
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v2 import _common as v2_common
from app.api.v2 import audit_ledger as v2_audit_ledger
from app.api.v2 import codex_reviews as v2_codex_reviews
from app.api.v2 import ollama as v2_ollama
from app.api.v2 import public_status as v2_public_status
from app.api.v2 import trainer as v2_trainer
from app.api.v2 import replay as v2_replay
from app.api.v2.trainer import (
    TrainerArgvViolation,
    validate_trainer_argv,
)
from app.main import create_app


# --------------------------------------------------------------------- #
# Fake Redis: a dict-backed minimal subset of the redis-py API the routes
# actually use. Behavior matches `decode_responses=True`.
# --------------------------------------------------------------------- #


class _FakeStreamEntry:
    __slots__ = ("evt_id", "fields")

    def __init__(self, evt_id: str, fields: dict[str, str]) -> None:
        self.evt_id = evt_id
        self.fields = fields


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.streams: dict[str, list[_FakeStreamEntry]] = {}
        self.audit_writes: list[tuple[str, dict[str, str]]] = []
        self.set_calls: list[tuple[str, str, int | None]] = []

    # KV ----------------------------------------------------------------
    def get(self, key: str) -> str | None:
        return self.kv.get(key)

    def set(self, key: str, value: Any, ex: int | None = None) -> bool:
        self.kv[key] = value if isinstance(value, str) else json.dumps(value)
        self.set_calls.append((key, self.kv[key], ex))
        return True

    def exists(self, key: str) -> int:
        return 1 if key in self.kv or key in self.streams else 0

    # Streams -----------------------------------------------------------
    def scan_iter(self, match: str = "*", count: int = 100):
        # Very loose glob: only handles `prefix*` patterns we actually use.
        if match.endswith("*"):
            prefix = match[:-1]
            for s in list(self.streams.keys()):
                if s.startswith(prefix):
                    yield s
            for k in list(self.kv.keys()):
                if k.startswith(prefix):
                    yield k
        else:
            if match in self.streams:
                yield match
            if match in self.kv:
                yield match

    def xrevrange(self, stream: str, count: int = 1):
        entries = self.streams.get(stream, [])
        if not entries:
            return []
        tail = list(reversed(entries))[:count]
        return [(e.evt_id, dict(e.fields)) for e in tail]

    def xadd(
        self,
        stream: str,
        fields: dict[str, str],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        evt_id = f"{int(time.time() * 1000)}-{len(self.streams.get(stream, []))}"
        self.streams.setdefault(stream, []).append(_FakeStreamEntry(evt_id, fields))
        self.audit_writes.append((stream, dict(fields)))
        return evt_id

    def ping(self) -> bool:
        return True


# --------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------- #


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fr = FakeRedis()

    # Patch get_redis() everywhere it's imported.
    monkeypatch.setattr(v2_common, "get_redis", lambda: fr)
    monkeypatch.setattr(v2_audit_ledger, "get_redis", lambda: fr)
    monkeypatch.setattr(v2_codex_reviews, "get_redis", lambda: fr)
    monkeypatch.setattr(v2_trainer, "get_redis", lambda: fr)
    monkeypatch.setattr(v2_ollama, "get_redis", lambda: fr)
    monkeypatch.setattr(v2_replay, "get_redis", lambda: fr)
    monkeypatch.setattr(v2_public_status, "get_redis", lambda: fr)
    # Live-readiness route + service.
    from app.api.v2 import live_readiness as v2_live_readiness

    monkeypatch.setattr(v2_live_readiness, "get_redis", lambda: fr)

    # Reset the in-process audit-ledger TTL cache so each test sees fresh state.
    monkeypatch.setattr(
        v2_audit_ledger, "_SUMMARY_CACHE", v2_common.TtlCache(ttl_seconds=1.0)
    )
    return fr


@pytest.fixture
def no_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force get_redis() -> None to simulate Redis being unavailable."""
    monkeypatch.setattr(v2_common, "get_redis", lambda: None)
    monkeypatch.setattr(v2_audit_ledger, "get_redis", lambda: None)
    monkeypatch.setattr(v2_codex_reviews, "get_redis", lambda: None)
    monkeypatch.setattr(v2_trainer, "get_redis", lambda: None)
    monkeypatch.setattr(v2_ollama, "get_redis", lambda: None)
    monkeypatch.setattr(v2_replay, "get_redis", lambda: None)
    monkeypatch.setattr(v2_public_status, "get_redis", lambda: None)
    from app.api.v2 import live_readiness as v2_live_readiness

    monkeypatch.setattr(v2_live_readiness, "get_redis", lambda: None)
    monkeypatch.setattr(
        v2_audit_ledger, "_SUMMARY_CACHE", v2_common.TtlCache(ttl_seconds=1.0)
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


# --------------------------------------------------------------------- #
# B1: audit-ledger/summary
# --------------------------------------------------------------------- #


SUMMARY_KEYS = {"chain_ok", "tail_age_ms", "last_event_id", "last_event_ts"}


def test_b1_summary_missing_redis_returns_empty_shape(
    client: TestClient, no_redis: None
) -> None:
    res = client.get("/api/v2/audit-ledger/summary")
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == SUMMARY_KEYS
    assert body["chain_ok"] is False
    assert body["tail_age_ms"] is None
    assert body["last_event_id"] is None
    assert body["last_event_ts"] is None


def test_b1_summary_chain_ok_when_recent_entry(
    client: TestClient, fake_redis: FakeRedis
) -> None:
    ms = int(time.time() * 1000) - 500
    fake_redis.streams["audit:ledger:events"] = [
        _FakeStreamEntry(
            f"{ms}-0",
            {"source": "risk", "act": "allow", "chain_status": "ok"},
        )
    ]
    res = client.get("/api/v2/audit-ledger/summary")
    assert res.status_code == 200
    body = res.json()
    assert body["chain_ok"] is True
    assert body["last_event_id"] == f"{ms}-0"
    assert body["tail_age_ms"] is not None and body["tail_age_ms"] >= 0


def test_b1_summary_stale_tail_returns_age(
    client: TestClient, fake_redis: FakeRedis
) -> None:
    ms = int(time.time() * 1000) - 30_000
    fake_redis.streams["audit:ledger"] = [
        _FakeStreamEntry(f"{ms}-0", {"chain_status": "ok"})
    ]
    res = client.get("/api/v2/audit-ledger/summary")
    body = res.json()
    assert body["tail_age_ms"] is not None and body["tail_age_ms"] >= 25_000


def test_b1_summary_chain_broken_flag(
    client: TestClient, fake_redis: FakeRedis
) -> None:
    ms = int(time.time() * 1000)
    fake_redis.streams["audit:ledger"] = [
        _FakeStreamEntry(f"{ms}-0", {"chain_status": "broken"})
    ]
    body = client.get("/api/v2/audit-ledger/summary").json()
    assert body["chain_ok"] is False


# --------------------------------------------------------------------- #
# B2: audit-ledger/tail + RBAC
# --------------------------------------------------------------------- #


TAIL_KEYS = {
    "evt_id",
    "source",
    "act",
    "decision_id",
    "reason",
    "chain_status",
    "age_seconds",
}


def test_b2_tail_public_role_denied(client: TestClient, fake_redis: FakeRedis) -> None:
    res = client.get("/api/v2/audit-ledger/tail", headers={"X-Role": "public"})
    assert res.status_code == 403


def test_b2_tail_no_role_denied(client: TestClient, fake_redis: FakeRedis) -> None:
    # No X-Role header == public.
    res = client.get("/api/v2/audit-ledger/tail")
    assert res.status_code == 403


def test_b2_tail_observer_role_allowed(
    client: TestClient, fake_redis: FakeRedis
) -> None:
    ms = int(time.time() * 1000)
    fake_redis.streams["audit:ledger"] = [
        _FakeStreamEntry(
            f"{ms}-0",
            {
                "source": "risk",
                "act": "deny",
                "decision_id": "d123",
                "reason": "over_cap",
                "chain_status": "ok",
            },
        )
    ]
    res = client.get(
        "/api/v2/audit-ledger/tail?limit=5", headers={"X-Role": "observer"}
    )
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert set(body[0].keys()) >= TAIL_KEYS
    assert body[0]["evt_id"] == f"{ms}-0"
    assert body[0]["decision_id"] == "d123"


def test_b2_tail_missing_redis_returns_empty(
    client: TestClient, no_redis: None
) -> None:
    res = client.get("/api/v2/audit-ledger/tail", headers={"X-Role": "operator"})
    assert res.status_code == 200
    assert res.json() == []


def test_b2_tail_limit_bounded(client: TestClient, fake_redis: FakeRedis) -> None:
    # Out-of-range limit should be rejected by FastAPI's validator (422).
    res = client.get(
        "/api/v2/audit-ledger/tail?limit=500", headers={"X-Role": "observer"}
    )
    assert res.status_code == 422


# --------------------------------------------------------------------- #
# B3: codex/reviews/latest
# --------------------------------------------------------------------- #


CODEX_KEYS = {
    "open_count",
    "blocker_count",
    "last_pass_id",
    "last_fail_id",
    "last_blocker_text",
}


def test_b3_codex_defaults_when_missing(
    client: TestClient, no_redis: None, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("CODEX_REVIEW_DIR", str(tmp_path / "nope"))
    res = client.get("/api/v2/codex/reviews/latest")
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == CODEX_KEYS
    assert body["open_count"] == 0
    assert body["blocker_count"] == 0
    assert body["last_pass_id"] is None
    assert body["last_fail_id"] is None
    assert body["last_blocker_text"] is None


def test_b3_codex_reads_redis_payload(
    client: TestClient, fake_redis: FakeRedis
) -> None:
    fake_redis.kv["codex:reviews:latest"] = json.dumps(
        {
            "open_count": 3,
            "blocker_count": 1,
            "last_pass_id": "p-1",
            "last_fail_id": "f-7",
            "last_blocker_text": "fix risk gate",
        }
    )
    body = client.get("/api/v2/codex/reviews/latest").json()
    assert body["open_count"] == 3
    assert body["blocker_count"] == 1
    assert body["last_pass_id"] == "p-1"
    assert body["last_fail_id"] == "f-7"
    assert body["last_blocker_text"] == "fix risk gate"


# --------------------------------------------------------------------- #
# B4: trainer/summary  (stub mode + cache + audit + argv validator)
# --------------------------------------------------------------------- #


TRAINER_KEYS = {
    "state",
    "checkpoint_id",
    "uptime_days",
    "win_rate_30d",
    "episodes_total",
    "drift_watch_count",
    "drift_alarm_count",
    "promotion_locked",
    "promotion_min_role",
}


def test_b4_trainer_stub_mode_returns_missing_evidence(
    client: TestClient,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_MODE", "stub")
    monkeypatch.setenv("LEGACY_TRAINER_PYTHON", "/usr/bin/python3")
    monkeypatch.setenv("LEGACY_BOT_ROOT", "/tmp/legacy")
    res = client.get("/api/v2/trainer/summary")
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == TRAINER_KEYS
    assert body["state"] == "MISSING_EVIDENCE"
    # An audit event should have been appended.
    assert any(stream == "audit:trainer:reads" for stream, _ in fake_redis.audit_writes)


def test_b4_trainer_missing_env_returns_missing_evidence(
    client: TestClient,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("V2_TRAINER_MODE", raising=False)
    monkeypatch.delenv("LEGACY_TRAINER_PYTHON", raising=False)
    monkeypatch.delenv("LEGACY_BOT_ROOT", raising=False)
    body = client.get("/api/v2/trainer/summary").json()
    assert body["state"] == "MISSING_EVIDENCE"


def test_b4_trainer_cache_hit_short_circuits_subprocess(
    client: TestClient,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a cached payload exists under v2:trainer:summary, the route must
    not invoke the subprocess. We assert the subprocess function is NOT
    called by patching it to raise.
    """
    monkeypatch.delenv("V2_TRAINER_MODE", raising=False)
    monkeypatch.setenv("LEGACY_TRAINER_PYTHON", "/usr/bin/python3")
    monkeypatch.setenv("LEGACY_BOT_ROOT", "/tmp/legacy")
    cached = {
        "state": "current",
        "checkpoint_id": "ckpt-42",
        "uptime_days": 3,
        "win_rate_30d": 0.62,
        "episodes_total": 100,
        "drift_watch_count": 0,
        "drift_alarm_count": 0,
        "promotion_locked": True,
        "promotion_min_role": "trusted",
    }
    fake_redis.kv["v2:trainer:summary"] = json.dumps(cached)

    def _boom() -> dict[str, Any]:
        raise AssertionError("subprocess must not be called on cache hit")

    monkeypatch.setattr(v2_trainer, "_run_trainer_status", _boom)
    body = client.get("/api/v2/trainer/summary").json()
    assert body == cached


def test_b4_trainer_argv_validator_rejects_dangerous_flags() -> None:
    # Helper for argv: every list must contain a script path at index 1 and
    # flags from index 2 onwards.
    interp = "/usr/bin/python3"
    script = "/tmp/x/trainer_status.py"

    # Baseline: allowed.
    validate_trainer_argv([interp, script, "--mode", "status", "--json"])
    validate_trainer_argv([interp, script, "--mode=read_only", "--json"])
    validate_trainer_argv([interp, script, "--mode=export"])

    # Each of these must raise.
    forbidden_argv_sets: list[list[str]] = [
        [interp, script, "--mode", "live"],
        [interp, script, "--mode=live", "--json"],
        [interp, script, "--mode", "status", "--enable-trader"],
        [interp, script, "--mode", "status", "--write"],
        [interp, script, "--mode", "status", "--kill-switch-off"],
        [interp, script, "--mode", "status", "--margin", "cross"],
        [interp, script, "--mode", "status", "--margin=cross"],
        [interp, script, "--mode", "status", "--margin=isolated"],
        # Missing --mode entirely.
        [interp, script, "--json"],
        # Truncated argv.
        [interp, script, "--mode"],
    ]
    for argv in forbidden_argv_sets:
        with pytest.raises(TrainerArgvViolation):
            validate_trainer_argv(argv)


# --------------------------------------------------------------------- #
# B5: ollama/health
# --------------------------------------------------------------------- #


OLLAMA_KEYS = {"model", "ready", "last_draft_at"}


def test_b5_ollama_unavailable_returns_not_ready(
    client: TestClient,
    no_redis: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use a guaranteed-dead host:port so httpx.get raises immediately.
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:1")
    res = client.get("/api/v2/ollama/health")
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) >= OLLAMA_KEYS
    assert body["ready"] is False
    assert body["model"] is None


def test_b5_ollama_ready_when_httpx_returns_models(
    client: TestClient,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch httpx.get to fabricate a 200 response with a model list."""
    import httpx  # type: ignore

    class _FakeResp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"models": [{"name": "qwen2.5-coder:7b"}]}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp())
    body = client.get("/api/v2/ollama/health").json()
    assert body["ready"] is True
    assert body["model"] == "qwen2.5-coder:7b"


# --------------------------------------------------------------------- #
# B6: replay/status
# --------------------------------------------------------------------- #


REPLAY_KEYS = {"last_run", "idempotent_hash", "bounded_events_count"}


def test_b6_replay_empty_when_no_redis(client: TestClient, no_redis: None) -> None:
    body = client.get("/api/v2/replay/status").json()
    assert set(body.keys()) == REPLAY_KEYS
    for v in body.values():
        assert v is None


def test_b6_replay_reads_keys(client: TestClient, fake_redis: FakeRedis) -> None:
    fake_redis.kv["replay:last_run"] = json.dumps(
        {
            "last_run": "2026-05-18T20:00:00Z",
            "idempotent_hash": "deadbeef",
            "bounded_events_count": 42,
        }
    )
    body = client.get("/api/v2/replay/status").json()
    assert body["last_run"] == "2026-05-18T20:00:00Z"
    assert body["idempotent_hash"] == "deadbeef"
    assert body["bounded_events_count"] == 42


# --------------------------------------------------------------------- #
# B7: live-readiness/gates  (G8 ALWAYS blocked without approval)
# --------------------------------------------------------------------- #


GATE_KEYS = {"id", "name", "sub", "source_route_or_key", "state"}
GATE_IDS = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8")
ALLOWED_STATES = {"passed", "pending", "locked", "blocked"}


def _by_id(gates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {g["id"]: g for g in gates}


def test_b7_gates_shape_and_g8_blocked_no_redis(
    client: TestClient, no_redis: None
) -> None:
    res = client.get("/api/v2/live-readiness/gates")
    assert res.status_code == 200
    gates = res.json()
    assert isinstance(gates, list) and len(gates) == 8
    for g, expected_id in zip(gates, GATE_IDS):
        assert set(g.keys()) >= GATE_KEYS
        assert g["id"] == expected_id
        assert g["state"] in ALLOWED_STATES
    # **The critical assertion.**
    assert _by_id(gates)["G8"]["state"] == "blocked"


def test_b7_g8_blocked_when_approval_key_absent(
    client: TestClient, fake_redis: FakeRedis
) -> None:
    # Populate ALL the other gates' keys -- G8 still blocked because the
    # approval key was never written.
    fake_redis.kv["system_atlas:go_no_go"] = "GO"
    fake_redis.kv["trainer_atlas:status"] = "complete"
    fake_redis.kv["codex:reviews:latest"] = json.dumps(
        {"blocker_count": 0, "last_pass_id": "p-1"}
    )
    fake_redis.kv["operator:truth:supervisor"] = json.dumps(
        {"stale_or_conflicting": False}
    )
    fake_redis.kv["pnl:decomp:canary_14d"] = "true"
    fake_redis.kv["risk:envelope:stress_test_passed"] = "true"
    fake_redis.kv["build:validation:status"] = "current"

    gates = _by_id(client.get("/api/v2/live-readiness/gates").json())
    assert gates["G1"]["state"] == "passed"
    assert gates["G2"]["state"] == "passed"
    assert gates["G3"]["state"] == "passed"
    assert gates["G4"]["state"] == "passed"
    assert gates["G5"]["state"] == "passed"
    assert gates["G6"]["state"] == "passed"
    assert gates["G7"]["state"] == "passed"
    # G8 -- NO EXCEPTIONS.
    assert gates["G8"]["state"] == "blocked"


def test_b7_g8_passes_only_when_approval_key_exists(
    client: TestClient, fake_redis: FakeRedis
) -> None:
    fake_redis.kv["audit:live_enable:last_approval_id"] = "approval-xyz"
    gates = _by_id(client.get("/api/v2/live-readiness/gates").json())
    assert gates["G8"]["state"] == "passed"


def test_b7_g8_blocked_when_redis_unreachable(
    client: TestClient, no_redis: None
) -> None:
    gates = _by_id(client.get("/api/v2/live-readiness/gates").json())
    # No Redis -> we cannot prove an approval exists -> blocked.
    assert gates["G8"]["state"] == "blocked"


# --------------------------------------------------------------------- #
# C2: public-status
# --------------------------------------------------------------------- #


PUBLIC_STATUS_KEYS = {
    "live_gate_status",
    "runtime_state",
    "public_route_failed_count",
    "supervisor_health",
}


def test_c2_public_status_missing_redis_returns_safe_defaults(
    client: TestClient, no_redis: None
) -> None:
    res = client.get("/api/v2/public/status")
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == PUBLIC_STATUS_KEYS
    assert body["live_gate_status"] == "blocked_human_only"
    assert body["runtime_state"] == "MISSING_EVIDENCE"
    assert body["public_route_failed_count"] is None
    assert body["supervisor_health"] == "MISSING_EVIDENCE"


def test_c2_public_status_reads_redis_payload(
    client: TestClient, fake_redis: FakeRedis
) -> None:
    fake_redis.kv["live_readiness:gate"] = "blocked_human_only"
    fake_redis.kv["status:paper_loop"] = "PAPER_LOOP_RUNNING"
    fake_redis.kv["tonight:readiness:public_route_failed_count"] = "0"
    fake_redis.kv["operator:truth:supervisor:stale_or_conflicting"] = "0"
    res = client.get("/api/v2/public/status")
    assert res.status_code == 200
    body = res.json()
    assert body["live_gate_status"] == "blocked_human_only"
    assert body["runtime_state"] == "PAPER_LOOP_RUNNING"
    assert body["public_route_failed_count"] == 0
    assert body["supervisor_health"] == "current"


def test_c2_public_status_never_leaks_internal_ids(
    client: TestClient, fake_redis: FakeRedis
) -> None:
    # Even when many internal-only keys are populated, the public route
    # whitelist must NOT expose them.
    fake_redis.kv["paper:lineage:current:prediction_id"] = "pred_should_not_leak"
    fake_redis.kv["risk:decisions:tail_id"] = "rd_should_not_leak"
    fake_redis.kv["audit:ledger:last_event_id"] = "evt_should_not_leak"
    res = client.get("/api/v2/public/status")
    assert res.status_code == 200
    body_text = res.text
    assert "should_not_leak" not in body_text


# --------------------------------------------------------------------- #
# Cross-route safety smoke: every route returns 200 with no exceptions
# even when Redis is unavailable.
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path,headers,status_code",
    [
        ("/api/v2/audit-ledger/summary", {}, 200),
        ("/api/v2/audit-ledger/tail", {"X-Role": "observer"}, 200),
        ("/api/v2/codex/reviews/latest", {}, 200),
        ("/api/v2/trainer/summary", {}, 200),
        ("/api/v2/ollama/health", {}, 200),
        ("/api/v2/replay/status", {}, 200),
        ("/api/v2/live-readiness/gates", {}, 200),
        ("/api/v2/public/status", {}, 200),
    ],
)
def test_every_route_returns_200_when_redis_missing(
    client: TestClient,
    no_redis: None,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    headers: dict[str, str],
    status_code: int,
) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:1")
    monkeypatch.delenv("LEGACY_TRAINER_PYTHON", raising=False)
    monkeypatch.delenv("LEGACY_BOT_ROOT", raising=False)
    res = client.get(path, headers=headers)
    assert res.status_code == status_code, (path, res.text)
