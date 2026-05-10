# 12H Runtime Monitor Plan

Prepared read-only monitor output directory.

The monitor may sample Redis with SCAN/TYPE/XLEN/XREVRANGE/GET/HGETALL/TTL only.
It must not use DEL/XDEL/XTRIM/SET/HSET/XADD/FLUSHALL/FLUSHDB.
Status: prepared, not completed.

12H_RUNTIME_MONITOR_PLAN_READY
