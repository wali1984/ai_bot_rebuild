# Expected Memory Reduction

The estimate is intentionally conservative because Redis stream memory
reclamation depends on internal stream/listpack layout.

- Current target memory usage: 12729.587 MiB
- Current target stream length: 70930876
- Phase 3F exported count: 70930810
- Current entries after export anchor or growth window: 66
- Proposed cutoff: `1777222885206-0`
- Estimated trim floor: 65930810 entries
- Estimated memory reduction: 10183.669 MiB
- Estimated total Redis used memory after trim: 2668.153 MiB
- Estimated total Redis maxmemory utilization after trim: 16.285%

Post-trim validation must treat these numbers as estimates and verify with
`MEMORY USAGE liquidations:events` and `INFO memory`.
