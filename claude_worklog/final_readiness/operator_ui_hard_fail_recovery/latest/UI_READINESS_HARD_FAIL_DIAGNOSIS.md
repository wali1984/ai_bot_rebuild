UI_READINESS_HARD_FAIL_DIAGNOSIS

Diagnosis: previous UI readiness was insufficient for operator acceptance.

Why previous markers were insufficient:
- A READY marker without browser screenshots did not prove the actual route rendered the intended cockpit.
- Root redirect alone only changed where the browser landed; it did not make the operator surface useful.
- Additive CSS/design tokens alone left the app feeling like old payload/proof pages.
- The operator truth payload alone did not solve visual hierarchy or page usefulness.
- Mission Control must visually match the Claude Design command-cockpit direction while preserving real V2 payload truth.
- Every route must either provide useful current evidence or state the exact evidence gap and next source/task.
- A text-dump cockpit is not acceptable for operator safety.

Superseded evidence:
- Earlier visual READY markers are retained as history but superseded for UI acceptance by this hard-fail recovery packet.
- Browser screenshot evidence is now required before this UI lane can be called READY.

Safety:
- This diagnosis does not approve live trading.
- Live trading remains `blocked_human_only`.
- Redis trim remains deferred/non-blocking.
