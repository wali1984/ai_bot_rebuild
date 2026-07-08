"""Legacy TA alias map shared by flat-hash adapters and tests."""

from __future__ import annotations

LEGACY_ALIAS_MAP: dict[str, tuple[str, ...]] = {
    "RSI": ("ta_RSI", "ta_RSI_14", "rsi", "rsi_14"),
    "MACD": ("ta_MACD_macd", "ta_MACD", "macd"),
    "MACD_SIGNAL": ("ta_MACD_signal", "macd_signal"),
    "MACD_HIST": ("ta_MACD_hist", "macd_hist"),
    "BB_UPPER": ("ta_BBANDS_20_upper", "ta_BBANDS_upperband", "bb_upper"),
    "BB_MIDDLE": ("ta_BBANDS_20_middle", "ta_BBANDS_middleband", "bb_middle"),
    "BB_LOWER": ("ta_BBANDS_20_lower", "ta_BBANDS_lowerband", "bb_lower"),
    "ATR": ("ta_ATR", "ta_ATR_14", "atr_14", "atr"),
    "NATR": ("ta_NATR", "ta_NATR_14", "natr"),
    "EMA": ("ta_EMA", "ta_EMA_20", "ema_20", "ema"),
    "EMA_50": ("ta_EMA_50", "ema_50"),
    "EMA_200": ("ta_EMA_200", "ema_200"),
    "SMA": ("ta_SMA", "ta_SMA_20", "sma_20", "sma"),
    "SMA_50": ("ta_SMA_50", "sma_50"),
    "VWAP": ("ta_VWAP", "vwap"),
    "ADX": ("ta_ADX", "ta_ADX_14", "adx"),
    "OBV": ("ta_OBV", "obv"),
    "MFI": ("ta_MFI", "ta_MFI_14", "mfi"),
    "STOCH": ("ta_STOCH_slowk", "ta_STOCH_k", "stoch_k"),
    "STOCH_D": ("ta_STOCH_slowd", "ta_STOCH_d", "stoch_d"),
    "CCI": ("ta_CCI", "ta_CCI_14", "cci"),
    "WILLR": ("ta_WILLR", "willr"),
    "MOM": ("ta_MOM", "mom"),
    "ROC": ("ta_ROC", "roc"),
    "TRANGE": ("ta_TRANGE", "trange"),
    "SAR": ("ta_SAR", "sar"),
    "AROON_UP": ("ta_AROON_up", "ta_AROON_aroonup"),
    "AROON_DOWN": ("ta_AROON_down", "ta_AROON_aroondown"),
    "ULTOSC": ("ta_ULTOSC",),
    "TRIX": ("ta_TRIX",),
}

MIN_REQUIRED_FIELDS = 160
