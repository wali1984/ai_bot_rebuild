from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from risk.halt_manager import HaltManager


@dataclass
class Violation:
    code: str
    msg: str
    fields: Dict[str, Any]


class AssertGovernor:
    """Legacy wrapper for backward compatibility. Uses risk.assertions + HaltManager."""

    def __init__(self, redis_client, telegram=None, account_id: str = "primary", kill_key: str = "wma:kill_switch"):
        self.redis = redis_client
        self.telegram = telegram
        self.account_id = str(account_id or "primary").strip().lower()
        self.kill_key = kill_key
        self._halt = HaltManager(redis_client, telegram=telegram, account_id=self.account_id)

    def is_halted(self) -> Tuple[bool, Optional[Dict[str, Any]]]:
        return self._halt.is_halted()

    def check_invariants(self, *args, **kwargs) -> Optional[Violation]:
        return self._halt.check_invariants(*args, **kwargs)

    def halt(self, violation: Violation, *args, **kwargs) -> Dict[str, Any]:
        return self._halt.halt(violation, *args, **kwargs)
