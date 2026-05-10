from v2.backend.app.composition.provenance_dedupe_attribution import (
    build_provenance_dedupe_attribution_runtime,
)
from v2.backend.app.domain.provenance_dedupe_attribution import DEDUPE_NEW

from v2.backend.tests.unit.domain.provenance_dedupe_attribution._fixtures import (
    TRAINER_FIELDS,
    risk_record,
)


def test_runtime_dedupe_decision_now_invokes_clock_zero_times_per_call() -> None:
    calls = 0

    def clock() -> int:
        nonlocal calls
        calls += 1
        return 999

    runtime = build_provenance_dedupe_attribution_runtime(now_ms_clock=clock)
    runtime.dedupe_decision_now(
        upstream_record=risk_record(),
        dedupe_state=DEDUPE_NEW,
        duplicate_of_decision_id=None,
        dedupe_reason="first_seen",
        trainer_model_version=TRAINER_FIELDS["model_version"],
        trainer_checkpoint_id=TRAINER_FIELDS["checkpoint_id"],
        trainer_confidence_raw=TRAINER_FIELDS["confidence_raw"],
        trainer_confidence_calibrated=TRAINER_FIELDS["confidence_calibrated"],
        trainer_worker_liveness=TRAINER_FIELDS["trainer_worker_liveness"],
    )
    assert calls == 0
