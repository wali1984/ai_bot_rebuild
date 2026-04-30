# 04 Dashboard Extension Plan

## Objective
Extend dashboard for continuous packet-aware operations while remaining read-only.

## New panels
1. Packet readiness
   - hourly packet ready: yes/no
   - daily packet ready: yes/no
   - active alert packet: yes/no
2. Latest alert
   - class/severity
   - component
   - first seen / last seen
3. Attribution completeness
   - signal attribution completeness %
   - execution lineage completeness %
4. Feature visibility
   - classification (partial/complete/missing)
5. Trainer prediction health
   - prediction stream status
   - gap age
6. Redis memory trend
   - current ratio
   - trend arrow
   - threshold band

## Rendering rules
- Refresh default every 15 seconds.
- Show explicit verification command for each alert tile.
- Use read-only command execution only.

## Compatibility
- Preserve current sections (monitor status, progress, Redis/system/PIA).
- Add new sections below existing output to avoid breaking operator habits.
