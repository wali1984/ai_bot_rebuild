from v2.backend.app.composition import trainer_worker_health as package
from v2.backend.app.composition.trainer_worker_health import (
    TrainerWorkerHealthCompositionError,
    TrainerWorkerHealthEvaluator,
    build_trainer_worker_health_evaluator,
)


def test_public_surface():
    assert package.__all__ == (
        "build_trainer_worker_health_evaluator",
        "TrainerWorkerHealthEvaluator",
        "TrainerWorkerHealthCompositionError",
    )
    assert package.build_trainer_worker_health_evaluator is build_trainer_worker_health_evaluator
    assert package.TrainerWorkerHealthEvaluator is TrainerWorkerHealthEvaluator
    assert package.TrainerWorkerHealthCompositionError is TrainerWorkerHealthCompositionError
