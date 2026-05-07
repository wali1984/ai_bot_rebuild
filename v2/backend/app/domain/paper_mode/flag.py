from __future__ import annotations

from dataclasses import dataclass

from .errors import PaperModeDomainError


PAPER_MODE_PAPER = "paper"
PAPER_MODE_LIVE_BLOCKED = "live_blocked"

_ALLOWED_MODES = frozenset({PAPER_MODE_PAPER, PAPER_MODE_LIVE_BLOCKED})


@dataclass(frozen=True, slots=True)
class PaperModeFlag:
    mode: str
    flag_emitted_ts_ms: int
    live_blocked: bool

    def __post_init__(self) -> None:
        if not isinstance(self.mode, str):
            raise PaperModeDomainError(
                "paper_mode_flag_unknown_mode",
                field="mode",
            )
        if self.mode not in _ALLOWED_MODES:
            raise PaperModeDomainError(
                "paper_mode_flag_unknown_mode",
                field="mode",
            )

        if isinstance(self.flag_emitted_ts_ms, bool) or not isinstance(
            self.flag_emitted_ts_ms,
            int,
        ):
            raise PaperModeDomainError(
                "paper_mode_flag_emitted_ts_ms_must_be_non_negative_int",
                field="flag_emitted_ts_ms",
            )
        if self.flag_emitted_ts_ms < 0:
            raise PaperModeDomainError(
                "paper_mode_flag_emitted_ts_ms_must_be_non_negative_int",
                field="flag_emitted_ts_ms",
            )

        if not isinstance(self.live_blocked, bool):
            raise PaperModeDomainError(
                "paper_mode_flag_requires_live_blocked_true",
                field="live_blocked",
            )
        if self.live_blocked is not True:
            raise PaperModeDomainError(
                "paper_mode_flag_requires_live_blocked_true",
                field="live_blocked",
            )
