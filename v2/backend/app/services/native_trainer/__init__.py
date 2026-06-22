"""V2 native trainer dataset + baseline model package (paper/shadow only).

Honest framing:

* This package builds a V2-native training / evaluation dataset from
  V2-owned evidence (features, TA, OHLCV, predictions, risk decisions,
  replay-outcome bundles, edge metrics, altdata) and trains / evaluates
  a small paper/shadow baseline model.
* The baseline model is NEVER claimed to be production-ready, never
  claimed to be checkpoint-compatible with the legacy trainer, never
  used to weaken the paper-fill gate, and never used to approve live,
  canary, legacy shutdown, or Redis trim.
* Allowed ``trainer_source`` values for any prediction emitted here:
  ``V2_NATIVE_BASELINE_PAPER_SHADOW`` or ``V2_NATIVE_CONTRACT_ONLY``.
* Forbidden ``trainer_source`` values: ``V2_NATIVE_TRAINER_READY``,
  ``V2_NATIVE_TRAINER_ACTIVE``.
"""
