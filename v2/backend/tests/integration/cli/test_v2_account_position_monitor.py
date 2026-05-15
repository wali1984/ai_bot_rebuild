from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_account_position_monitor as worker
from v2.backend.app.cli.v2_account_position_monitor import (
    LIVE_GATE_STATUS,
    MISSING_EVIDENCE,
    REQUIRED_PUBLIC_PAYLOAD_FIELDS,
    SOURCE_ENDPOINT_VERSIONS,
    SYMBOL_UNIVERSE_CONTRACT,
    WORKER_ID,
    build_symbol_scope,
    parse_args,
    run_once,
)
from v2.backend.app.services.account_position_monitor.service import (
    ACCOUNT_ENDPOINT,
    POSITION_RISK_ENDPOINT,
    BinanceFuturesReadOnlyClient,
    ExchangeReadError,
    RateLimitError,
    ReadOnlyCredentials,
)
from v2.backend.app.services.symbol_universe.service import (
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
)


def _route_writes_to(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Path]:
    public_dir = tmp_path / "public"
    local_dir = tmp_path / "local"
    worker_dir = tmp_path / "worker"
    monkeypatch.setattr(worker, "PUBLIC_RUNTIME_DIR", public_dir)
    monkeypatch.setattr(worker, "LOCAL_RUNTIME_DIR", local_dir)
    monkeypatch.setattr(worker, "WORKER_STATUS_DIR", worker_dir)
    monkeypatch.setattr(worker, "PUBLIC_STATUS_FILE", public_dir / f"{WORKER_ID}_status.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_FILE", local_dir / f"{WORKER_ID}_status.json")
    monkeypatch.setattr(worker, "WORKER_STATUS_FILE", worker_dir / f"{WORKER_ID}_status.json")
    monkeypatch.setattr(
        worker,
        "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES",
        [tmp_path / "missing_symbol_universe.json"],
    )
    monkeypatch.setattr(
        worker,
        "PAPER_POSITION_CANDIDATE_PATHS",
        [tmp_path / "paper_runtime_status.json"],
    )
    return {"public": public_dir, "local": local_dir, "worker": worker_dir}


class FakeReadOnlyClient:
    readonly_endpoint_paths = (ACCOUNT_ENDPOINT, POSITION_RISK_ENDPOINT)

    def __init__(
        self,
        *,
        account: Dict[str, Any] | None = None,
        positions: List[Dict[str, Any]] | None = None,
    ):
        self.account = account or {
            "totalWalletBalance": "2500.0",
            "availableBalance": "2100.0",
            "totalUnrealizedProfit": "12.5",
            "totalMarginBalance": "2512.5",
            "totalMaintMargin": "22.0",
            "canTrade": True,
            "positions": [{"symbol": "BTCUSDT", "leverage": "10"}],
        }
        self.positions = positions or [
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0.25",
                "entryPrice": "60000",
                "markPrice": "60100",
                "unRealizedProfit": "25.0",
                "liquidationPrice": "52000",
                "leverage": "10",
                "marginType": "isolated",
                "isolatedMargin": "1500",
                "positionInitialMargin": "1500",
            },
            {
                "symbol": "ETHUSDT",
                "positionAmt": "0",
                "entryPrice": "3200",
                "markPrice": "3210",
                "unRealizedProfit": "0",
                "leverage": "5",
                "marginType": "cross",
            }
        ]
        self.calls: List[str] = []

    def fetch_account(self) -> Dict[str, Any]:
        self.calls.append(ACCOUNT_ENDPOINT)
        return self.account

    def fetch_positions(self) -> List[Dict[str, Any]]:
        self.calls.append(POSITION_RISK_ENDPOINT)
        return self.positions


def _present_credentials() -> ReadOnlyCredentials:
    return ReadOnlyCredentials(api_key="test-key", api_secret="test-secret", status="PRESENT")


def test_read_only_account_and_position_endpoints_are_called(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    client = FakeReadOnlyClient()

    status = run_once(parse_args(["--once"]), client=client, credentials=_present_credentials())

    assert client.calls == [ACCOUNT_ENDPOINT, POSITION_RISK_ENDPOINT]
    assert status["runtime_evidence_status"] == "PRESENT"
    assert status["source_endpoint_versions"] == SOURCE_ENDPOINT_VERSIONS
    assert status["open_positions_count"] == 1
    assert status["account_snapshot"]["total_wallet_balance"] == pytest.approx(2500.0)
    assert status["account_snapshot"]["available_balance"] == pytest.approx(2100.0)
    assert status["account_snapshot"]["total_unrealized_profit"] == pytest.approx(12.5)
    assert status["account_snapshot"]["total_maint_margin"] == pytest.approx(22.0)
    assert status["account_snapshot"]["total_margin_balance"] == pytest.approx(2512.5)
    assert status["maintenance_margin_ratio_pct"] == pytest.approx((22.0 / 2512.5) * 100.0)
    assert status["account_margin_ratio_status"] == "PRESENT"
    assert status["open_positions_sample_anonymized"][0]["symbol"] == "BTCUSDT"
    assert status["margin_mode_evidence_or_MISSING_EVIDENCE"] == ["isolated"]
    assert status["leverage_evidence_or_MISSING_EVIDENCE"] == [10]
    assert status["positions"][0]["entry_price"] == pytest.approx(60000.0)
    assert status["positions"][0]["mark_price"] == pytest.approx(60100.0)
    assert status["positions"][0]["liquidation_price"] == pytest.approx(52000.0)
    assert status["positions"][0]["notional"] == pytest.approx(0.25 * 60100.0)
    assert status["positions"][0]["unrealized_pnl"] == pytest.approx(25.0)
    assert status["open_positions_sample_anonymized"][0]["liquidation_price"] == pytest.approx(52000.0)
    assert status["live_gate"] == LIVE_GATE_STATUS == "blocked_human_only"
    assert status["exchange_action_taken"] is False
    assert status["exchange_mutation_performed"] is False
    written = json.loads((paths["public"] / f"{WORKER_ID}_status.json").read_text())
    assert written["worker_id"] == WORKER_ID


def test_real_readonly_client_uses_expected_endpoint_paths() -> None:
    seen_paths: List[str] = []

    def request_func(url: str, timeout_seconds: float) -> Any:
        del timeout_seconds
        parsed = urllib.parse.urlparse(url)
        seen_paths.append(parsed.path)
        if parsed.path == ACCOUNT_ENDPOINT:
            return {"canTrade": False, "positions": []}
        if parsed.path == POSITION_RISK_ENDPOINT:
            return []
        raise AssertionError(parsed.path)

    client = BinanceFuturesReadOnlyClient(
        credentials=_present_credentials(),
        request_func=request_func,
    )
    assert client.fetch_account()["canTrade"] is False
    assert client.fetch_positions() == []
    assert seen_paths == [ACCOUNT_ENDPOINT, POSITION_RISK_ENDPOINT]


def test_no_credentials_fallback_emits_missing_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    for name in (
        "BINANCE_FUTURES_READONLY_API_KEY",
        "BINANCE_FUTURES_READONLY_API_SECRET",
        "BINANCE_FUT_API_KEY_READONLY",
        "BINANCE_FUT_API_SECRET_READONLY",
        "BINANCE_FUT_API_KEY",
        "BINANCE_FUT_API_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    status = run_once(parse_args(["--once"]))

    assert status["runtime_evidence_status"] == "MISSING_CREDENTIALS"
    assert status["generated_at"] == status["last_run_ts"]
    assert status["credentials_status_one_of_PRESENT_MISSING_INVALID"] == "MISSING"
    assert status["fail_closed"] is True
    assert status["open_positions_count"] == 0
    assert status["margin_mode_evidence_or_MISSING_EVIDENCE"] == MISSING_EVIDENCE
    assert status["leverage_evidence_or_MISSING_EVIDENCE"] == MISSING_EVIDENCE
    assert "MISSING_CREDENTIALS" in status["canary_blockers"]


def test_never_emits_paper_positions_as_real_account_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper_path = tmp_path / "paper_runtime_status.json"
    paper_path.write_text(
        json.dumps(
            {
                "positions": [
                    {
                        "symbol": "DOGEUSDT",
                        "side": "LONG",
                        "source": "paper_online_runtime",
                    }
                ]
            }
        )
    )
    _route_writes_to(tmp_path, monkeypatch)
    monkeypatch.setattr(worker, "PAPER_POSITION_CANDIDATE_PATHS", [paper_path])

    status = run_once(
        parse_args(["--once"]),
        client=FakeReadOnlyClient(
            positions=[
                {
                    "symbol": "ETHUSDT",
                    "positionAmt": "-1.0",
                    "entryPrice": "3200",
                    "markPrice": "3190",
                    "unRealizedProfit": "10.0",
                    "leverage": "5",
                    "marginType": "cross",
                }
            ]
        ),
        credentials=_present_credentials(),
    )

    assert status["paper_positions_payload_present"] is True
    assert status["paper_positions_ignored_for_real_account"] is True
    assert status["open_positions_sample_anonymized"][0]["symbol"] == "ETHUSDT"
    assert "DOGEUSDT" not in json.dumps(status["open_positions_sample_anonymized"])


def test_fail_closed_on_exchange_read_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _route_writes_to(tmp_path, monkeypatch)

    class BrokenClient(FakeReadOnlyClient):
        def fetch_account(self) -> Dict[str, Any]:
            raise ExchangeReadError("boom")

    status = run_once(parse_args(["--once"]), client=BrokenClient(), credentials=_present_credentials())

    assert status["fail_closed"] is True
    assert status["runtime_evidence_status"] == "EXCHANGE_READ_FAILED"
    assert status["exchange_action_taken"] is False


def test_rate_limit_backoff_then_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    sleeps: List[float] = []

    class RateLimitedOnceClient(FakeReadOnlyClient):
        def __init__(self) -> None:
            super().__init__()
            self._first = True

        def fetch_account(self) -> Dict[str, Any]:
            if self._first:
                self._first = False
                raise RateLimitError("slow down", retry_after_seconds=1.5)
            return super().fetch_account()

    status = run_once(
        parse_args(["--once"]),
        client=RateLimitedOnceClient(),
        credentials=_present_credentials(),
        sleep_func=sleeps.append,
    )

    assert sleeps == [1.5]
    assert status["runtime_evidence_status"] == "PRESENT"
    assert status["fail_closed"] is False


def test_readonly_contract_rejects_mutating_client_attribute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    client = FakeReadOnlyClient()
    setattr(client, "create" + "_" + "order", lambda: None)

    status = run_once(parse_args(["--once"]), client=client, credentials=_present_credentials())

    assert status["fail_closed"] is True
    assert status["runtime_evidence_status"] == "READONLY_CONTRACT_FAILED"


def test_readonly_contract_rejects_mutating_endpoint_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _route_writes_to(tmp_path, monkeypatch)

    class MutatingEndpointClient(FakeReadOnlyClient):
        readonly_endpoint_paths = (ACCOUNT_ENDPOINT, POSITION_RISK_ENDPOINT, "/fapi/v1/" + "order")

    status = run_once(
        parse_args(["--once"]),
        client=MutatingEndpointClient(),
        credentials=_present_credentials(),
    )

    assert status["fail_closed"] is True
    assert status["runtime_evidence_status"] == "READONLY_CONTRACT_FAILED"


def test_missing_margin_and_leverage_are_explicit_evidence_gaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    status = run_once(
        parse_args(["--once"]),
        client=FakeReadOnlyClient(
            account={"canTrade": False, "positions": []},
            positions=[
                {
                    "symbol": "SOLUSDT",
                    "positionAmt": "2.0",
                    "entryPrice": "150",
                    "markPrice": "151",
                    "unRealizedProfit": "2.0",
                }
            ],
        ),
        credentials=_present_credentials(),
    )

    assert status["margin_mode_evidence_or_MISSING_EVIDENCE"] == MISSING_EVIDENCE
    assert status["leverage_evidence_or_MISSING_EVIDENCE"] == MISSING_EVIDENCE
    assert "ISOLATED_MARGIN_EVIDENCE_MISSING" in status["canary_blockers"]
    assert "LEVERAGE_CAP_EVIDENCE_MISSING" in status["canary_blockers"]


def test_symbol_universe_contract_roles_are_distinguished(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    symbol_payload = tmp_path / "symbol_universe_status.json"
    symbol_payload.write_text(
        json.dumps(
            {
                "legacy_active_symbols": LEGACY_ACTIVE_SYMBOLS_25,
                "discovered_symbols": ["BTCUSDT", "ETHUSDT", "COINANKONLYUSDT"],
                "dynamic_discovered_symbols": ["BTCUSDT", "ETHUSDT", "COINANKONLYUSDT"],
                "training_symbols": ["BTCUSDT"],
                "paper_symbols": ["ETHUSDT"],
                "binance_usdm_confirmed_symbols": ["BTCUSDT", "ETHUSDT"],
            }
        )
    )
    monkeypatch.setattr(worker, "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES", [symbol_payload])

    scope = build_symbol_scope(observed_symbols=["BTCUSDT", "ETHUSDT"])

    assert scope["symbol_universe_contract"] == SYMBOL_UNIVERSE_CONTRACT
    assert scope["legacy_active_symbols"] == sorted(LEGACY_ACTIVE_SYMBOLS_25)
    assert len(scope["legacy_active_symbols"]) == 25
    assert scope["discovered_symbols"] == ["BTCUSDT", "COINANKONLYUSDT", "ETHUSDT"]
    assert scope["dynamic_discovered_symbols"] == ["BTCUSDT", "COINANKONLYUSDT", "ETHUSDT"]
    assert scope["training_symbols"] == ["BTCUSDT"]
    assert scope["paper_symbols"] == ["ETHUSDT"]
    assert scope["live_symbols"] == []
    assert scope["train_all_discovered_symbols"] is False
    assert scope["trade_all_discovered_symbols"] is False
    assert scope["coinank_symbols_directly_tradable"] is False
    assert scope["binance_usdm_confirmed_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert "COINANKONLYUSDT" not in scope["binance_usdm_confirmed_symbols"]
    assert scope["symbol_selection_score_factors"] == SYMBOL_SELECTION_SCORE_FACTORS


def test_required_public_payload_fields_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    status = run_once(parse_args(["--once"]), client=FakeReadOnlyClient(), credentials=_present_credentials())

    missing = [field for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS if field not in status]
    assert missing == []


def test_worker_source_has_no_mutating_exchange_method_tokens() -> None:
    source = (
        (REPO_ROOT / "v2/backend/app/cli/v2_account_position_monitor.py").read_text()
        + "\n"
        + (REPO_ROOT / "v2/backend/app/services/account_position_monitor/service.py").read_text()
    )
    forbidden = [
        "create" + "_" + "order",
        "cancel" + "_" + "order",
        "futures" + "_" + "create" + "_" + "order",
        "futures" + "_" + "change" + "_" + "leverage",
        "futures" + "_" + "change" + "_" + "margin" + "_" + "type",
    ]
    assert [token for token in forbidden if token in source] == []
