"""Tests for the V2 legacy log intelligence observer."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]


def test_typo_tolerance_resolves_close_match(tmp_path, monkeypatch) -> None:
    from v2.backend.app.services.legacy_log_intelligence import service as svc

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "hybrid_trainer.log").write_text("ok")
    monkeypatch.setattr(svc, "LEGACY_BOT_ROOT", tmp_path, raising=True)
    monkeypatch.setattr(svc, "LEGACY_LOGS_DIR", logs, raising=True)
    monkeypatch.setattr(svc, "LEGACY_SCRIPTS_DIR", tmp_path / "scripts", raising=True)
    resolved, hint = svc._resolve_with_typo_tolerance("logs/hybrid_traimer.log")
    assert resolved is not None
    assert resolved.name == "hybrid_trainer.log"


def test_typo_tolerance_missing_returns_missing_path(tmp_path, monkeypatch) -> None:
    from v2.backend.app.services.legacy_log_intelligence import service as svc

    monkeypatch.setattr(svc, "LEGACY_BOT_ROOT", tmp_path)
    monkeypatch.setattr(svc, "LEGACY_LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(svc, "LEGACY_SCRIPTS_DIR", tmp_path / "scripts")
    resolved, hint = svc._resolve_with_typo_tolerance("logs/something_that_does_not_exist.log")
    assert resolved is None
    assert hint == "MISSING_PATH"


def test_read_tail_returns_only_new_bytes(tmp_path, monkeypatch) -> None:
    from v2.backend.app.services.legacy_log_intelligence import service as svc
    monkeypatch.setattr(svc, "OFFSET_DIR", tmp_path / "offsets")
    log = tmp_path / "demo.log"
    log.write_text("alpha\nbeta\n")
    data1, off1 = svc._read_tail(log, 0)
    assert b"alpha" in data1
    log.write_text("alpha\nbeta\ngamma\n")
    data2, _ = svc._read_tail(log, off1)
    assert b"gamma" in data2


def test_trainer_parser_extracts_action(tmp_path) -> None:
    from v2.backend.app.services.legacy_log_intelligence import service as svc
    log = tmp_path / "hybrid_trainer.log"
    log.write_text(
        "INFO prediction: BTCUSDT 5m action=close_short_open_long confidence=0.71\n"
    )
    out = svc.parse_trainer_log_tail(log, 0)
    assert out["latest_trainer_action_by_symbol"].get("BTCUSDT") == "close_short_open_long"
    assert out["latest_trainer_confidence_by_symbol"].get("BTCUSDT") == 0.71


def test_orchestrator_parser_extracts_block_reasons(tmp_path) -> None:
    from v2.backend.app.services.legacy_log_intelligence import service as svc
    log = tmp_path / "orchestrator_worker.log"
    log.write_text("duplicate proposal rejected\ndeconflict ALL_SIGNALS_AGREE\n")
    out = svc.parse_orchestrator_log_tail(log, 0)
    assert "duplicate_reject" in out["latest_orchestrator_block_reasons"]
    assert "deconflict" in out["latest_orchestrator_block_reasons"]


def test_inspect_monitor_script(tmp_path) -> None:
    from v2.backend.app.services.legacy_log_intelligence import service as svc
    script = tmp_path / "monitor_signals.py"
    script.write_text("import redis\nr=redis.Redis()\nr.get('signals:trading:asjad')\n")
    info = svc.inspect_monitor_script(script)
    assert info["exists"] is True
    assert "signals:trading:asjad" in info["redis_keys_read"]


def test_enrich_classifies_v2_hold() -> None:
    from v2.backend.app.services.legacy_log_intelligence import service as svc
    obs = {"trainer_log_summary": {"latest_trainer_action_by_symbol": {"BTCUSDT": "x"}},
            "orchestrator_log_summary": {"latest_orchestrator_block_reasons": []}}
    cmp_payload = {"per_symbol": [{
        "symbol": "BTCUSDT", "match": False,
        "legacy": {"exists": True, "action": "close_short_open_long",
                    "feature_freshness_state": "CURRENT"},
        "v2": {"exists": True, "selected_action": "hold", "paper_fill_allowed": False,
                "paper_fill_gate_block_reasons": ["NEG"], "feature_freshness_state": "CURRENT"},
    }]}
    enriched = svc.enrich_comparison(obs, cmp_payload)
    causes = enriched["per_symbol"][0]["mismatch_causes_classified"]
    assert "V2_hold_due_strict_gate" in causes
    assert "checkpoint_weight_missing" in causes
