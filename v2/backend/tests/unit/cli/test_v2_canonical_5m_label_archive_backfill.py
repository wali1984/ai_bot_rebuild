from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from v2.backend.app.cli import v2_canonical_5m_label_archive_backfill as cli

START_UTC = "2023-11-14T22:10:00Z"
END_UTC = "2023-11-14T22:20:00Z"
NOW_MS = 1_700_000_100_000


def _base_args(tmp_path: Path) -> list[str]:
    return [
        "--symbols",
        "BTCUSDT,ETHUSDT",
        "--start-utc",
        START_UTC,
        "--end-utc",
        END_UTC,
        "--authority-cutoff-utc",
        END_UTC,
        "--archive-path",
        str(tmp_path / "labels.sqlite3"),
        "--state-path",
        str(tmp_path / "backfill.sqlite3"),
    ]


def _write_attestation(tmp_path: Path) -> Path:
    archive_path = (tmp_path / "labels.sqlite3").resolve()
    cutoff_ms = cli._parse_utc_boundary(END_UTC)
    path = tmp_path / "wss-inactive-attestation.json"
    path.write_text(
        json.dumps(
            {
                "attestation_id": "operator-fixed-cutoff-cli-test",
                "archive_path": str(archive_path),
                "authority_cutoff_open_time_ms": cutoff_ms,
                "attested_at_ms": NOW_MS - 1_000,
                "valid_until_ms": NOW_MS + 60_000,
                "producer_worker_id": "v2_binance_kline_wss_loop",
                "producer_archive_writes_inactive": True,
                "operator_authorized": True,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_default_cli_is_no_write_no_network_plan(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    code = cli.main(_base_args(tmp_path))

    assert code == 0
    assert not (tmp_path / "labels.sqlite3").exists()
    assert not (tmp_path / "backfill.sqlite3").exists()
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == "canonical_5m_historical_backfill_plan_v2"
    assert report["status"] == "PLAN_ONLY_EXPLICIT_PUBLIC_REST_OPT_IN_REQUIRED"
    assert report["network_requests_made"] == 0
    assert report["archive_mutated"] is False
    assert report["credentials_used"] is False
    assert report["orders_or_account_mutations"] is False
    assert report["job"]["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert (
        report["job"]["authority_cutoff_open_time_ms"]
        == report["job"]["end_open_time_ms_exclusive"]
    )
    assert (
        "--wss-inactive-attestation=<operator-provided JSON authorization>"
        in report["required_execution_controls"]
    )
    assert report["run_bounds"] == {
        "max_pages": 4,
        "max_slots": 4_000,
        "local_weight_budget_per_utc_minute": 120,
        "max_request_weight_per_run": 120,
        "immutable_local_weight_per_utc_minute_ceiling": 120,
        "immutable_request_weight_per_run_ceiling": 120,
    }


@pytest.mark.parametrize(
    ("flag", "error"),
    (
        ("--local-weight-budget-per-minute", "backfill_weight_budget_invalid"),
        ("--max-request-weight-per-run", "backfill_run_request_weight_invalid"),
    ),
)
def test_cli_refuses_request_weight_above_immutable_ceiling(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    flag: str,
    error: str,
) -> None:
    code = cli.main([*_base_args(tmp_path), flag, "121"])

    assert code == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "BLOCKED_FAIL_CLOSED"
    assert report["error"] == error
    assert not (tmp_path / "backfill.sqlite3").exists()


def test_cli_refuses_mismatched_fixed_cutoff_without_writes(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    args = _base_args(tmp_path)
    cutoff_index = args.index("--authority-cutoff-utc") + 1
    args[cutoff_index] = "2023-11-14T22:25:00Z"

    code = cli.main(args)

    assert code == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "BLOCKED_FAIL_CLOSED"
    assert report["error"] == "authority_cutoff_must_exactly_equal_end_utc"
    assert not (tmp_path / "backfill.sqlite3").exists()


def test_cli_execution_requires_operator_attestation_file(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    code = cli.main([*_base_args(tmp_path), "--execute-public-rest"])

    assert code == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "BLOCKED_FAIL_CLOSED"
    assert report["error"] == "execute_requires_wss_inactive_attestation_file"
    assert not (tmp_path / "backfill.sqlite3").exists()


def test_cli_execution_wires_valid_attestation_and_runtime_probe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    attestation_path = _write_attestation(tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr(cli, "_clock_ms", lambda: NOW_MS)
    monkeypatch.setattr(
        cli,
        "_wss_archive_producer_inactive_probe",
        lambda *, archive_path: {
            "probe_method": "fake_cli_proc_probe_v1",
            "producer_worker_id": "v2_binance_kline_wss_loop",
            "archive_path": str(Path(archive_path).resolve()),
            "observed_at_ms": NOW_MS,
            "active_process_ids": [],
            "wss_archive_producer_inactive": True,
            "process_probe_role": "SECONDARY_EVIDENCE_ONLY",
            "shared_exact_archive_writer_lease_is_primary": True,
        },
    )

    def _fake_run(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        probe = kwargs["wss_inactive_probe"]
        assert callable(probe)
        captured["probe_receipt"] = probe()
        return {
            "job_complete": False,
            "paused": False,
            "credentials_used": False,
            "orders_or_account_mutations": False,
            "wss_activation_performed": False,
        }

    monkeypatch.setattr(cli, "run_historical_5m_backfill", _fake_run)

    code = cli.main(
        [
            *_base_args(tmp_path),
            "--execute-public-rest",
            "--wss-inactive-attestation",
            str(attestation_path),
        ]
    )

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "BOUNDED_SLICE_COMPLETE_RESUME_REQUIRED"
    assert report["job"]["authority_cutoff"]["operator_authorized"] is True
    assert report["job"]["authority_cutoff"]["cryptographic_authentication_claimed"] is False
    spec = captured["spec"]
    assert spec.authority_cutoff.attestation_id == "operator-fixed-cutoff-cli-test"
    assert captured["probe_receipt"]["active_process_ids"] == []


def test_cli_rejects_expired_or_extra_field_attestation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    path = _write_attestation(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(cli, "_clock_ms", lambda: NOW_MS)

    code = cli.main(
        [
            *_base_args(tmp_path),
            "--execute-public-rest",
            "--wss-inactive-attestation",
            str(path),
        ]
    )

    assert code == 2
    report = json.loads(capsys.readouterr().out)
    assert report["error"] == ("wss_inactive_attestation_fields_missing_or_unexpected")


def test_cli_runtime_probe_ignores_market_only_and_binds_enabled_exact_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proc = tmp_path / "proc"
    (proc / "100").mkdir(parents=True)
    archive_path = (tmp_path / "labels.sqlite3").resolve()
    other_archive_path = (tmp_path / "different.sqlite3").resolve()
    (proc / "100" / "cmdline").write_bytes(b"python\x00v2_binance_kline_wss_loop.py\x00")
    (proc / "101").mkdir()
    (proc / "101" / "cmdline").write_bytes(
        b"python\x00v2_binance_kline_wss_loop.py\x00"
        b"--enable-canonical-5m-label-archive\x00"
        b"--canonical-5m-label-archive-path\x00" + str(archive_path).encode() + b"\x00"
    )
    (proc / "102").mkdir()
    (proc / "102" / "cmdline").write_bytes(
        b"python\x00v2_binance_kline_wss_loop.py\x00"
        b"--enable-canonical-5m-label-archive\x00"
        b"--canonical-5m-label-archive-path=" + str(other_archive_path).encode() + b"\x00"
    )
    original_path = cli.Path

    def _fake_path(value: object) -> Path:
        if value == "/proc":
            return proc
        return original_path(value)

    monkeypatch.setattr(cli, "Path", _fake_path)
    monkeypatch.setattr(cli, "_clock_ms", lambda: NOW_MS)

    proof = cli._wss_archive_producer_inactive_probe(archive_path=archive_path)

    assert proof["active_process_ids"] == [101]
    assert proof["wss_archive_producer_inactive"] is False
    assert proof["process_probe_role"] == "SECONDARY_EVIDENCE_ONLY"
    assert proof["shared_exact_archive_writer_lease_is_primary"] is True
    assert proof["enabled_writer_processes_other_archive"] == [
        {"process_id": 102, "archive_path": str(other_archive_path)}
    ]


def test_cli_runtime_probe_fails_closed_on_malformed_enabled_path_args(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proc = tmp_path / "proc"
    (proc / "100").mkdir(parents=True)
    (proc / "100" / "cmdline").write_bytes(
        b"python\x00v2_binance_kline_wss_loop.py\x00"
        b"--enable-canonical-5m-label-archive\x00"
        b"--canonical-5m-label-archive-path\x00"
    )
    original_path = cli.Path

    def _fake_path(value: object) -> Path:
        if value == "/proc":
            return proc
        return original_path(value)

    monkeypatch.setattr(cli, "Path", _fake_path)

    with pytest.raises(
        cli.Historical5mBackfillError,
        match="enabled_archive_path_arg_malformed",
    ):
        cli._wss_archive_producer_inactive_probe(archive_path=tmp_path / "labels.sqlite3")


@pytest.mark.parametrize(
    "protected_name",
    (
        "labels.sqlite3",
        "labels.sqlite3-wal",
        "labels.sqlite3-shm",
        "labels.sqlite3-journal",
        "labels.sqlite3.writer.lock",
        "backfill.sqlite3",
        "backfill.sqlite3-wal",
        "backfill.sqlite3-shm",
    ),
)
def test_cli_report_path_cannot_overwrite_runtime_artifacts_even_on_error(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    protected_name: str,
) -> None:
    protected = tmp_path / protected_name
    marker = b"operator-artifact-marker"
    protected.write_bytes(marker)

    code = cli.main([*_base_args(tmp_path), "--report-path", str(protected)])

    assert code == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "BLOCKED_FAIL_CLOSED"
    assert "report_path_collides" in report["error"]
    assert protected.read_bytes() == marker


def test_cli_report_hard_link_alias_cannot_truncate_archive(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    archive = tmp_path / "labels.sqlite3"
    marker = b"operator-archive-marker"
    archive.write_bytes(marker)
    report_path = tmp_path / "report-hard-link.json"
    os.link(archive, report_path)

    code = cli.main([*_base_args(tmp_path), "--report-path", str(report_path)])

    assert code == 2
    assert "report_path_collides" in json.loads(capsys.readouterr().out)["error"]
    assert archive.read_bytes() == marker
    assert report_path.read_bytes() == marker


def test_cli_report_path_cannot_overwrite_attestation(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    attestation = _write_attestation(tmp_path)
    before = attestation.read_bytes()

    code = cli.main(
        [
            *_base_args(tmp_path),
            "--wss-inactive-attestation",
            str(attestation),
            "--report-path",
            str(attestation),
        ]
    )

    assert code == 2
    assert "report_path_collides" in json.loads(capsys.readouterr().out)["error"]
    assert attestation.read_bytes() == before


def test_cli_state_path_cannot_equal_archive_even_in_plan_mode(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    args = _base_args(tmp_path)
    state_index = args.index("--state-path") + 1
    args[state_index] = str(tmp_path / "labels.sqlite3")

    code = cli.main(args)

    assert code == 2
    assert "state_path_collides" in json.loads(capsys.readouterr().out)["error"]
    assert not (tmp_path / "labels.sqlite3").exists()


def test_cli_shared_rest_gate_reserves_exact_binance_request_weight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_require(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"request_allowed": True}

    monkeypatch.setattr(cli, "require_binance_rest_fallback", _fake_require)
    request = cli.BinanceKlineRequest(
        symbol="BTCUSDT",
        start_open_time_ms=1_700_000_000_000,
        end_close_time_ms=1_700_299_999_999,
        limit=1_000,
    )

    cli._before_public_request(request)

    assert captured["request_weight"] == 5
    assert captured["require_shared_budget"] is True


def test_cli_rate_limit_callback_requires_durable_shared_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "report_binance_rest_response",
        lambda **_kwargs: False,
    )
    response = cli.PublicHttpResponse(
        status_code=418,
        headers={"retry-after": "1800"},
        body=b"[]",
        received_at_ms=NOW_MS,
    )

    with pytest.raises(
        cli.Historical5mBackfillError,
        match="shared_rate_limit_cooldown_persistence_failed",
    ):
        cli._on_rate_limit(response)
