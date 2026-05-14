# -*- coding: utf-8 -*-
"""
Asjad trader entrypoint (Jan6)
==============================

This file is intentionally a THIN WRAPPER to guarantee that primary + asjad traders
run the *same* implementation and cannot drift.

- Shared implementation: `trading/trader.py`
- Differences are configured only via env:
  - TRADER_ACCOUNT_ID=asjad
  - TRADER_LOG_FILE=logs/trader-asjad.log

NOTE:
- Any logic changes made in `trading/trader.py` automatically apply to Asjad.
- Do NOT duplicate trading/hedging logic in this file.
- If you need per-process overrides (e.g., different hedge opener policy),
  set env vars before launching this process (example: `HEDGE_OPEN_POLICY=...`).
"""

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path when this file is executed directly.
# When running `python trading/trader-asjad.py`, Python sets sys.path[0] to the
# `trading/` directory, which breaks `import trading.*` unless we add the parent.
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def main():
    os.environ.setdefault("TRADER_ACCOUNT_ID", "asjad")
    os.environ.setdefault("ACCOUNT_ID", "asjad")  # backward compatible with trading/trader.py main()
    os.environ.setdefault("TRADER_LOG_FILE", "logs/trader-asjad.log")

    # Import after env is set so logging + account_id are correct.
    from trading.trader import main as shared_main  # runtime import is intentional

    return shared_main()


if __name__ == "__main__":
    main()


