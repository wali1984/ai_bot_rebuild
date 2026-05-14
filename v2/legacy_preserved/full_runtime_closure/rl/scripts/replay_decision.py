"""
Replay a decision from signals:trading using its stream ID.

Usage:
    python -m rl.scripts.replay_decision --id <stream-id>
"""
import argparse
import json

try:
    from utils.redis_client import get_redis
except Exception:
    get_redis = None  # type: ignore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True, help="Stream entry ID to replay")
    args = parser.parse_args()

    rc = get_redis() if get_redis else None
    if rc is None:
        print("redis unavailable")
        return 1

    entries = rc.xrange("signals:trading", min=args.id, max=args.id)
    if not entries:
        print("not found")
        return 1

    _, fields = entries[0]
    raw = fields.get(b"data") or fields.get("data")
    if not raw:
        print("no data field")
        return 1
    payload = json.loads(raw if isinstance(raw, str) else raw.decode())
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
