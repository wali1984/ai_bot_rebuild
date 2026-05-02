from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from .models import (
    ContractFamily,
    ContractType,
    MarketType,
    NormalizationConfidence,
    SymbolIdentity,
)

STOCK_LIKE_BASES: frozenset[str] = frozenset({
    "AAPL", "TSLA", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "MSFT",
    "NFLX", "AMD", "INTC", "IBM", "ORCL", "QQQ", "SPY",
    "GOLD", "SILVER", "OIL", "WTI", "BRENT", "COPPER", "NATGAS",
    "SP500", "DOW", "NASDAQ",
})

BINANCE_USDM_EXCHANGE_SLUGS: frozenset[str] = frozenset({
    "BINANCE", "BINANCE_USDM", "BINANCE_FUTURES", "BINANCE_PERP",
})

DATED_SUFFIX_RE = re.compile(r"_(\d{6})$")
PERP_SUFFIX_RE = re.compile(r"_PERP$")


@dataclass(frozen=True)
class CoinAnkRawRow:
    symbol: str
    baseCoin: str
    exchangeName: str
    expireAt: Optional[int]
    updateAt: Optional[int]
    productType: Optional[str] = None
    quoteCoin: Optional[str] = None
    tradingPair: Optional[str] = None
    marketType: Optional[str] = None
    is_synthetic: bool = False


def _is_chinese(value: str) -> bool:
    return any(ord(c) > 0x7F for c in (value or ""))


def _normalize_ascii_letters(value: str) -> str:
    return "".join(c for c in (value or "").upper() if c.isascii() and c.isalnum())


def _stable_cjk_token(value: str) -> str:
    return "CJK" + hashlib.sha1((value or "").encode("utf-8")).hexdigest()[:8].upper()


def _classify_quote_kind(symbol: str, explicit_quote: Optional[str]) -> str:
    upper = (symbol or "").upper()
    if explicit_quote:
        eu = explicit_quote.upper()
        if eu in {"USDT", "USDC", "USD", "BTC", "ETH"}:
            return eu
    stem = upper
    perp_match = PERP_SUFFIX_RE.search(stem)
    if perp_match:
        stem = stem[: perp_match.start()]
    else:
        dated_match = DATED_SUFFIX_RE.search(stem)
        if dated_match:
            stem = stem[: dated_match.start()]
    if stem.endswith("USDT"):
        return "USDT"
    if stem.endswith("USDC"):
        return "USDC"
    if stem.endswith("USD"):
        return "USD"
    if stem.endswith("BTC"):
        return "BTC"
    if stem.endswith("ETH"):
        return "ETH"
    return "OTHER"


def _exchange_slug(exchange_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", (exchange_name or "")).upper().strip("_")
    return cleaned or "UNKNOWN"


def classify_coinank_row(row: CoinAnkRawRow) -> Dict[str, Any]:
    symbol = row.symbol or ""
    base_coin = row.baseCoin or ""
    is_chinese_name = _is_chinese(symbol) or _is_chinese(base_coin)
    base_token = _normalize_ascii_letters(base_coin)
    is_stock_like = base_token in STOCK_LIKE_BASES
    is_dated = bool(row.expireAt and int(row.expireAt) > 0) or bool(DATED_SUFFIX_RE.search(symbol))
    quote_kind = _classify_quote_kind(symbol, row.quoteCoin)
    is_perp_inverse = bool(PERP_SUFFIX_RE.search(symbol)) and quote_kind == "USD"
    is_usdc = quote_kind == "USDC"
    is_usdt = quote_kind == "USDT"
    candidate_for_usdm_confirmation = (
        not is_chinese_name
        and not is_stock_like
        and not is_dated
        and not is_perp_inverse
        and quote_kind in {"USDT", "USDC"}
    )
    return {
        "is_chinese_name": is_chinese_name,
        "is_stock_like": is_stock_like,
        "is_dated": is_dated,
        "is_perp_inverse": is_perp_inverse,
        "is_usdc": is_usdc,
        "is_usdt": is_usdt,
        "quote_kind": quote_kind,
        "candidate_for_usdm_confirmation": candidate_for_usdm_confirmation,
        "exchange_slug": _exchange_slug(row.exchangeName),
        "requires_confirmation": True,
    }


def coinank_identity_from_row(row: CoinAnkRawRow) -> SymbolIdentity:
    flags = classify_coinank_row(row)
    base_token = _normalize_ascii_letters(row.baseCoin) or _stable_cjk_token(row.baseCoin)
    quote = flags["quote_kind"] if flags["quote_kind"] != "OTHER" else "OTHER"
    if flags["is_perp_inverse"]:
        type_part = "INVERSE_PERP"
        contract_type = ContractType.PERPETUAL.value
    elif flags["is_dated"]:
        if row.expireAt and int(row.expireAt) > 0:
            type_part = f"DATED{int(row.expireAt)}"
        else:
            match = DATED_SUFFIX_RE.search(row.symbol)
            type_part = f"DATED{match.group(1)}" if match else "DATED"
        contract_type = ContractType.DATED_DELIVERY.value
    elif PERP_SUFFIX_RE.search(row.symbol):
        type_part = "PERP"
        contract_type = ContractType.PERPETUAL.value
    elif quote in {"USDT", "USDC"}:
        type_part = "PERP"
        contract_type = ContractType.PERPETUAL.value
    else:
        type_part = "UNKNOWN"
        contract_type = ContractType.UNKNOWN.value
    canonical = "-".join(["COINANK-DISC", flags["exchange_slug"], base_token, quote, type_part])
    metadata: Dict[str, Any] = {
        "coinank_raw": {
            "symbol": row.symbol,
            "baseCoin": row.baseCoin,
            "exchangeName": row.exchangeName,
            "expireAt": row.expireAt,
            "updateAt": row.updateAt,
            "productType": row.productType,
            "quoteCoin": row.quoteCoin,
            "tradingPair": row.tradingPair,
            "marketType": row.marketType,
        },
        "is_synthetic": row.is_synthetic,
    }
    metadata.update(flags)
    market_type = (
        MarketType.FUTURES.value
        if flags["exchange_slug"] in BINANCE_USDM_EXCHANGE_SLUGS
        else "unknown"
    )
    return SymbolIdentity(
        canonical_symbol_id=canonical,
        base_asset=base_token,
        quote_asset=quote,
        settlement_asset="UNKNOWN",
        market_type=market_type,
        contract_family=ContractFamily.UNKNOWN.value,
        contract_type=contract_type,
        exchange="coinank",
        source="coinank",
        source_symbol=row.symbol,
        source_pair=row.tradingPair or row.symbol,
        legacy_symbol=None,
        normalization_confidence=NormalizationConfidence.LOW.value,
        alias_set=[],
        status="discovery_only",
        metadata=metadata,
    )


def coinank_row_from_payload(payload: Dict[str, Any]) -> CoinAnkRawRow:
    return CoinAnkRawRow(
        symbol=str(payload.get("symbol", "")),
        baseCoin=str(payload.get("baseCoin", "")),
        exchangeName=str(payload.get("exchangeName", "")),
        expireAt=payload.get("expireAt"),
        updateAt=payload.get("updateAt"),
        productType=payload.get("productType"),
        quoteCoin=payload.get("quoteCoin"),
        tradingPair=payload.get("tradingPair"),
        marketType=payload.get("marketType"),
        is_synthetic=bool(payload.get("is_synthetic", False)),
    )


def confirm_coinank_against_usdm(
    coinank_identity: SymbolIdentity,
    usdm_identities: Iterable[SymbolIdentity],
) -> Optional[SymbolIdentity]:
    if coinank_identity.source != "coinank":
        return None
    metadata = coinank_identity.metadata or {}
    if not metadata.get("candidate_for_usdm_confirmation"):
        return None
    if metadata.get("exchange_slug") not in BINANCE_USDM_EXCHANGE_SLUGS:
        return None
    base = coinank_identity.base_asset
    quote = coinank_identity.quote_asset
    for usdm in usdm_identities:
        if usdm.source != "binance_usdm":
            continue
        if usdm.contract_family != ContractFamily.USD_M.value:
            continue
        if usdm.contract_type != ContractType.PERPETUAL.value:
            continue
        if usdm.base_asset != base or usdm.quote_asset != quote:
            continue
        if not usdm.is_trading():
            continue
        return usdm
    return None
