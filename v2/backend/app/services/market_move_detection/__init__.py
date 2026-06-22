"""Paper-only market move detection helpers."""

from .breakout_squeeze import detect_breakout_squeeze
from .contracts import BreakoutSqueezeSignal, CandleInput, DetectionContext

__all__ = [
    "BreakoutSqueezeSignal",
    "CandleInput",
    "DetectionContext",
    "detect_breakout_squeeze",
]
