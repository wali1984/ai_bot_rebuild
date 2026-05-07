from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.paper_mode import PaperModeFlag
from v2.backend.app.services.paper_mode import assemble_paper_mode_flag
from .errors import PaperModeRuntimeCompositionError


class PaperModeRuntime:
    __slots__ = ("paper_mode_now",)

    def __init__(
        self,
        *,
        paper_mode_now: Callable[..., PaperModeFlag],
    ) -> None:
        self.paper_mode_now = paper_mode_now


def build_paper_mode_runtime(
    *,
    now_ms_clock: Callable[[], int],
) -> PaperModeRuntime:
    if not callable(now_ms_clock):
        raise PaperModeRuntimeCompositionError(
            "must_be_callable",
            field="now_ms_clock",
        )

    _now_ms_clock = now_ms_clock

    def _paper_mode_now(*, requested_mode: str) -> PaperModeFlag:
        return assemble_paper_mode_flag(
            requested_mode=requested_mode,
            now_ms_clock=_now_ms_clock,
        )

    return PaperModeRuntime(paper_mode_now=_paper_mode_now)
