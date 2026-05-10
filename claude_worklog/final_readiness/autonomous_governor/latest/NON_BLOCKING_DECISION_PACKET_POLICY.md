# Non-Blocking Decision Packet Policy

Non-live approval or decision packets do not block the global queue. They remain
local subtasks with `waiting_decision_packet` or `delegated_decision_pending`
state while the governor selects unrelated safe work.

Final live/capital actions are different: they remain hard-stop human gates.
