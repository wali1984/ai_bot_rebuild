def test_public_surface():
    import v2.backend.app.composition.trainer_parity as package
    from v2.backend.app.composition.trainer_parity import __all__
    from v2.backend.app.composition.trainer_parity.errors import (
        TrainerParityCompositionError,
    )
    from v2.backend.app.composition.trainer_parity.runtime import (
        TrainerLivenessEvaluator,
        build_trainer_liveness_evaluator,
    )

    assert __all__ == (
        "build_trainer_liveness_evaluator",
        "TrainerLivenessEvaluator",
        "TrainerParityCompositionError",
    )
    assert package.build_trainer_liveness_evaluator is build_trainer_liveness_evaluator
    assert package.TrainerLivenessEvaluator is TrainerLivenessEvaluator
    assert package.TrainerParityCompositionError is TrainerParityCompositionError
