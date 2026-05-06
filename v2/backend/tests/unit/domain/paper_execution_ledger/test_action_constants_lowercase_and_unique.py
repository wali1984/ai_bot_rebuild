from v2.backend.app.domain.paper_execution_ledger import (
    PAPER_LEDGER_ACTION_RECORD_ALLOW,
    PAPER_LEDGER_ACTION_RECORD_DENY,
)


def test_action_constants_lowercase_and_unique() -> None:
    values = (PAPER_LEDGER_ACTION_RECORD_ALLOW, PAPER_LEDGER_ACTION_RECORD_DENY)
    assert all(isinstance(value, str) and value for value in values)
    assert all(value == value.lower() for value in values)
    assert len(set(values)) == 2
