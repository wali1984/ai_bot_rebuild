# Phase 2X Test Plan

Domain tests cover both valid flag states, invalid flag states, record construction for quarantined and not-present flags, `live_blocked` rejection, public surface, and no Redis/FastAPI import side effects.

Service tests cover record assembly for both flags, rejection of non-record and non-flag inputs, keyword-only invocation, Phase 2V trainer-parity propagation, public surface, and no Redis/FastAPI import side effects.

Composition tests cover runtime construction, no build-time clock invocation, exactly one clock invocation per runtime call, keyword-only runtime calls, callable clock validation, public surface, and no Redis/FastAPI import side effects.

PHASE_2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_TEST_PLAN_READY
