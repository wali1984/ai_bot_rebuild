from v2.backend.app.domain.paper_execution_ledger import (
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
    PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT,
    PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED,
    PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
)


def test_reason_constants_lowercase_and_unique() -> None:
    values = (
        PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
        PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
        PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED,
        PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
        PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT,
    )
    assert all(isinstance(value, str) and value for value in values)
    assert all(value == value.lower() for value in values)
    assert len(set(values)) == 5
