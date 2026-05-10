# Live Gate And Boundary Stops

Final live trading and real exchange capital activation remain human-only.

Additional explicit boundary approvals remain required for destructive or
safety-sensitive actions that are not ordinary safe non-live rebuild work:

- Redis trim/delete/write
- legacy mutation
- live service restart
- exchange order/cancel
- leverage/margin/position mode change
- deployment
- secret handling changes

Current Phase 3H Redis trim is blocked because the exact approval file is not
present.
