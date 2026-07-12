"""WI-3 confidence-calibration (temperature scaling) unit tests."""
from __future__ import annotations

import json
import math

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import confidence as conf
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    DEFAULT_CONFIDENCE_TEMPERATURE,
    expected_calibration_error,
    fit_temperature,
    resolve_confidence_temperature,
)


def _overconfident_dataset(n: int = 400):
    """Model says ~0.9 confident but is only right ~55% of the time (overconfident)."""
    raw, wins = [], []
    for i in range(n):
        raw.append(0.9)
        wins.append(1 if i % 20 < 11 else 0)  # 55% win rate
    return raw, wins


def test_fit_temperature_spreads_overconfident_probs() -> None:
    raw, wins = _overconfident_dataset()
    fit = fit_temperature(raw, wins)
    assert fit["fitted"] is True
    # Overconfident -> fitted T must be > 1 (pushes 0.9 down toward the true 0.55).
    assert fit["temperature"] > 1.0
    # Calibration error must improve vs the fixed default.
    assert fit["ece_after"] <= fit["ece_before"] + 1e-9


def test_fit_temperature_refuses_small_sample() -> None:
    fit = fit_temperature([0.9] * 10, [1] * 10)
    assert fit["fitted"] is False
    assert fit["reason"] == "INSUFFICIENT_OUTCOME_SAMPLE"
    assert fit["temperature"] == DEFAULT_CONFIDENCE_TEMPERATURE


def test_ece_lower_after_good_temperature() -> None:
    raw, wins = _overconfident_dataset()
    fit = fit_temperature(raw, wins)
    ece_default = expected_calibration_error(raw, wins, DEFAULT_CONFIDENCE_TEMPERATURE)
    ece_fitted = expected_calibration_error(raw, wins, fit["temperature"])
    assert ece_fitted <= ece_default + 1e-9


def test_resolve_temperature_reads_state_then_falls_back(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("V2_TRAINER_CONFIDENCE_TEMPERATURE", raising=False)
    state = tmp_path / "confidence_temperature.json"
    monkeypatch.setattr(conf, "CONFIDENCE_TEMPERATURE_STATE_PATH", state)
    conf._TEMPERATURE_CACHE.update({"mtime": None, "value": None})
    # No file -> default.
    assert resolve_confidence_temperature() == DEFAULT_CONFIDENCE_TEMPERATURE
    # File present -> fitted value used.
    state.write_text(json.dumps({"temperature": 2.3}))
    assert math.isclose(resolve_confidence_temperature(), 2.3, rel_tol=1e-6)


def test_resolve_temperature_env_override(monkeypatch) -> None:
    monkeypatch.setenv("V2_TRAINER_CONFIDENCE_TEMPERATURE", "1.9")
    assert math.isclose(resolve_confidence_temperature(), 1.9, rel_tol=1e-6)


def test_disabled_path_is_default() -> None:
    # With no env and no state, the model's calibration is byte-identical to the
    # historical fixed-temperature behaviour.
    import os

    os.environ.pop("V2_TRAINER_CONFIDENCE_TEMPERATURE", None)
    conf._TEMPERATURE_CACHE.update({"mtime": None, "value": None})
    # Point at a definitely-missing path.
    conf.CONFIDENCE_TEMPERATURE_STATE_PATH = conf.Path("/nonexistent/confidence_temperature.json")
    assert resolve_confidence_temperature() == DEFAULT_CONFIDENCE_TEMPERATURE
