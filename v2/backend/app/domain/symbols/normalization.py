from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional, Set

from .models import ContractFamily, ContractType, MarketType, NormalizationConfidence, SymbolIdentity


def normalize_contract_type(raw: Optional[str], symbol: str = "") -> str:
    value = (raw or "").upper()
    if value == "PERPETUAL" or symbol.endswith("_PERP"):
        return ContractType.PERPETUAL.value
    if value == "CURRENT_QUARTER":
        return ContractType.CURRENT_QUARTER.value
    if value == "NEXT_QUARTER":
        return ContractType.NEXT_QUARTER.value
    if value or re.search(r"_\d{6}$", symbol):
        return ContractType.DATED_DELIVERY.value
    return ContractType.UNKNOWN.value


def normalize_asset(value: Optional[str]) -> str:
    return (value or "").upper().replace("-", "").replace("_", "")


def canonical_id(
    base_asset: str,
    quote_asset: str,
    contract_type: str,
    contract_family: str,
    exchange: str,
    delivery_date: Optional[Any] = None,
) -> str:
    type_part = "PERP" if contract_type == ContractType.PERPETUAL.value else str(delivery_date or contract_type).upper()
    return "-".join([
        normalize_asset(base_asset),
        normalize_asset(quote_asset),
        type_part,
        contract_family.replace("_", "").upper(),
        exchange.upper(),
    ])


def build_alias_set(identity: SymbolIdentity) -> list[str]:
    aliases: Set[str] = {
        identity.canonical_symbol_id,
        identity.source_symbol,
        identity.source_symbol.replace("_", ""),
    }
    if identity.source_pair:
        aliases.add(identity.source_pair)
    if identity.legacy_symbol:
        aliases.add(identity.legacy_symbol)
    aliases.add(f"{identity.base_asset}{identity.quote_asset}")
    aliases.add(f"{identity.base_asset}-{identity.quote_asset}")
    if identity.contract_type == ContractType.PERPETUAL.value:
        aliases.add(f"{identity.base_asset}{identity.quote_asset}_PERP")
    return sorted(a for a in aliases if a)


def normalize_source_symbol(source: str, raw_symbol_payload: Dict[str, Any]) -> SymbolIdentity:
    source_key = source.lower()
    if source_key == "binance_usdm":
        return _normalize_binance_usdm(raw_symbol_payload)
    if source_key == "binance_coinm":
        return _normalize_binance_coinm(raw_symbol_payload)
    if source_key == "coinank":
        return _normalize_generic(source_key, raw_symbol_payload, exchange="coinank", family=ContractFamily.UNKNOWN.value)
    if source_key == "coinapi_ws":
        return _normalize_generic(source_key, raw_symbol_payload, exchange="coinapi", family=ContractFamily.USD_M.value)
    if source_key == "coinapi_rest":
        return _normalize_generic(source_key, raw_symbol_payload, exchange="coinapi", family=ContractFamily.USD_M.value)
    if source_key == "kucoin":
        return _normalize_generic(source_key, raw_symbol_payload, exchange="kucoin", family=ContractFamily.USD_M.value)
    raise ValueError(f"unsupported symbol source: {source}")


def _normalize_binance_usdm(payload: Dict[str, Any]) -> SymbolIdentity:
    symbol = str(payload.get("symbol", ""))
    pair = str(payload.get("pair", "")) or symbol
    base = normalize_asset(payload.get("baseAsset") or re.sub(r"(USDT|USDC|USD)$", "", pair))
    quote = normalize_asset(payload.get("quoteAsset") or ("USDC" if symbol.endswith("USDC") else "USDT"))
    settlement = normalize_asset(payload.get("marginAsset") or quote)
    contract_type = normalize_contract_type(payload.get("contractType"), symbol)
    type_part = "PERP" if contract_type == ContractType.PERPETUAL.value else str(payload.get("deliveryDate") or contract_type).upper()
    metadata = {
        "deliveryDate": payload.get("deliveryDate"),
        "onboardDate": payload.get("onboardDate"),
        "filters": payload.get("filters", []),
        "pricePrecision": payload.get("pricePrecision"),
        "quantityPrecision": payload.get("quantityPrecision"),
        "linear": True,
    }
    identity = SymbolIdentity(
        canonical_symbol_id=f"BINANCE-USDM-{base}-{quote}-{type_part}",
        base_asset=base,
        quote_asset=quote,
        settlement_asset=settlement,
        market_type=MarketType.FUTURES.value,
        contract_family=ContractFamily.USD_M.value,
        contract_type=contract_type,
        exchange="binance",
        source="binance_usdm",
        source_symbol=symbol,
        source_pair=pair,
        legacy_symbol=symbol if quote in {"USDT", "USDC"} else payload.get("legacy_symbol"),
        normalization_confidence=NormalizationConfidence.HIGH.value,
        status=str(payload.get("status") or payload.get("contractStatus") or ""),
        metadata=metadata,
    )
    return SymbolIdentity(**{**identity.__dict__, "alias_set": build_alias_set(identity)})


def _normalize_binance_coinm(payload: Dict[str, Any]) -> SymbolIdentity:
    symbol = str(payload.get("symbol", ""))
    pair = str(payload.get("pair", "")) or symbol.split("_", 1)[0]
    base = normalize_asset(payload.get("baseAsset") or re.sub(r"(USD|USDT)$", "", pair))
    quote = normalize_asset(payload.get("quoteAsset") or "USD")
    settlement = normalize_asset(payload.get("marginAsset") or base)
    contract_type = normalize_contract_type(payload.get("contractType"), symbol)
    metadata = {
        "deliveryDate": payload.get("deliveryDate"),
        "onboardDate": payload.get("onboardDate"),
        "filters": payload.get("filters", []),
        "pricePrecision": payload.get("pricePrecision"),
        "quantityPrecision": payload.get("quantityPrecision"),
    }
    identity = SymbolIdentity(
        canonical_symbol_id=canonical_id(base, quote, contract_type, ContractFamily.COIN_M.value, "binance", payload.get("deliveryDate")),
        base_asset=base,
        quote_asset=quote,
        settlement_asset=settlement,
        market_type=MarketType.FUTURES.value,
        contract_family=ContractFamily.COIN_M.value,
        contract_type=contract_type,
        exchange="binance",
        source="binance_coinm",
        source_symbol=symbol,
        source_pair=pair,
        legacy_symbol=payload.get("legacy_symbol"),
        normalization_confidence=NormalizationConfidence.HIGH.value,
        status=str(payload.get("contractStatus") or payload.get("status") or ""),
        metadata=metadata,
    )
    return SymbolIdentity(**{**identity.__dict__, "alias_set": build_alias_set(identity)})


def _normalize_generic(source: str, payload: Dict[str, Any], exchange: str, family: str) -> SymbolIdentity:
    source_symbol = str(payload.get("symbol") or payload.get("source_symbol") or payload.get("id") or "")
    pair = str(payload.get("pair") or payload.get("source_pair") or source_symbol)
    base = normalize_asset(payload.get("baseAsset") or payload.get("base") or pair.split("-")[0].split("/")[0])
    default_quote = "USDT" if "USDT" in pair.upper() else "USD"
    quote = normalize_asset(payload.get("quoteAsset") or payload.get("quote") or default_quote)
    settlement = normalize_asset(payload.get("settlementAsset") or payload.get("settlement") or quote)
    contract_type = normalize_contract_type(payload.get("contractType") or payload.get("contract_type"), source_symbol)
    identity = SymbolIdentity(
        canonical_symbol_id=canonical_id(base, quote, contract_type, family, exchange, payload.get("deliveryDate")),
        base_asset=base,
        quote_asset=quote,
        settlement_asset=settlement,
        market_type=MarketType.FUTURES.value,
        contract_family=family,
        contract_type=contract_type,
        exchange=exchange,
        source=source,
        source_symbol=source_symbol,
        source_pair=pair,
        legacy_symbol=payload.get("legacy_symbol"),
        normalization_confidence=payload.get("normalization_confidence", NormalizationConfidence.MEDIUM.value),
        status=payload.get("status"),
        metadata={k: v for k, v in payload.items() if k not in {"symbol", "pair", "base", "quote"}},
    )
    return SymbolIdentity(**{**identity.__dict__, "alias_set": build_alias_set(identity)})


def resolve_symbol_alias(source_symbol: str, source: str, identities: Iterable[SymbolIdentity]) -> Optional[SymbolIdentity]:
    wanted = source_symbol.upper()
    source_key = source.lower()
    for identity in identities:
        aliases = {a.upper() for a in identity.alias_set}
        if identity.source == source_key and wanted in aliases:
            return identity
    for identity in identities:
        if wanted in {a.upper() for a in identity.alias_set}:
            return identity
    return None


def match_cross_source_symbol(identity_a: SymbolIdentity, identity_b: SymbolIdentity) -> str:
    if identity_a.canonical_symbol_id == identity_b.canonical_symbol_id:
        return NormalizationConfidence.HIGH.value
    same_base_quote = identity_a.base_asset == identity_b.base_asset and identity_a.quote_asset == identity_b.quote_asset
    if same_base_quote and (
        identity_a.contract_type != identity_b.contract_type
        or identity_a.contract_family != identity_b.contract_family
        or identity_a.settlement_asset != identity_b.settlement_asset
    ):
        return "none"
    same_contract = (
        same_base_quote
        and identity_a.settlement_asset == identity_b.settlement_asset
        and identity_a.contract_type == identity_b.contract_type
        and identity_a.contract_family == identity_b.contract_family
    )
    if same_contract:
        return NormalizationConfidence.HIGH.value
    same_market = (
        identity_a.base_asset == identity_b.base_asset
        and identity_a.quote_asset == identity_b.quote_asset
        and identity_a.contract_type == identity_b.contract_type
    )
    if same_market:
        return NormalizationConfidence.MEDIUM.value
    if identity_a.contract_type == identity_b.contract_type and identity_a.contract_family == identity_b.contract_family and set(identity_a.alias_set) & set(identity_b.alias_set):
        return NormalizationConfidence.LOW.value
    return "none"
