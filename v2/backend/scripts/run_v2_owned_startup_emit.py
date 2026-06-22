"""Helper: emit the v2_owned_non_live_startup public payload."""
from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.cli.v2_owned_non_live_startup import (
    DEFAULT_PAYLOAD_PATH,
    build_payload,
)


def main() -> int:
    payload = build_payload()
    dest = DEFAULT_PAYLOAD_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        "wrote",
        dest,
        "go_no_go",
        payload["go_no_go"],
        "any_unsafe_live_field",
        payload["any_unsafe_live_field"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
