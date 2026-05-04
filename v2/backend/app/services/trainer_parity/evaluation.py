from __future__ import annotations

from dataclasses import dataclass

from v2.backend.app.domain.liveness_stream_growth import StreamIdObservation
from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot


@dataclass(frozen=True, slots=True)
class TrainerLivenessEvaluation:
    snapshot: LivenessSignalSnapshot
    prediction_history: tuple[StreamIdObservation, ...]
    proposal_history: tuple[StreamIdObservation, ...]
