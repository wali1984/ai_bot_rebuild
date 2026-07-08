from __future__ import annotations

from typing import Any, Iterable, Mapping


BETA_BY_SYMBOL_PREFIX: dict[str, tuple[float, float]] = {
    "BTC": (1.0, 0.35),
    "ETH": (0.45, 1.0),
    "SOL": (0.28, 0.42),
    "BNB": (0.22, 0.28),
}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _symbol(row: Mapping[str, Any]) -> str:
    return str(row.get("symbol") or "").upper()


def _side(row: Mapping[str, Any]) -> str:
    return str(row.get("side") or row.get("action") or "").strip().lower()


def _notional(row: Mapping[str, Any]) -> float:
    return abs(
        _f(
            row.get("target_notional_usd")
            or row.get("target_notional_usdt")
            or row.get("gross_notional_usd")
            or row.get("notional_usd")
            or row.get("notional")
        )
    )


def _signed_notional(row: Mapping[str, Any]) -> float:
    value = _notional(row)
    side = _side(row)
    if side in {"short", "sell", "open_short"}:
        return -value
    if side in {"long", "buy", "open_long"}:
        return value
    return 0.0


def _beta(symbol: str) -> tuple[float, float]:
    for prefix, beta in BETA_BY_SYMBOL_PREFIX.items():
        if symbol.startswith(prefix):
            return beta
    return (0.18, 0.18)


def compute_portfolio_exposure(
    positions: Iterable[Mapping[str, Any]] | None = None,
    *,
    candidate: Mapping[str, Any] | None = None,
    correlation_exposure_pct: float | None = None,
    equity_usd: float | None = None,
) -> dict[str, Any]:
    rows: list[Mapping[str, Any]] = list(positions or [])
    if candidate:
        rows.append(candidate)

    long_exposure = 0.0
    short_exposure = 0.0
    net_delta = 0.0
    btc_beta = 0.0
    eth_beta = 0.0
    sector_totals: dict[str, float] = {}

    for row in rows:
        signed = _signed_notional(row)
        notional = abs(signed)
        if signed > 0:
            long_exposure += notional
        elif signed < 0:
            short_exposure += notional
        net_delta += signed
        btc, eth = _beta(_symbol(row))
        btc_beta += signed * btc
        eth_beta += signed * eth
        sector = str(row.get("sector") or row.get("asset_sector") or "crypto").lower()
        sector_totals[sector] = sector_totals.get(sector, 0.0) + signed

    gross_exposure = long_exposure + short_exposure
    equity = max(_f(equity_usd), 1.0)
    corr_pct = _f(correlation_exposure_pct)
    if corr_pct <= 0.0 and gross_exposure > 0.0:
        corr_pct = min(1.0, gross_exposure / equity)

    return {
        "net_delta_usd": round(net_delta, 8),
        "gross_exposure_usd": round(gross_exposure, 8),
        "long_exposure_usd": round(long_exposure, 8),
        "short_exposure_usd": round(short_exposure, 8),
        "btc_beta_exposure_usd": round(btc_beta, 8),
        "eth_beta_exposure_usd": round(eth_beta, 8),
        "sector_exposure_usd": {key: round(value, 8) for key, value in sorted(sector_totals.items())},
        "correlation_exposure_usd": round(gross_exposure * corr_pct, 8),
        "correlation_exposure_pct": round(corr_pct, 8),
    }
