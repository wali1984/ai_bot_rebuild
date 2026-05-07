from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.paper_mode import (
    PAPER_MODE_LIVE_BLOCKED,
    PAPER_MODE_PAPER,
    PaperModeFlag,
)
from .errors import PaperModeServiceError


_ALLOWED_REQUESTED_MODES = frozenset({PAPER_MODE_PAPER, PAPER_MODE_LIVE_BLOCKED})


def assemble_paper_mode_flag(
    *,
    requested_mode: str,
    now_ms_clock: Callable[[], int],
) -> PaperModeFlag:
    if type(requested_mode) is not str:
        raise PaperModeServiceError("must_be_str", field="requested_mode")
    if not callable(now_ms_clock):
        raise PaperModeServiceError("must_be_callable", field="now_ms_clock")
    if requested_mode not in _ALLOWED_REQUESTED_MODES:
        raise PaperModeServiceError(
            "paper_mode_service_unrecognized_requested_mode",
            field="requested_mode",
        )

    now_ms = now_ms_clock()
    if isinstance(now_ms, bool) or type(now_ms) is not int:
        raise PaperModeServiceError("must_be_int", field="now_ms_clock")
    if now_ms < 0:
        raise PaperModeServiceError("must_be_nonnegative", field="now_ms_clock")

    if requested_mode == PAPER_MODE_PAPER:
        flag_mode = PAPER_MODE_PAPER
    elif requested_mode == PAPER_MODE_LIVE_BLOCKED:
        flag_mode = PAPER_MODE_LIVE_BLOCKED
    else:
        raise PaperModeServiceError(
            "paper_mode_service_unrecognized_requested_mode",
            field="requested_mode",
        )

    return PaperModeFlag(
        mode=flag_mode,
        flag_emitted_ts_ms=now_ms,
        live_blocked=True,
    )
