from v2.backend.app.domain.symbols.models import ManualOverride, SymbolOverride, SymbolState, SymbolStateRecord
from v2.backend.app.domain.symbols.normalization import normalize_source_symbol
from v2.backend.app.domain.symbols.state_machine import apply_override


def test_manual_override_can_force_observe_non_trading_symbol():
    identity = normalize_source_symbol("binance_coinm", {
        "symbol": "BNBUSD_200925",
        "pair": "BNBUSD",
        "contractType": "CURRENT_QUARTER",
        "contractStatus": "DELIVERED",
        "baseAsset": "BNB",
        "quoteAsset": "USD",
        "marginAsset": "BNB",
    })
    record = SymbolStateRecord(identity=identity)
    moved = apply_override(record, SymbolOverride(action=ManualOverride.FORCE_OBSERVE.value, reason="operator_review"))

    assert moved.state == SymbolState.OBSERVED.value
    assert moved.override is not None


def test_pause_symbol_records_manual_override_state():
    identity = normalize_source_symbol("binance_coinm", {
        "symbol": "BTCUSD_PERP",
        "pair": "BTCUSD",
        "contractType": "PERPETUAL",
        "contractStatus": "TRADING",
        "baseAsset": "BTC",
        "quoteAsset": "USD",
        "marginAsset": "BTC",
    })
    moved = apply_override(
        SymbolStateRecord(identity=identity),
        SymbolOverride(action=ManualOverride.PAUSE_SYMBOL.value, reason="maintenance_window"),
    )

    assert moved.state == SymbolState.MANUAL_OVERRIDE.value

