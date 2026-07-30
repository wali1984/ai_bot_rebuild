# Permanent Recovery Day-Long Run Closeout

Generated: 2026-07-28T17:31:40.254476Z  
Mode: CLOSEOUT_AND_HANDOFF  
Authority: exact repository and runtime snapshot; no readiness promotion  
Final classification: RUNTIME_ACCEPTANCE_PASS_ECONOMIC_ACCEPTANCE_PENDING_LIVE_NO_GO

## Executive truth

The controlled engineering run is stopped. The natural adaptive paper lifecycle,
restart reconstruction, accounting reconciliation, two post-close cycles,
candidate-outcome runtime, authenticated composite dataset and bounded escalation
dispatcher are proven. Permanent recovery is not complete: the frozen natural
economic cohort contains 1 of the required 5 closes, G03 has not been recomputed
on a complete cohort, G11/G13/G14 remain red, the current boot-validator oneshot
is failed, and no superior challenger has been activated.

The escalation runtime started from repository HEAD during the final bounded
attempt and was stopped on the closeout directive. Its timer is inactive. It did
not promote its partial build, did not write a model registry candidate, and did
not change the active generation-3 checkpoint. The interrupted non-authoritative
build remains at:

~~~
/home/wali/ai_bot_local_data/adaptive_candidate_dataset_v3/.release_build__zrpx813
~~~

It contains a 172,786,062-byte dataset, 7,194,946-byte manifest, 712-byte parity
report and 3,295-byte signed receipt. It must not be consumed as a release.

## 1. Repository state

- Branch: codex/pipeline-trust-refresh
- HEAD: 85c9bb86591011639b483a88bf25587432ecfaf4
- Upstream relation at snapshot: ahead of origin/codex/pipeline-trust-refresh by 92
- Goal commit window: 2026-07-27T17:33:10Z through closeout
- Commits visible on the branch in that window: 183
- Note: the list is a branch-time-window ledger. It includes commits made by
  other concurrent actors, including unrelated iOS work, and is not a claim
  that Codex authored every listed commit.

The status immediately before the two authorized closeout writes was:

~~~text
## codex/pipeline-trust-refresh...origin/codex/pipeline-trust-refresh [ahead 92]
 M .claude/hooks/block_dangerous.sh
~~~

Final uncommitted ownership:

| File | State | Owner |
|---|---|---|
| .claude/hooks/block_dangerous.sh | modified before this goal; preserved and never edited during this run | operator/user |
| claude_worklog/codex/PERMANENT_RECOVERY_DAY_LONG_RUN_CLOSEOUT.md | closeout artifact | Codex closeout |
| goal_state/PERMANENT_SYSTEM_RECOVERY/RECOVERY_STATUS.json | truth correction and closeout pointer | Codex closeout |

No unrelated untracked file was removed or changed during closeout.
RECOVERY_STATUS.json is covered by the repository's goal_state/*/ ignore rule,
so Git does not report it even though the requested on-disk artifact was updated.

### Deployed versus repository-only commits

Running immutable processes use only these repository commits:

- canonical serving: 250ad83ef1d187a2f20a3bf5e32a80ff410c0ff9
- paper loop: 27635258e87ba434c2c001887337db31972f1969
- candidate-outcome publisher: 879fd2e71f8212d35debc0d6e81f9b4580c79e03
- candidate-outcome calibration: 82700c83e0a6de8f4f504c55b19af9574e9be6a4
- full TA-Lib loop and strategy-supply publisher: 3d65aa9cc81247b0e8938f2498a6320b7bdf0605

Inactive configured units reference f12bce1229b0f157b92089c71f1774caace1c4c5
(gen-5 backfill) and 7700414a4bca1df6a4964a587d5d22455ab40841
(adaptive shadow). HEAD 85c9bb86591011639b483a88bf25587432ecfaf4 is
configured in the stopped/failed escalation oneshot but no process from it is
running. All other commits in the appendix are repository-only unless named
above.

### Complete branch commit ledger, oldest to newest

~~~text
0980e692107a8cf4c436a5f66fd7bd45c7042ba1	2026-07-27T14:15:07-04:00	Wali	Define adaptive policy action v2 contract
44f1dace201eed25e93197c44a52f855f913c811	2026-07-27T14:15:41-04:00	Wali	Add deterministic trading authority inventory scanner
34e5137bfa418f45b00edcbcdd4123ed80563853	2026-07-27T14:23:27-04:00	Wali	FINAL PASS: AdaptivePolicyActionV2 + CandidateDecisionOutcomeV2 + escalation ladder
658d6fc760cabeef92f856bae5ccb34462693d56	2026-07-27T14:24:55-04:00	Wali	Remove duplicate adaptive action contract
31f0ca56756485953f7aed60ac1a74dbf6ae49ed	2026-07-27T14:27:02-04:00	Wali	FINAL PASS: venue-aware bounded exploration sizing (FP-130 / Phase 12)
2934dcff3196eeb1d4b418f2f67e88cff07c5439	2026-07-27T14:34:39-04:00	Wali	Define calibrated component estimate shadow contract
5ce083874d3d11f889edd191c2937716d92630ba	2026-07-27T14:38:57-04:00	Wali	Enforce component estimate physical domains
563f3d757aa2553c83079854bb582ee3d5c5f692	2026-07-27T14:38:57-04:00	Wali	Harden venue minimum exploration proposal
5ce5903084983ddccad1a65f779b060aa8ac14cf	2026-07-27T14:43:05-04:00	Wali	Make exploration sizing decimal-context invariant
79681b8a98e0ade4bbb82872818cf3663833e389	2026-07-27T14:43:05-04:00	Wali	Define evidence-fitted adaptive objective shadow
2b7442e61a4de9d1e929ac299073ca2591e48dac	2026-07-27T14:44:28-04:00	Wali	Complete exact exploration arithmetic isolation
2170d4a533f6000f485f8f86522a982b557c9e2c	2026-07-27T14:55:06-04:00	Wali	FINAL PASS: repair corpus contract — importer emits rich serving-compatible label binding (Phase 7 / FP-080)
46915ad447fbd9b590e8158291a6206192e82ea8	2026-07-27T14:59:47-04:00	Wali	FINAL PASS: data-utilization funnel telemetry (Phase 7 / FP-080)
d12f418d3de92f36b828046a216c57a14bcaebe7	2026-07-27T15:09:56-04:00	Wali	Harden adaptive objective evidence boundary
0a29fe7deb63da0d275faf89d39a64a47eeb2c2d	2026-07-27T15:10:31-04:00	Wali	Record final pass objective foundation status
3f138f17e88f7cfe7494bf46a700ccf7f7c82d88	2026-07-27T15:13:55-04:00	Wali	Improve trading configuration inventory coverage
75c735036b9299506258bce917247fde38076472	2026-07-27T15:15:13-04:00	Wali	Record phase one scanner progress
289bb9911f51e277b66c9cf2c449bf78d2802251	2026-07-27T15:37:08-04:00	Wali	Harden candidate outcome evidence contract
1bf996bf9ba34ec8f07afaf620cb4a46934ad18f	2026-07-27T15:38:14-04:00	Wali	Record candidate outcome contract progress
ad7d7015965a63fb8c6d5aaf0fae3a0a2429d1f8	2026-07-27T15:47:21-04:00	Wali	FINAL PASS: durable snapshot-based gen-5 backfill + per-row proof currency (Phase 7)
619902c4ae923bb0f3c648e1e60a0192efd56441	2026-07-27T15:49:56-04:00	Wali	gen5 backfill: use fresh challenger archive for immutable-snapshot import
f12bce1229b0f157b92089c71f1774caace1c4c5	2026-07-27T16:00:05-04:00	Wali	Harden generation 5 snapshot backfill
db7ddeeadf043a7b8f21ab046e86fb812a4c812e	2026-07-27T16:04:26-04:00	Wali	Add authenticated candidate outcome archive
fc4535c5ec4096520336f8142a582384f0b4edcc	2026-07-27T16:06:44-04:00	Wali	Keep decision groups intact across dataset splits
d01b25820b62dd590fca91a3aa06742cfd3aa95b	2026-07-27T16:10:48-04:00	Wali	Add exact generation 5 corpus reconciliation
ad65cd0e31e489726da858828e68df331e111ca3	2026-07-27T16:24:34-04:00	Wali	Add exact candidate outcome cycle publisher
7bafe70fa30375bf3148143f14aa18d9b232abd4	2026-07-27T16:29:07-04:00	Wali	Run signed candidate outcome publisher
761e6769c5d1d02009e8d8498080034b048dedc1	2026-07-27T16:29:47-04:00	Wali	Add candidate outcome publisher service
35cf783aa71b905e6f112b6316c823c2a444e0e2	2026-07-27T16:32:19-04:00	Wali	Bind candidate snapshots by point in time
6c16c308ff2df3c64a1862a7ac78e9c15c379722	2026-07-27T16:32:48-04:00	Wali	Deploy candidate outcome publisher release
b8741e38961e978b65199750b2576332d3b14ae4	2026-07-27T16:34:03-04:00	Wali	FINAL PASS: gen-5 backfill reconciliation tool (Phase 7 step 1)
4e0005eb9d71375162db91848031ed445d07dcae	2026-07-27T16:35:12-04:00	Wali	FINAL PASS: gen-5 dataset build + gen-4 comparison tool (Phase 7 step 3)
6a828966578c9406c0fa7175bfe2185a62f48957	2026-07-27T16:37:00-04:00	Wali	Compact verified candidate portfolio evidence
e3a5cf2588bc290765e53e5edad8d1f05e8a0c85	2026-07-27T16:37:28-04:00	Wali	Deploy compact candidate outcome release
38954fb2cf0b8e3807238a79e33375ee4f785701	2026-07-27T16:45:43-04:00	Wali	Add verified candidate outcome maturation
0db2e209a44f3316535a835568f1908517041bdb	2026-07-27T16:48:58-04:00	Wali	Integrate candidate outcome maturation runtime
d416c4a7cd82ce043101ca25d12c1158a8478f71	2026-07-27T16:49:44-04:00	Wali	Deploy candidate outcome maturation release
8164dea0fe47d4a7d7efcea5b506c5ca5e631739	2026-07-27T16:58:17-04:00	Wali	Reconcile gen5 rejection sequences exactly
4376cd2497ac32adf2a1cf0517237408cbe849a0	2026-07-27T17:06:21-04:00	Wali	gen5 reconcile: correct identity (unique rejected != reason-occurrences)
597c4c229906cf497df45c051b3133576de05d6d	2026-07-27T17:17:56-04:00	Wali	Bind gen5 label proof and regime coverage
7e8ec6c21f9f5cc05601c72ad288a284b2ee9cc2	2026-07-27T17:24:04-04:00	Wali	Separate selected action venue feasibility
9885d416a8b10e30c32e264012df894513cef470	2026-07-27T17:35:35-04:00	Wali	Fit adaptive calibration from matured candidates
1936342266ed7410ff39e45cbdc1d3908c38c2ea	2026-07-27T17:49:18-04:00	Wali	Mature flat candidates with incremental label proofs
229ada632dff3e0ff2f1e10720d5db0ac4687a40	2026-07-27T17:53:57-04:00	Wali	Publish candidate outcome calibration at runtime
7be57c45ae66fe140ee4d2ddaca854ec65f2e9fa	2026-07-27T18:12:37-04:00	Wali	Fit and verify adaptive shadow policy decisions
9e255b5fb538ec383fb26519716117c264cf039b	2026-07-27T18:14:08-04:00	Wali	Use expected risk contributions in adaptive objective
8085986ad7a357d83ec54aacc77cdaa344faafaf	2026-07-27T18:22:30-04:00	Wali	Persist adaptive policy shadow decisions
2e44c3b711ba7167b5fc45256c30efe28853f389	2026-07-27T18:23:36-04:00	Wali	Deploy adaptive policy shadow evaluator unit
d03ca51749706351bc6f58576a49fc827c6cd651	2026-07-27T18:30:19-04:00	Wali	Bind adaptive execution to exact cost evidence
40f5db3e6e0c4fe6729ddb19804ff0a80790e923	2026-07-27T18:31:14-04:00	Wali	Deploy exact-cost adaptive shadow runtime
f0be8a756b608b3ff908e1561915b4724ded24bd	2026-07-27T18:35:50-04:00	Wali	Authorize exact adaptive paper policy actions
1729eb11e328c36c620859821280ba219572c559	2026-07-27T18:41:05-04:00	Wali	Validate exact adaptive paper allocations
350ecccbe0722ba18cfd7dabe7c0772612a5f0e3	2026-07-27T19:00:31-04:00	Wali	Cut over adaptive paper policy authority
398b0c95a3bacb9659b130435c300d7496ef36ae	2026-07-27T19:03:27-04:00	Wali	FINAL PASS: effective corpus-diversity analysis (step 8)
af7f83026c6b200444e8cedf25f1550d93ef5742	2026-07-27T19:10:06-04:00	Wali	Repair adaptive paper execution binding
44ce24d7d9f4e9d3744703286f4d51db495e77a6	2026-07-27T19:15:44-04:00	Wali	Bind verified adaptive feature evidence
ac281f86e5ff35e045b5ab44f36d91488c54da1a	2026-07-27T19:35:49-04:00	Wali	Complete adaptive paper final admission cutover
088a2030cc67c1a9a710dfe13492fdac27709988	2026-07-27T19:41:37-04:00	Wali	Separate candidate mark valuation from execution notional
a41732009adb05a7178f8633c35a6b2c2b87a755	2026-07-27T19:50:20-04:00	Wali	Repair paper restart clocks and open margin evidence
a916a9c370d23ec6bf0ed2fc85a2e55299ca4c78	2026-07-27T19:54:32-04:00	Wali	FINAL PASS: operational escalation supervisor (operator #2)
f105232c74ad20b2579766c9e8f3cdee5bd76469	2026-07-27T20:01:08-04:00	Wali	Preserve economic cohort lineage through paper lifecycle
7700414a4bca1df6a4964a587d5d22455ab40841	2026-07-27T20:18:28-04:00	Wali	Keep adaptive shadow learning during open exposure
2c9324fedbe67eb8e9a80e001838ba010114c3c6	2026-07-27T20:22:37-04:00	Wali	Archive blocked candidates without reservation snapshots
8260186b4112437b9fc0324d4afdc669db1640a5	2026-07-27T20:22:51-04:00	Wali	FINAL PASS #2: point escalation RECALIBRATE rung at a real worker
0050eccd78c1e4e92618887934d422092238dfe6	2026-07-27T20:29:00-04:00	Wali	Surface authenticated open-position clock for allocation PIT
403a937a85d2b468779b3570b95360822c5acab8	2026-07-27T20:31:50-04:00	Wali	Keep candidate evidence consumers current
d5eff6fa064e89d5aa4e9b798411a8005f4656ed	2026-07-27T20:36:37-04:00	Wali	Scale authenticated candidate archive appends
86df7dcfd3977fb5afdc3feb646a942aa09aa89c	2026-07-27T20:52:40-04:00	Wali	Repair proofless paper position state atomically
909d7eb23ef74caf2cc2d8e2fae1f00af990dc1f	2026-07-27T20:59:29-04:00	Wali	Quarantine unproved adaptive paper closes
76eb64433ecb2f68af6ba182c38f364a8bdd27cf	2026-07-27T21:02:37-04:00	Wali	Join paper positions to accepted fill aliases
2931e2801e433446a4e3755292b80266d655437c	2026-07-27T21:08:55-04:00	Wali	Fix iOS release blocker: ambiguous ForEach in ProvidersView
16715a0b4b74502bede76efebd8485ffc2290c0e	2026-07-27T21:10:20-04:00	Wali	Add read-only /api/v2/adaptive/status endpoint
8a5cd6695f9a1c837cb3ecb685ae2f87deb40fa7	2026-07-27T21:12:58-04:00	Wali	Harden iOS Admin against malformed baseURL (guard force-unwrapped URLs)
113b613c5da88d69dbb898a27baa05077e5cd516	2026-07-27T21:24:26-04:00	Wali	Persist accepted fill proof with paper inventory
fc3a4a1ac96e35b0cee651e097c93797bc19fac2	2026-07-27T21:33:47-04:00	Wali	Preserve reconstructed paper unrealized PnL
4d839ed471c8a46ffddbe75d89801b87193446c7	2026-07-27T21:45:09-04:00	Wali	Reconstruct portfolio PnL from durable fill proofs
54684ea5e2df54ae8af5b8a69006788a33dc81ad	2026-07-27T21:52:34-04:00	Wali	Split microstructure integrity from market state
5a41aedb68a438ef67568b20b2881ef7c25d2573	2026-07-27T21:53:05-04:00	Wali	Separate microstructure code and runtime roots
620b6d1d5f99fb6d031d004c3b865fce7d76ecd6	2026-07-27T22:01:46-04:00	Wali	Preserve entry feature finality through paper signals
1a803f1712bbeadf1e2d9f54f2047f25e326916a	2026-07-27T22:09:33-04:00	Wali	iOS: add read-only Adaptive System screen (/api/v2/adaptive/status)
7b2cd9125a350ec4b6ad9bb840661e94dbbe459d	2026-07-27T22:19:48-04:00	Wali	Bind adaptive paper decisions to cycle receipts
228f8f1ac16f376392c48e89e2fb2008998eaf66	2026-07-27T22:25:23-04:00	Wali	Persist adaptive receipts and normalize spread clocks
420dbc82da451d521496f78342ce5a8252cf9136	2026-07-27T22:30:29-04:00	Wali	Join canonical finality into paper signal fallback
ad9ec35cbc51fca9832704fb8944e74301b6d3de	2026-07-27T22:36:12-04:00	Wali	Align serving probabilities with runtime action ABI
f77f5673d6e6f5043d437a4e4e49f468ca70843e	2026-07-27T22:46:48-04:00	Wali	iOS: qualify SwiftUI.withAnimation / SwiftUI.Animation.default for Xcode 26.4
380244762a16f5ab9f4595d903581bc412f12c60	2026-07-27T22:52:09-04:00	Wali	Enforce accepted fill position invariant
10f1cf19bef0ab0a132b27a87e84e2480b571980	2026-07-27T22:54:26-04:00	Wali	Index integrity quarantines for position removal
0f856d6f1dd079f6c4f786bbc97325e5f340844c	2026-07-27T22:59:08-04:00	Wali	Reconcile post-lifecycle reservation status
f3fc42e94af7f7700322f3835705c78df1fd5d2f	2026-07-27T23:07:52-04:00	Wali	Separate profitability confidence from action probability
426e8dd1efccb2a98d1087863de9b033f3a55ec9	2026-07-27T23:11:43-04:00	Wali	Preserve submillisecond signal decision clocks
ba21fdf7e3707f6354043f89666939987e298d52	2026-07-27T23:34:36-04:00	Wali	Separate microstructure evidence integrity from policy
6988a3f1435e989ce0c2f589d4071cda7ec28654	2026-07-27T23:43:06-04:00	Wali	Add paper-loop runtime acceptance harness (FINAL PASS #15-17)
d338f41fed8c120349c59d5d638691da3623015c	2026-07-27T23:54:31-04:00	Wali	Add CG-F063 proof-store reconciliation regression fixtures (FINAL PASS #6)
9f28179fe8e8ec4edcc5ae2d6ecc77781c39a5f8	2026-07-28T00:03:41-04:00	Wali	Add CG-F057 completion acceptance fixtures (FINAL PASS #8-10)
959ac24bdfc7478bea674ea3f013d29df54fd663	2026-07-28T00:04:01-04:00	Wali	Paper epoch reset: preflight gate tool + PaperAccountEpochV1 design (no state mutated)
7d3624d24b68a4a50e4600f957ce3d9688f903c3	2026-07-28T00:15:50-04:00	Wali	Fail closed paper proof reconciliation
3dccc1864b87d6ab29d5b1a97e92da23a2b3d56d	2026-07-28T00:17:50-04:00	Wali	Record CG-F063 implementation boundary
bad88d5409dc33c7d30a191bde235a12fe1e7d7e	2026-07-28T00:18:21-04:00	Wali	Paper epoch reset: rotation engine + 12 tests + CLIs (prestaged, no state mutated)
e8c7856f86ea19b7dead28b55608073f77193e9f	2026-07-28T00:21:47-04:00	Wali	Block unsafe paper epoch rotation
a124df529b4b7f87fa08e441892cd40e0f4553d2	2026-07-28T00:25:43-04:00	Wali	Keep adaptive policy behind hard local gates
28aada8c391adcee996035abc834d824d5c70af7	2026-07-28T00:27:08-04:00	Wali	Restore committed paper growth fixture dependency
5f9d4d993e8aaf577d88dbc4e2caee17e181aa70	2026-07-28T00:28:54-04:00	Wali	Record hard-boundary release candidate
c9869abfc3b6d8d8cc394a0404e8da11fe4e5321	2026-07-28T00:36:25-04:00	Wali	Reconcile adaptive runtime evidence
db6f19019551092d3e4b6a615f9c24af55a9562a	2026-07-28T00:37:00-04:00	Wali	Record runtime reconciliation commands
c956ec46b8686d64f52dc6b1c9757b0f740cb517	2026-07-28T00:51:17-04:00	Wali	Publish identity-scoped data utilization truth
07521bce0f7cd9b6f3d1b2576115cc4594f77822	2026-07-28T00:54:05-04:00	Wali	Record truthful phase 7 utilization status
4003720f9283f287ecba8aeee485ff0302bd778b	2026-07-28T01:08:39-04:00	Wali	Add paper first-lifecycle acceptance harness (FINAL PASS #18)
b52ab023ac5feac3a39df27e68d1a3c99ab24823	2026-07-28T01:12:08-04:00	Wali	Build serving dataset from matured candidates
cbf83b408b4f070ab50216dd9f51fcda1e04d1c9	2026-07-28T01:14:19-04:00	Wali	Measure balanced training group independence
5c69bbfd64dce95ccef148820ff8b654533494c4	2026-07-28T01:21:59-04:00	Wali	Bind matured outcomes to adaptive training evidence
307cd19feb7f24ed02229f406b5a9b1c8d9ea219	2026-07-28T01:23:44-04:00	Wali	Add partial-close proof reconciliation regression
a88bb1ca38f839394b05e1feba08501e39662c2c	2026-07-28T01:36:33-04:00	Wali	Preserve partial positions across proof reconciliation
686a22c253fcffe6459f027ab79dd7e0cc5e4dfe	2026-07-28T01:40:53-04:00	Wali	Extend partial-close proof transition fixtures
e6e4328344d44ff43dff9e259368f583cf1ae0fa	2026-07-28T01:43:21-04:00	Wali	Harden partial close proof migration
8d7926292a88d1000d6368edb15e898771854a0e	2026-07-28T01:45:39-04:00	Wali	Test partial close ancestor authority
30c80a064057673d25520893a08e0206dba55c01	2026-07-28T01:48:31-04:00	Wali	Validate every partial-close proof ancestor
7714d3188a6389ed93ceed5e376b0363bff6a4fb	2026-07-28T01:50:01-04:00	Wali	Test partial close ancestor receipt semantics
7d6764aa24bc79315a05902c2976b8750c611459	2026-07-28T01:50:40-04:00	Wali	Reject contradictory ancestor close receipts
0ebcbe0ad69c04d6fff00c5b627818840f4e00db	2026-07-28T01:50:59-04:00	Wali	Paper epoch preflight: realign to operator predicate-3 set (harness owns proof-store)
d966b325ef7f1074d8cb7a6028f06556c428ad81	2026-07-28T01:51:56-04:00	Wali	Test complete partial close receipt contract
9499d998d997bffedae3ddfc9c3ea82283c9058f	2026-07-28T01:52:44-04:00	Wali	Bind complete partial-close receipt semantics
e663136ba46915adf864169233c1848bb1025a3c	2026-07-28T01:53:41-04:00	Wali	Paper epoch: add scope_payload reader-wiring helper + test
b0a5ada3ea236c400da37f97e4b45caf9d38d505	2026-07-28T01:54:25-04:00	Wali	Test complete partial close receipt finality
1afb085891ee35576383cf112de26f421a1c374b	2026-07-28T01:55:33-04:00	Wali	Align legacy partial close receipt fixtures
c718d169032ff37833e112f7722072f1fe9a7600	2026-07-28T01:55:50-04:00	Wali	Require exact partial-close receipt state
92b489f77d87883ed54b5d72ed148a68c234f0b0	2026-07-28T01:56:51-04:00	Wali	Test required partial close receipt identity
adcfb926c4fdf7673edb7438a5ccf5f30cb26a2d	2026-07-28T01:57:27-04:00	Wali	Require durable partial-close identity
7e35132325fadc526488b9136fd5701ddf772241	2026-07-28T01:59:14-04:00	Wali	Test partial close lineage and cost binding
1744a35a3312095b94567aeaa02798a0db365444	2026-07-28T02:01:12-04:00	Wali	Align restart fixtures with cost basis contract
cf9348ba8eab753a97d6fd809a7eb0131f189c94	2026-07-28T02:01:29-04:00	Wali	Bind close lineage and remaining cost basis
6ae73c303a5c1d16ff302b7d8a3686def9be68a9	2026-07-28T02:03:54-04:00	Wali	Test ancestor cost value domain
30b20b6040fa13f84ff0413e85da71bad74dbe85	2026-07-28T02:04:55-04:00	Wali	Reject invalid partial-close cost domains
0a2bc08500354fdc870cbbb7cf1d953b5eee98c3	2026-07-28T02:06:05-04:00	Wali	Test ancestor cost chain binding
d3635a8c10ef02f0a8c553e0a7d69feb780cef60	2026-07-28T02:06:52-04:00	Wali	Bind partial-close cost transition chain
966a8e2a688dbb65370bfc9b90f051967a845c63	2026-07-28T02:23:51-04:00	Wali	Record CG-F063 runtime acceptance truth
85b5f2c34bc0c1a046d5d2500108bc0893d82eb9	2026-07-28T02:24:48-04:00	Wali	Record runtime evidence and command ledger
92622ef4e9202c5efa81b25274af756c2ef110b3	2026-07-28T02:41:59-04:00	Wali	Fix durable feature clock semantics
937c800640af86e1765cedd3c91ff226109efe08	2026-07-28T02:57:03-04:00	Wali	Fix paper microstructure read clock race
b1e2f5ac0817a683a3e41178447701cbc0348223	2026-07-28T03:13:29-04:00	Wali	Synchronize paper risk decision handoff
6a10b9ed902c58f6be46768f114ebcb765543e18	2026-07-28T03:22:32-04:00	Wali	Use post-handoff paper decision clock
01302c2fa606aa85732e8f4a4df9cad55ba30a2d	2026-07-28T03:36:25-04:00	Wali	Bind execution-time microstructure evidence
f3cd6a1b70f147a41ddf1a1bd65e23f3c4d1bf51	2026-07-28T04:08:35-04:00	Wali	fix(paper): bind admission evidence before allocation
ca6f43e522818c81e49648b80c29dab0e1b3b097	2026-07-28T04:23:45-04:00	Wali	fix(paper): scope quarantine to execution lineage
a7382fdcdf5d6670d5d97e6d232bf481338f900f	2026-07-28T05:02:04-04:00	Wali	fix(paper): preserve sealed accepted-fill replay
a5535b011c65ca6a43f9b406bce620323e70f584	2026-07-28T05:19:27-04:00	Wali	fix(paper): replay compact accepted fills immutably
6611d6784177d78f891ba7b5119b2d770ffe1919	2026-07-28T05:33:25-04:00	Wali	fix(paper): preserve compact replay across restart
250ad83ef1d187a2f20a3bf5e32a80ff410c0ff9	2026-07-28T05:51:52-04:00	Wali	fix(paper): retain accepted source through restart
4eb85c11fb5af467edf6ca4371880c5bb6ef5529	2026-07-28T06:29:21-04:00	Wali	fix(paper): preserve authenticated entry proof through close
f3fd227ad15cba0379cbeb27b44eaddca7cab25d	2026-07-28T07:35:44-04:00	Wali	fix(paper): publish complete candidate decision matrix
27635258e87ba434c2c001887337db31972f1969	2026-07-28T07:47:39-04:00	Wali	fix(adaptive): stream verified calibration revisions
f90effc2437eccf8686f63c318dded5d996c46d7	2026-07-28T08:03:59-04:00	Wali	docs: record adaptive runtime acceptance
6f80eec4167dd1e7cd44fcc98ad687e198e2cc19	2026-07-28T08:21:33-04:00	Wali	fix(adaptive): authenticate outcome dataset evidence
df75333efba77c53109757ab78db578bdbbce6a5	2026-07-28T08:31:32-04:00	Wali	fix(adaptive): close dataset receipt gaps
eedf8d8b0deb9687b3f9316f9925f4498c9507d1	2026-07-28T08:36:08-04:00	Wali	fix(adaptive): require authenticated dataset source receipt
0825f200e3aca4eb423914caab6b8ce4839c1235	2026-07-28T08:37:43-04:00	Wali	fix(adaptive): canonicalize archive receipt path
49ee369e08206e4135eb1b2c6ff6b008f64c7b68	2026-07-28T09:05:22-04:00	Wali	Authenticate and freeze adaptive challenger training
04b49c4673c67b21fc320685b142f7d315bd5a65	2026-07-28T09:15:20-04:00	Wali	Close rotated training receipt semantic gaps
48165b48ee24c7f75f06c9fbcd22d6bbcb1f1027	2026-07-28T09:18:26-04:00	Wali	Type source high-water counters strictly
7e8a153b78f26e51d19dad8ab5d7d7edd57b98a0	2026-07-28T09:20:34-04:00	Wali	Bind candidate derivation method semantics
a1add4a2830c5ca0d994a897c9a23efd58c4a381	2026-07-28T09:26:13-04:00	Wali	Record authenticated challenger rejection
5821713e0b63982b334f9a1ebb77e68891b958df	2026-07-28T09:40:45-04:00	Wali	Authenticate rolling training dataset receipts
8973b381403850a63cd055db85738b95f61a6719	2026-07-28T09:57:18-04:00	Wali	Dispatch authenticated adaptive challengers durably
39ba18ae7d33d2bba550541c11963f05967a9635	2026-07-28T10:07:43-04:00	Wali	Harden adaptive dispatch authorization and replay
79a2b370c3bd6ba4771dd797dbc3ec2aa169d170	2026-07-28T10:21:21-04:00	Wali	Record authenticated escalation rejection
df8b57e85b17ec7b39241207acd526f1854619df	2026-07-28T10:37:42-04:00	Wali	Authenticate alternative strategy supply evaluation
3d65aa9cc81247b0e8938f2498a6320b7bdf0605	2026-07-28T10:44:22-04:00	Wali	Bind strategy supply matrix identity
c3a30a60900ce64cc345133e22d361b519b69109	2026-07-28T11:08:11-04:00	Wali	Authenticate bounded exploration escalation
f1df3dad180d5e0720e535abfe343325a7ac101f	2026-07-28T11:22:35-04:00	Wali	Stream candidate outcome archive processing
879fd2e71f8212d35debc0d6e81f9b4580c79e03	2026-07-28T11:26:08-04:00	Wali	Bind streamed maturation rereads
aae7a0dad08c67df4c63001891a8ea4891030cc9	2026-07-28T11:48:28-04:00	Wali	Automate authenticated adaptive escalation
43f431a2aaa947dabf6df301e32a27de7f5bdf4e	2026-07-28T12:00:03-04:00	Wali	Harden automatic adaptive escalation
cb5b0cbcc4182a7724300a19b2ac72b9d0d1822d	2026-07-28T12:02:55-04:00	Wali	Snapshot candidate archive outside writer lock
ee4c2b20aded258f55cedd7bf4c392a02e63fdc0	2026-07-28T12:08:31-04:00	Wali	Bind adaptive work to checkpoint failure cycles
f839b3a3be620a905e81b4e84a533964ae4ecd1d	2026-07-28T12:09:02-04:00	Wali	Bind calibration publish to active registry readback
2c0a1cda37b4d899034fa7638d68413de9c73d6b	2026-07-28T12:13:17-04:00	Wali	Enforce canonical adaptive dispatch replay
82700c83e0a6de8f4f504c55b19af9574e9be6a4	2026-07-28T12:20:38-04:00	Wali	Bind calibration to exact archive snapshot
fbb20410cfb436d8d5925e708a80dc73645f1f0f	2026-07-28T12:34:17-04:00	Wali	Bind feature representation rung to signed release
9feefb3d606a738937645ec38f1d79aad485cd3d	2026-07-28T12:40:30-04:00	Wali	fix adaptive representation authentication
763be6ac466395ef00904af03fa5f5fb43cee4f1	2026-07-28T12:52:24-04:00	Wali	add authenticated diversified challenger rungs
2f3bb8b8c1db8fdaed59381ccec078917021a8f0	2026-07-28T12:55:46-04:00	Wali	prevent incremental ladder starvation
820cf1e59c29cc42a408760b1c7169f816e198a6	2026-07-28T13:04:48-04:00	Wali	Bind authenticated hedge research labels
f68d372541178a86e39d72a2a44beb1bce87b526	2026-07-28T13:14:53-04:00	Wali	Cross-bind hedge scenario semantics
85c9bb86591011639b483a88bf25587432ecfaf4	2026-07-28T13:19:43-04:00	Wali	Bind hedge outcome clocks and receipts
~~~

## 2. Runtime deployment state

Repository SHA for every row is
85c9bb86591011639b483a88bf25587432ecfaf4.

| Unit | State | MainPID | NRestarts | Immutable/configured SHA | Differs from HEAD |
|---|---:|---:|---:|---|---:|
| ai-bot-v2-canonical-prediction-serving.service | active/running | 3541449 | 0 | 250ad83ef1d187a2f20a3bf5e32a80ff410c0ff9 | yes |
| ai-bot-v2-trade-management-paper-loop.service | active/running | 3710798 | 0 | 27635258e87ba434c2c001887337db31972f1969 | yes |
| ai-bot-v2-candidate-outcome-publisher.service | active/running | 4028680 | 0 | 879fd2e71f8212d35debc0d6e81f9b4580c79e03 | yes |
| ai-bot-v2-candidate-outcome-calibration.service | active/running | 4104274 | 0 | 82700c83e0a6de8f4f504c55b19af9574e9be6a4 | yes |
| ai-bot-v2-full-talib-ta-loop.service | active/running | 3966828 | 0 | 3d65aa9cc81247b0e8938f2498a6320b7bdf0605 | yes |
| ai-bot-v2-strategy-supply-publisher.service | active/running | 3967119 | 0 | 3d65aa9cc81247b0e8938f2498a6320b7bdf0605 | yes |
| ai-bot-v2-gen5-backfill.service | inactive/dead | 0 | 0 | f12bce1229b0f157b92089c71f1774caace1c4c5 | yes |
| ai-bot-v2-adaptive-policy-shadow.service | inactive/dead | 0 | 0 | 7700414a4bca1df6a4964a587d5d22455ab40841 | yes |
| ai-bot-v2-adaptive-escalation-runtime.service | failed/failed after requested SIGTERM | 0 | 0 | 85c9bb86591011639b483a88bf25587432ecfaf4 | no |
| ai-bot-v2-adaptive-escalation-runtime.timer | inactive/dead | 0 | 0 | unit configured for 85c9bb86591011639b483a88bf25587432ecfaf4 | no |

The stopped escalation service reports Result=signal, ExecMainCode=2 and
ExecMainStatus=15. This is the requested closeout interruption, not an
application crash. The credential file existed as a regular operator-owned
mode-0600 file; no credential content was read or recorded.

Exact rollback commands use the last running or known-safe immutable SHA.
They are operator commands and were not executed during closeout:

~~~bash
sed -i -E 's#/deployments/ai_bot_rebuild/[0-9a-f]{40}#/deployments/ai_bot_rebuild/250ad83ef1d187a2f20a3bf5e32a80ff410c0ff9#g' /home/wali/.config/systemd/user/ai-bot-v2-canonical-prediction-serving.service
systemctl --user daemon-reload
systemctl --user restart ai-bot-v2-canonical-prediction-serving.service

sed -i -E 's#/deployments/ai_bot_rebuild/[0-9a-f]{40}#/deployments/ai_bot_rebuild/27635258e87ba434c2c001887337db31972f1969#g' /home/wali/.config/systemd/user/ai-bot-v2-trade-management-paper-loop.service
systemctl --user daemon-reload
systemctl --user restart ai-bot-v2-trade-management-paper-loop.service

sed -i -E 's#/deployments/ai_bot_rebuild/[0-9a-f]{40}#/deployments/ai_bot_rebuild/879fd2e71f8212d35debc0d6e81f9b4580c79e03#g' /home/wali/.config/systemd/user/ai-bot-v2-candidate-outcome-publisher.service
systemctl --user daemon-reload
systemctl --user restart ai-bot-v2-candidate-outcome-publisher.service

sed -i -E 's#/deployments/ai_bot_rebuild/[0-9a-f]{40}#/deployments/ai_bot_rebuild/82700c83e0a6de8f4f504c55b19af9574e9be6a4#g' /home/wali/.config/systemd/user/ai-bot-v2-candidate-outcome-calibration.service
systemctl --user daemon-reload
systemctl --user restart ai-bot-v2-candidate-outcome-calibration.service

sed -i -E 's#/deployments/ai_bot_rebuild/[0-9a-f]{40}#/deployments/ai_bot_rebuild/3d65aa9cc81247b0e8938f2498a6320b7bdf0605#g' /home/wali/.config/systemd/user/ai-bot-v2-full-talib-ta-loop.service /home/wali/.config/systemd/user/ai-bot-v2-strategy-supply-publisher.service
systemctl --user daemon-reload
systemctl --user restart ai-bot-v2-full-talib-ta-loop.service ai-bot-v2-strategy-supply-publisher.service

sed -i -E 's#/deployments/ai_bot_rebuild/[0-9a-f]{40}#/deployments/ai_bot_rebuild/f12bce1229b0f157b92089c71f1774caace1c4c5#g' /home/wali/.config/systemd/user/ai-bot-v2-gen5-backfill.service
systemctl --user daemon-reload
systemctl --user stop ai-bot-v2-gen5-backfill.service

sed -i -E 's#/deployments/ai_bot_rebuild/[0-9a-f]{40}#/deployments/ai_bot_rebuild/7700414a4bca1df6a4964a587d5d22455ab40841#g' /home/wali/.config/systemd/user/ai-bot-v2-adaptive-policy-shadow.service
systemctl --user daemon-reload
systemctl --user stop ai-bot-v2-adaptive-policy-shadow.service

sed -i -E 's#85c9bb86591011639b483a88bf25587432ecfaf4#9feefb3d606a738937645ec38f1d79aad485cd3d#g; s# --max-dispatches-per-run 4##' /home/wali/.config/systemd/user/ai-bot-v2-adaptive-escalation-runtime.service
systemctl --user daemon-reload
systemctl --user stop ai-bot-v2-adaptive-escalation-runtime.timer ai-bot-v2-adaptive-escalation-runtime.service
systemctl --user reset-failed ai-bot-v2-adaptive-escalation-runtime.service
~~~

## 3. Current paper truth

Snapshot sources are the latest canonical lifecycle state and paper-loop Redis
status generated between 2026-07-28T17:26:07Z and 17:26:19Z.

| Predicate | Current value |
|---|---:|
| starting session equity | 3000.00000000 USD |
| wallet balance | 2985.65188356 USD |
| equity | 2985.65188356 USD |
| free margin | 2985.65188356 USD |
| used margin | 0.00000000 USD |
| reserved margin | 0.00000000 USD |
| accepted-fill state rows | 0 |
| accepted-fill quarantine rows | 27 |
| proof-store state | EMPTY_INITIALIZED_PROOF_SET |
| proof-store rows | 0 |
| open positions | 0 |
| closed trades | 93 |
| pending reservations | 0 |
| duplicate fills | 0 |
| duplicate closes | 0 |
| reservation leaks | 0 |
| unproved open positions | 0 |
| historical unproved-close quarantine rows | 2 |
| last completed paper cycle | 2026-07-28T17:26:16.768560Z |

Proof reconciliation is PASS and idempotent with zero phantom or unresolved
positions, zero used/reserved-margin release and zero wallet mutation. The empty
proof set is initialized and completed; absence is not being interpreted as
position invalidity.

Last natural admission/fill/close lineage:

~~~text
prediction/fill/intent=v2h_9de687c8976c12b33f84a627ab698fd6
signal=sig_v2h_9de687c8976c12b33f84a627ab698fd6
orchestrator=dec_v2h_9de687c8976c12b33f84a627ab698fd6
risk=rd_dec_v2h_9de687c8976c12b33f84a627ab698fd6
allocation=alloc_6bbbb576c4eb8e5c6a1fed6c
position=paper_pos_1000PEPEUSDT_a38a3a3e790e11be
close=paper_close_paper_pos_1000PEPEUSDT_a38a3a3e790e11be_1_43703
entry=2026-07-28T10:06:26.293943Z
close=2026-07-28T11:06:38.250082Z
close_reason=TIER_3_ADAPTIVE_POLICY_TIME_EXIT
realized_net_pnl_usd=0.05716304487747147
~~~

The immutable acceptance artifact is
goal_state/PERMANENT_SYSTEM_RECOVERY/4eb85c11_1000pepe_lifecycle_acceptance_20260728.json
with SHA-256
d1c1177da792fc8a02ca038551416f69a99046b0bb74e562a83063c2cac91c5f.

## 4. Gate status

| Gate | Result | Required failure class | Exact truth |
|---|---|---|---|
| G03 | FAIL | RUNTIME_EVIDENCE_GATED | F049-F054 were not formally recomputed/closed on a complete frozen five-close cohort |
| G11 | FAIL | NATURAL_MARKET_OUTCOME_GATED | only 1/5 current generation natural closes; old counterfactual result remains 0/5 |
| G12 | PASS | — | 17/17 rare-event suite |
| G13 | FAIL | NATURAL_MARKET_OUTCOME_GATED | only 1/5 current cohort; historical weighted expectancy -18.12637793535448 bps |
| G14 | FAIL | NATURAL_MARKET_OUTCOME_GATED | only 1/5 current cohort; historical profit factor 0.6580123165026963 |
| natural lifecycle | PASS | — | natural fill, proof-backed position, mandatory protection and ordinary reduce-only close |
| restart reconstruction | PASS | — | exact open fill/position/proof/accounting state retained; no duplicate/release |
| accounting reconciliation | PASS | — | wallet/equity/free-margin reconciliation difference zero after close |
| systemd verification | PASS | — | diagnostics=0 and ordering cycles=0 |
| boot validator | FAIL | RUNTIME_EVIDENCE_GATED | current unit failed/failed, Result=exit-code, ExecMainStatus=1; last recorded PASS is stale from 2026-07-26 |

A controlled reboot remains OPERATOR_AUTHORIZATION_GATED and was not run.

## 5. Tests and evidence

Exact significant verification commands and their recorded results:

~~~bash
.venv/bin/pytest -q   v2/backend/tests/unit/services/adaptive_system/test_candidate_outcome_serving_dataset_v2.py   v2/backend/tests/unit/cli/test_v2_candidate_outcome_dataset_builder.py   v2/backend/tests/unit/cli/test_train_serving_profitability_v3_checkpoint.py   v2/backend/tests/unit/cli/test_v2_adaptive_diversified_challenger.py   v2/backend/tests/unit/cli/test_v2_adaptive_escalation_runtime.py   v2/backend/tests/unit/services/adaptive_system/test_escalation_supervisor_v2.py
# final closeout rerun: 136 passed in 7.36s

.venv/bin/pytest -q --tb=no v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
# 691 passed, 13 failed, 31 setup errors

.venv/bin/python scripts/guardian_phase10_rare_event_tests.py
# 17 PASS, 0 WARNING, 0 FAIL

.venv/bin/python -m py_compile <changed Python files>
# PASS

.venv/bin/ruff check --select E902,F821,F822,F823 <changed Python and test files>
# PASS

systemd-analyze --user verify ai-bot-v2-stack.target default.target timers.target   ai-bot-v2-adaptive-escalation-runtime.service   ai-bot-v2-adaptive-escalation-runtime.timer   ai-bot-v2-trade-management-paper-loop.service
# no output; diagnostics=0

git diff --check
# no output
~~~

Earlier exact recovery-baseline invocation:

~~~bash
.venv/bin/pytest -q v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py v2/backend/tests/unit/services/paper_trade_management/test_adaptive_cost_model.py v2/backend/tests/unit/cli/test_v2_boot_validator.py v2/backend/tests/unit/cli/test_v2_canonical_prediction_serving_runtime.py v2/backend/tests/unit/cli/test_v2_microstructure_feed_quality_monitor.py
# 143 passed

.venv/bin/python scripts/s13_max_hold_transport_canary.py
# all_pass=true; exchange_action_taken=false
~~~

Later immutable acceptance artifacts record 58/58 archive/publisher/calibration,
27/27 complete-matrix/paper, 144/144 CG-F057/adaptive/lifecycle, 132/132 local
authenticated-dataset/trainer and 91/91 independent exact-SHA tests with 34/34
hostile mutations rejected. Their selection lists are recorded in FINAL PASS.md;
the day-long ledger used scoped-selection notation rather than preserving every
expanded argv. This handoff does not invent missing argv details.

The 13 failures and 31 setup errors are the documented pre-existing legacy
cycle-reservation/final-admission fixture family. The recorded earlier baseline
was 547 passed, 13 failed, 31 errors; later scoped repairs increased passing
coverage without changing those 13/31. New failures introduced by this goal:
zero known.

Authoritative evidence paths and hashes:

- lifecycle/restart/accounting:
  goal_state/PERMANENT_SYSTEM_RECOVERY/4eb85c11_1000pepe_lifecycle_acceptance_20260728.json,
  d1c1177da792fc8a02ca038551416f69a99046b0bb74e562a83063c2cac91c5f
- candidate runtime:
  goal_state/PERMANENT_SYSTEM_RECOVERY/27635258_candidate_outcome_runtime_acceptance_20260728.json,
  b1b699410185482518074bb7183d7731fcdff038b16fc6a6e5656ce77e825e6e
- composite dataset:
  goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/FP080_TYPED_OUTCOME_DATASET_ACCEPTANCE.json,
  0d072b34e91752828b9f7ce362fbe006f15da2d4ef6ebbe10da10dc41fbb9399
- rejected challenger:
  goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/FP100_AUTHENTICATED_CHALLENGER_EVALUATION.json,
  b66859b8110ac6ef28aa3a549768789e397c01f95d0480915361088da6d49b91
- bounded escalation dispatch:
  goal_state/ADAPTIVE_SYSTEM_FINAL_PASS/FP110_AUTHENTICATED_ESCALATION_DISPATCH_20260728.json,
  605a46ab47d1980fcb5c692345f806a7f2254b317632ec10a4d48dedf750a63f

Not run in this closeout: full-repository pytest, unrestricted full-repository
Ruff, a fresh boot-validator invocation, controlled reboot, live exchange tests,
real order submission, a new five-close economic evaluation, or a complete
promotion run for the interrupted partial build. No summary claim relies on
those unrun checks.

The exhaustive command-family ledger for the engineering run remains in
FINAL PASS.md. Closeout itself used only git/status/log/diff, jq, sha256sum,
systemctl show/stop, systemd-analyze verify, Redis GET/SCAN projections, rg,
sed, stat, find and the two authorized apply-patch writes. The only closeout
runtime mutation was stopping the escalation oneshot; it was required by the
operator's stop directive.

## 6. Safety truth

~~~text
paper_only=true
live_gate=blocked_human_only
routes_to_live=false
places_real_order=false
exchange_action_taken=false
~~~

The generation-3 checkpoint remains paper-only and provisional. The model
registry candidate lane was not written by the interrupted attempt. No order,
cancel, leverage change, margin-mode change or exchange mutation was performed.

## 7. Five bounded follow-up goals

### Goal 1 — Paper account epoch reset

Owner: Codex  
Timebox: 75 minutes  
Bounded files: v2/backend/app/services/paper_session/epoch.py,
v2/backend/tests/test_paper_epoch_rotation.py, tools/paper_epoch_preflight.py,
tools/paper_epoch_rotate.py, and one generated signed epoch manifest.

Acceptance: preflight PASS on a flat book and initialized proof store; archive
the 93 historical closes and all economic/training evidence without mutation;
activate one new current-session identifier; expose exactly 3000.00 USD wallet,
equity and free margin with zero used/reserved margin; prove archive/current
counts and SHA bindings; paper-only flags remain false for live authority.
No execution is allowed until the manifest contains an exact inverse state
plan.

Rollback command for code:

~~~bash
git restore --source=85c9bb86591011639b483a88bf25587432ecfaf4 --   v2/backend/app/services/paper_session/epoch.py   v2/backend/tests/test_paper_epoch_rotation.py   tools/paper_epoch_preflight.py tools/paper_epoch_rotate.py
~~~

Runtime rollback must be the exact inverse command sealed into the pre-execution
epoch manifest; absence of that command is an acceptance failure.

### Goal 2 — Proof/accounting acceptance

Owner: Claude  
Timebox: 60 minutes  
Bounded files: v2/backend/app/cli/v2_trade_management_paper_loop.py,
v2/backend/tests/unit/cli/test_cg_f063_proof_store_reconciliation.py,
v2/backend/tests/unit/services/paper_trade_management/test_partial_close_restart_reconstruction.py,
and one acceptance JSON.

Acceptance: five legitimate positions survive an uninitialized proof store;
backfill produces five exact bindings; idempotent replay; one quarantined
phantom removes only that phantom; no wallet mutation, duplicate close, duplicate
margin release or conservation error; long/short symmetry and restart
reconstruction PASS. Review-only unless a concrete failing fixture proves a
defect.

Rollback command:

~~~bash
git restore --source=27635258e87ba434c2c001887337db31972f1969 --   v2/backend/app/cli/v2_trade_management_paper_loop.py   v2/backend/tests/unit/cli/test_cg_f063_proof_store_reconciliation.py   v2/backend/tests/unit/services/paper_trade_management/test_partial_close_restart_reconstruction.py
~~~

### Goal 3 — Frontend session scoping

Owner: Codex  
Timebox: 60 minutes  
Bounded files: one paper-session API module, its API tests,
v2/frontend/tests/e2e/trade_terminal_redesign.spec.ts, and only the directly
consuming frontend cache/store module identified by the failing fixture.

Acceptance: current session and archive are separate typed responses; current
totals never include archive rows; archive remains queryable; cache keys include
session ID and invalidate on epoch change; malformed/missing scope fails closed;
API and E2E fixtures PASS.

Rollback command:

~~~bash
git restore --source=85c9bb86591011639b483a88bf25587432ecfaf4 --   v2/frontend/tests/e2e/trade_terminal_redesign.spec.ts
~~~

The production API/cache file must be appended to that exact command before any
edit; an unbounded frontend rollback is forbidden.

### Goal 4 — Adaptive-policy evidence integration

Owner: Codex  
Timebox: 90 minutes  
Bounded files: v2/backend/app/domain/adaptive_policy_action_v2/record.py,
v2/backend/app/services/adaptive_system/adaptive_policy_shadow_v2.py,
v2/backend/app/services/adaptive_system/adaptive_paper_policy_authorization_v2.py,
v2/backend/app/cli/v2_adaptive_policy_shadow_runtime.py, their direct unit tests,
and no live execution file.

Acceptance: conservative microstructure minima/maxima are consumed by the typed
action; ExpectedCostBreakdownV2 identity holds; feed_integrity_pass=false blocks
every action including FLAT/SHADOW; non-catastrophic regression is a bounded
risk penalty; every typed action/FLAT/BLOCK has decision, authorization and cycle
hash lineage; independent reference parity has zero disagreements.

Rollback command:

~~~bash
git restore --source=85c9bb86591011639b483a88bf25587432ecfaf4 -- v2/backend/app/domain/adaptive_policy_action_v2/record.py v2/backend/app/services/adaptive_system/adaptive_policy_shadow_v2.py v2/backend/app/services/adaptive_system/adaptive_paper_policy_authorization_v2.py v2/backend/app/cli/v2_adaptive_policy_shadow_runtime.py
~~~

### Goal 5 — Natural lifecycle observer

Owner: Claude  
Timebox: 60 minutes or 10 completed paper cycles, whichever comes first  
Bounded files: no production files; one observation artifact beneath
goal_state/PERMANENT_SYSTEM_RECOVERY.

Acceptance: observation-only; acquire the single-run lock only on a fresh
generation-bound persisted fill plus open position; freeze lineage/accounting
before any restart; otherwise finish with NO_EVENT_BOUNDED_WINDOW. No model,
threshold, service, Redis, systemd or deployment change is permitted. A defect
may only be reported with a concrete immutable failing fixture for a separate
goal.

Rollback command:

~~~bash
true
~~~

## 8. Final closeout statement

Completed: ServingFeatureABIV2 and parity; authenticated enlarged dataset;
candidate-outcome publication/maturation/calibration; adaptive paper authority;
proof-store fail-closed semantics; one natural adaptive fill/open/mandatory
protection/restart/ordinary close/accounting lifecycle; two confirmation cycles;
G12; immutable paper runtime deployments; bounded authenticated escalation and
diversified/hedge research contracts.

Not completed: paper account epoch reset/current-versus-archive UI scoping;
full FINAL PASS task set; superior challenger activation; five-close economic
cohort; G03/G11/G13/G14; fresh boot-validator PASS; controlled reboot; permanent
recovery; live submission.

Current exact blocker: only 1 of 5 required eligible generation-scoped natural
closes exists, so economic gates cannot be recomputed honestly. Separately, the
current boot-validator service state is failed and must be refreshed only after
its runtime predicates are current.

The core paper stack is safe to leave running: it is flat, reconciled, has one
canonical writer, zero restarts, initialized proof state, zero reservations and
all no-live flags. No additional running service must be stopped. The escalation
oneshot and timer are already stopped and should remain stopped.

Single safest next action: accept this handoff, then run Goal 1's paper-epoch
preflight in dry-run mode only. Do not execute rotation until its signed manifest
contains the exact inverse rollback plan and all flat-book/proof/accounting
predicates pass.

~~~text
V2_PERMANENT_RECOVERY_COMPLETE=false
LIVE_NO_GO=true
A_PLUS_READY=false
LIVE_SUBMISSION_READY=false
~~~
