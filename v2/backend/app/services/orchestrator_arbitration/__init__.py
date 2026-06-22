"""V2 orchestrator arbitration service package.

PaperOnly orchestrator arbitration primitives ported from the legacy
``rl/orchestrator_worker.py`` / ``rl/proposal_bus.py`` /
``rl/tradeplan_orchestrator.py`` / ``rl/intent_engine.py`` family. These
modules implement deterministic, paper-only arbitration scoring, signal
schema validation, deconflict, and stream routing metadata; they do not
import any Redis client, exchange SDK, or perform any network IO.

Public exports:
  - :class:`Proposal` / :func:`score_proposal`
  - :class:`V2Signal` / :func:`validate_signal`
  - :func:`deconflict_signals` / :class:`DeconflictResult`
  - :class:`StreamRouter`
  - :class:`OrchestratorArbitrationService`

Hard invariants (verified by tests):
  - ``live_gate == "blocked_human_only"``
  - ``live_symbols == []``
  - ``approves_live is False``
  - No forbidden exchange-mutation substrings in source.
"""
from __future__ import annotations

from .deconflict import (
    DECONFLICT_REASON_AGREE,
    DECONFLICT_REASON_CONFIDENCE_TIE_BREAK,
    DECONFLICT_REASON_DOMINANT_SIDE,
    DECONFLICT_REASON_EMPTY,
    DECONFLICT_REASON_MISSING_EVIDENCE,
    DeconflictResult,
    deconflict_signals,
)
from .proposal import Proposal, score_proposal
from .service import OrchestratorArbitrationService
from .signal_schema import V2Signal, validate_signal
from .stream_routing import StreamRouter

__all__ = (
    "DECONFLICT_REASON_AGREE",
    "DECONFLICT_REASON_CONFIDENCE_TIE_BREAK",
    "DECONFLICT_REASON_DOMINANT_SIDE",
    "DECONFLICT_REASON_EMPTY",
    "DECONFLICT_REASON_MISSING_EVIDENCE",
    "DeconflictResult",
    "OrchestratorArbitrationService",
    "Proposal",
    "StreamRouter",
    "V2Signal",
    "deconflict_signals",
    "score_proposal",
    "validate_signal",
)
