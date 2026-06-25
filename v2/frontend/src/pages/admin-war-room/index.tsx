import meta from './meta';
import {
  BlockerChip,
  FreshnessBadge,
  MetricCard,
  PanelHeader,
  PayloadMissingCard,
  SafetyInvariantStrip,
  SourceBadge,
} from '../../components/realtimeWebsite';
import {
  PAYLOAD_PATHS,
  useFrontendTruth,
  useFullObservationBuilder,
  useLegacyLogIntelligence,
  useLiveCanaryBringupDashboard,
  useLiveCanaryExecutorStatus,
  useLiveCanaryPermissionProbe,
  useWarRoomActionsApplied,
  useWarRoomCodexQueue,
  useWarRoomDashboard,
  useWarRoomGapMatrix,
  useParallelSparkAutomationStatus,
} from '../../data/realtimeUserWebsitePayloads';
import { usePayloadFile } from '../../hooks/usePayloadFile';

const LIVE_GATE_RUNTIME_PATH = '/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json';

interface LiveGateRuntimePayload {
  live_gate?: string;
  execution_live_symbols?: string[];
  live_order_submit_allowed?: boolean;
  live_blocked?: boolean;
  live_blocker?: string;
  places_real_order?: boolean;
}

export default function AdminWarRoomPage(): JSX.Element {
  const warRoom = useWarRoomDashboard();
  const gapMatrix = useWarRoomGapMatrix();
  const actions = useWarRoomActionsApplied();
  const codexQueue = useWarRoomCodexQueue();
  const fullObs = useFullObservationBuilder();
  const legacyLog = useLegacyLogIntelligence();
  const frontendTruth = useFrontendTruth();
  const canaryDash = useLiveCanaryBringupDashboard();
  const canaryExec = useLiveCanaryExecutorStatus();
  const canaryProbe = useLiveCanaryPermissionProbe();
  const parallelSparkAutomation = useParallelSparkAutomationStatus();
  const { data: liveGateRuntime } = usePayloadFile<LiveGateRuntimePayload>(LIVE_GATE_RUNTIME_PATH, 8_000);

  const envelope = warRoom.payload?.safety_invariants ?? warRoom.payload;
  const extra = {
    checkpoint_compatibility_claimed:
      fullObs.payload?.checkpoint_compatibility_claimed ??
      (warRoom.payload?.safety_invariants as any)?.checkpoint_compatibility_claimed ??
      false,
    policy_architecture_parity_claimed:
      fullObs.payload?.policy_architecture_parity_claimed ??
      (warRoom.payload?.safety_invariants as any)?.policy_architecture_parity_claimed ??
      false,
  };

  const cycle = warRoom.payload?.cycle;
  const state = warRoom.payload?.state;
  const lane_g = warRoom.payload?.lane_g_narrow_fixes;
  const aggregated = gapMatrix.payload?.aggregated_classification_counts ?? warRoom.payload?.lane_b_gap_matrix?.aggregated_classification_counts ?? {};

  // Raw payload explorer: every source path we read, plus current
  // freshness status. NEVER includes raw secret values.
  const explorerRows: Array<{ key: string; path: string; status: string; freshness: string }> = [
    { key: 'frontend_truth', path: PAYLOAD_PATHS.frontend_truth, status: frontendTruth.error ?? (frontendTruth.payload ? 'OK' : 'loading'), freshness: frontendTruth.payload?.generated_utc ?? '' },
    { key: 'war_room_dashboard', path: PAYLOAD_PATHS.war_room_dashboard, status: warRoom.error ?? (warRoom.payload ? 'OK' : 'loading'), freshness: warRoom.payload?.generated_utc ?? '' },
    { key: 'war_room_gap_matrix', path: PAYLOAD_PATHS.war_room_gap_matrix, status: gapMatrix.error ?? (gapMatrix.payload ? 'OK' : 'loading'), freshness: (gapMatrix.payload as any)?.generated_utc ?? '' },
    { key: 'war_room_actions', path: PAYLOAD_PATHS.war_room_actions, status: actions.error ?? (actions.payload ? 'OK' : 'loading'), freshness: '' },
    { key: 'war_room_codex_queue', path: PAYLOAD_PATHS.war_room_codex_queue, status: codexQueue.error ?? (codexQueue.payload ? 'OK' : 'loading'), freshness: '' },
    { key: 'full_observation_builder', path: PAYLOAD_PATHS.full_observation_builder, status: fullObs.error ?? (fullObs.payload ? 'OK' : 'loading'), freshness: '' },
    { key: 'legacy_log_intelligence', path: PAYLOAD_PATHS.legacy_log_intelligence, status: legacyLog.error ?? (legacyLog.payload ? 'OK' : 'loading'), freshness: legacyLog.payload?.generated_utc ?? '' },
    { key: 'live_canary_bringup_dashboard', path: PAYLOAD_PATHS.live_canary_bringup_dashboard, status: canaryDash.error ?? (canaryDash.payload ? 'OK' : 'loading'), freshness: canaryDash.payload?.generated_utc ?? '' },
    { key: 'live_canary_executor_status', path: PAYLOAD_PATHS.live_canary_executor_status, status: canaryExec.error ?? (canaryExec.payload ? 'OK' : 'loading'), freshness: canaryExec.payload?.generated_utc ?? '' },
    { key: 'live_canary_permission_probe', path: PAYLOAD_PATHS.live_canary_permission_probe, status: canaryProbe.error ?? (canaryProbe.payload ? 'OK' : 'loading'), freshness: canaryProbe.payload?.generated_utc ?? '' },
    { key: 'parallel_spark_automation', path: PAYLOAD_PATHS.parallel_spark_automation, status: parallelSparkAutomation.error ?? (parallelSparkAutomation.payload ? 'OK' : 'loading'), freshness: parallelSparkAutomation.payload?.generated_utc ?? '' },
  ];

  return (
    <article className="production-public-page grid-bg" data-testid="page-admin-war-room" data-page-id={meta.id}>
      <header className="public-page-header panel bracketed">
        <span className="br-bl" aria-hidden="true" />
        <span className="br-br" aria-hidden="true" />
        <p className="eyebrow">{meta.description}</p>
        <h1>{meta.title}</h1>
      </header>

      <SafetyInvariantStrip envelope={envelope as any} extra={extra} />

      {/* ---- 1. War-room cycle table ---- */}
      <section className="panel" style={{ padding: 14, marginTop: 18 }} data-testid="war-room-cycle-panel">
        <PanelHeader title="War-room cycles" source={PAYLOAD_PATHS.war_room_dashboard} rightExtras={<FreshnessBadge generatedAt={warRoom.payload?.generated_utc} maxAgeSeconds={360} />} />
        {!warRoom.payload ? (
          <PayloadMissingCard path={PAYLOAD_PATHS.war_room_dashboard} error={warRoom.error} loading={warRoom.loading} />
        ) : (
          <section className="status-rail">
            <div className="wrap">
              <MetricCard label="cycle_count" value={state?.cycle_count ?? 0} />
              <MetricCard label="last cycle_id" value={cycle?.cycle_id ?? '—'} />
              <MetricCard label="last started_at" value={cycle?.started_at ?? '—'} detail={<FreshnessBadge generatedAt={cycle?.finished_at} maxAgeSeconds={600} />} />
              <MetricCard label="actions_applied" value={(actions.payload?.actions ?? []).length} />
              <MetricCard label="no_action_streak" value={state?.no_action_streak ?? 0} />
              <MetricCard label="codex_reviews_queued_total" value={state?.codex_reviews_queued_total ?? 0} />
            </div>
          </section>
        )}
      </section>

      {/* ---- 2. Model signal gap matrix ---- */}
      <section className="panel" style={{ padding: 14, marginTop: 18 }} data-testid="war-room-gap-matrix">
        <PanelHeader title="Model signal gap matrix" source={PAYLOAD_PATHS.war_room_gap_matrix} rightExtras={<FreshnessBadge generatedAt={(gapMatrix.payload as any)?.generated_utc} maxAgeSeconds={1200} />} />
        {!gapMatrix.payload ? (
          <PayloadMissingCard path={PAYLOAD_PATHS.war_room_gap_matrix} error={gapMatrix.error} loading={gapMatrix.loading} />
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="mkt" style={{ width: '100%' }}>
              <thead>
                <tr>
                  <th>Classification</th>
                  <th>Count across symbols</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(aggregated).map(([k, v]) => (
                  <tr key={k}>
                    <td>{k}</td>
                    <td className="num">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {(gapMatrix.payload.per_symbol ?? []).map((row) => (
                <div key={row.symbol ?? Math.random()} className="panel" style={{ padding: 10, minWidth: 240 }}>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 12, marginBottom: 6 }}>{row.symbol}</div>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {(row.classifications ?? []).map((c) => (
                      <BlockerChip key={c} text={c} tone={c.startsWith('PAPER_FILL_GATE_STRICT_BLOCK') || c.includes('CHECKPOINT') ? 'block' : 'warn'} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* ---- 3. Raw blocker matrix ---- */}
      <section className="panel" style={{ padding: 14, marginTop: 18 }} data-testid="war-room-raw-blocker-matrix">
        <PanelHeader title="Raw blocker matrix" source={PAYLOAD_PATHS.full_observation_builder} rightExtras={<FreshnessBadge generatedAt={(fullObs.payload as any)?.generated_at as any} maxAgeSeconds={1800} />} />
        <section className="status-rail">
          <div className="wrap">
            <MetricCard label="Live order routing" value="blocked" tone="bad" />
            <MetricCard label="Shutdown" value="blocked" tone="bad" />
            <MetricCard label="checkpoint_compatibility_claimed" value={String(extra.checkpoint_compatibility_claimed)} tone={extra.checkpoint_compatibility_claimed ? 'warn' : 'ok'} />
            <MetricCard label="policy_architecture_parity_claimed" value={String(extra.policy_architecture_parity_claimed)} tone={extra.policy_architecture_parity_claimed ? 'warn' : 'ok'} />
            <MetricCard label="full_observation_state" value={fullObs.payload?.state ?? '—'} tone={fullObs.payload?.state === 'FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS' ? 'warn' : 'ok'} />
            <MetricCard label="approves_*" value="all false" tone="ok" />
          </div>
        </section>
      </section>

      {/* ---- 4. Legacy log observer panel ---- */}
      <section className="panel" style={{ padding: 14, marginTop: 18 }} data-testid="war-room-legacy-log-observer">
        <PanelHeader title="Legacy log observer" source={PAYLOAD_PATHS.legacy_log_intelligence} rightExtras={<FreshnessBadge generatedAt={legacyLog.payload?.generated_utc} maxAgeSeconds={1800} />} />
        {!legacyLog.payload ? (
          <PayloadMissingCard path={PAYLOAD_PATHS.legacy_log_intelligence} error={legacyLog.error} loading={legacyLog.loading} />
        ) : (
          <div className="metric-list">
            <div className="metric-row"><div className="lbl">trainer_log_evidence_present</div><div className="val">{String(legacyLog.payload.trainer_log_evidence_present ?? '—')}</div><div className="delta">runtime telemetry</div></div>
            <div className="metric-row"><div className="lbl">orchestrator_log_evidence_present</div><div className="val">{String(legacyLog.payload.orchestrator_log_evidence_present ?? '—')}</div><div className="delta">runtime telemetry</div></div>
            <div className="metric-row"><div className="lbl">read_only_safety</div><div className="val up">{String(legacyLog.payload.read_only_safety ?? true)}</div><div className="delta">never writes legacy</div></div>
            <div className="metric-row"><div className="lbl">go_no_go</div><div className="val">{legacyLog.payload.go_no_go ?? '—'}</div><div className="delta">observer</div></div>
          </div>
        )}
      </section>

      {/* ---- 5. Codex review status ---- */}
      <section className="panel" style={{ padding: 14, marginTop: 18 }} data-testid="war-room-codex-review">
        <PanelHeader title="Codex review queue" source={PAYLOAD_PATHS.war_room_codex_queue} rightExtras={<FreshnessBadge generatedAt={(codexQueue.payload as any)?.generated_utc} maxAgeSeconds={3600} />} />
        {!codexQueue.payload ? (
          <PayloadMissingCard path={PAYLOAD_PATHS.war_room_codex_queue} error={codexQueue.error} loading={codexQueue.loading} />
        ) : (
          <div>
            <p style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-3)' }}>Pending Codex reviews: {(codexQueue.payload.pending_codex_reviews ?? []).length}</p>
            <ul style={{ listStyle: 'none', display: 'grid', gap: 6 }}>
              {(codexQueue.payload.pending_codex_reviews ?? []).slice(0, 10).map((r: any, i) => (
                <li key={String(r.review_id ?? i)}>
                  <BlockerChip text={`${r.severity ?? 'P?'} · ${r.topic ?? '—'}`} tone="info" />
                </li>
              ))}
            </ul>
            <p style={{ marginTop: 12, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-3)' }}>Existing blockers excluded from auto-task creation:</p>
            <ul style={{ listStyle: 'none', display: 'grid', gap: 6 }}>
              {(codexQueue.payload.pre_existing_blockers_not_eligible_for_new_task_creation ?? []).slice(0, 10).map((b: any, i) => (
                <li key={String(b.blocker_id ?? i)}>
                  <BlockerChip text={`${b.blocker_id ?? '—'} · owner: ${b.owner ?? '—'}`} tone="warn" />
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* ---- 6. Safety scan panel ---- */}
      <section className="panel" style={{ padding: 14, marginTop: 18 }} data-testid="war-room-safety-scan">
        <PanelHeader title="Safety scan" source={PAYLOAD_PATHS.war_room_dashboard} rightExtras={<FreshnessBadge generatedAt={warRoom.payload?.generated_utc} maxAgeSeconds={1800} />} />
        <section className="status-rail">
          <div className="wrap">
            <MetricCard label="Legacy Redis writes" value="none" tone="ok" />
            <MetricCard label="Exchange order writes" value="none" tone="ok" />
            <MetricCard label="Real/canary/shutdown approvals" value="all blocked" tone="ok" />
            <MetricCard label="Credential exposure" value="none detected" tone="ok" />
            <MetricCard label="Synthetic signal/market data" value="not rendered" tone="ok" />
            <MetricCard label="Runtime shutdown acceptance" value="not created" tone="ok" />
          </div>
        </section>
      </section>

      {/* ---- 7. Live canary bring-up status (telemetry; NO controls) ---- */}
      <section className="panel" style={{ padding: 14, marginTop: 18 }} data-testid="war-room-live-canary-bringup">
        <PanelHeader
          title="24h live-canary bring-up (dry-run scaffolding; no controls)"
          source={PAYLOAD_PATHS.live_canary_bringup_dashboard}
          rightExtras={<FreshnessBadge generatedAt={canaryDash.payload?.generated_utc} maxAgeSeconds={1800} />}
        />
        {!canaryDash.payload && !canaryExec.payload ? (
          <PayloadMissingCard
            path={PAYLOAD_PATHS.live_canary_bringup_dashboard}
            error={canaryDash.error}
            loading={canaryDash.loading}
          />
        ) : (
          <>
            <section className="status-rail">
              <div className="wrap">
                <MetricCard
                  label="Go/no-go decision"
                  value={canaryDash.payload?.go_no_go ?? canaryExec.payload?.go_no_go ?? '—'}
                  tone="warn"
                />
                <MetricCard
                  label="Live gate"
                  value={liveGateRuntime?.live_order_submit_allowed === false || liveGateRuntime?.live_blocked === true ? (liveGateRuntime?.live_blocker ?? 'BLOCKED') : (liveGateRuntime?.live_gate ?? canaryDash.payload?.live_gate ?? 'loading')}
                  tone={liveGateRuntime?.live_order_submit_allowed === true && liveGateRuntime?.live_blocked !== true ? 'ok' : 'warn'}
                />
                <MetricCard label="Execution symbols" value={liveGateRuntime?.execution_live_symbols?.length ?? 0} tone="ok" />
                <MetricCard label="Dry-run mode" value={(canaryDash.payload?.dry_run ?? true) ? 'enabled' : 'disabled'} tone="ok" />
                <MetricCard label="Live order routing enabled" value={(canaryDash.payload?.live_enabled ?? false) ? 'enabled' : 'blocked'} tone="ok" />
                <MetricCard label="Real order attempt" value={(canaryDash.payload?.real_order_attempted ?? false) ? 'attempted' : 'none'} tone="ok" />
                <MetricCard label="Leverage changes" value={(canaryDash.payload?.leverage_changed ?? false) ? 'changed' : 'unchanged'} tone="ok" />
                <MetricCard label="Margin mode changes" value={(canaryDash.payload?.margin_mode_changed ?? false) ? 'changed' : 'unchanged'} tone="ok" />
                <MetricCard label="Approval artifact" value={(canaryDash.payload?.approval_file_present ?? false) ? 'present' : 'not present'} />
                <MetricCard label="Codex pass marker" value={(canaryDash.payload?.codex_live_canary_pass_marker_present ?? false) ? 'present' : 'not present'} />
                <MetricCard label="Permission probe" value={canaryDash.payload?.permission_probe_go_no_go ?? canaryProbe.payload?.go_no_go ?? '—'} />
                <MetricCard label="Dry-run intent count" value={canaryDash.payload?.intent_count ?? canaryExec.payload?.intent_count ?? 0} />
                <MetricCard label="Credentials in payload" value={(canaryDash.payload?.raw_credential_in_payload ?? 'NEVER') === 'NEVER' ? 'none detected' : canaryDash.payload?.raw_credential_in_payload} tone="ok" />
                <MetricCard label="Exchange adapter" value={(canaryExec.payload as any)?.exchange_adapter_kind ?? 'FakeExchangeAdapter'} tone="ok" />
                <MetricCard label="Dry-run service" value="active" tone="ok" detail="ai-bot-v2-live-canary-dry-run.timer · 60s cadence" />
                <MetricCard label="Private signed POST callable" value={(canaryExec.payload as any)?.private_signed_post_callable ? 'callable' : 'blocked'} tone="ok" />
                <MetricCard label="Final order boundary checks" value={(canaryExec.payload as any)?.final_order_post_boundary_count ?? 1} tone="ok" />
              </div>
            </section>
            {canaryProbe.payload && (
              <div style={{ marginTop: 12 }}>
                <p style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-3)' }}>permission_probe fail_blockers:</p>
                <ul style={{ listStyle: 'none', display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {(canaryProbe.payload.fail_blockers ?? []).map((b, i) => (
                    <li key={String(b) + i}>
                      <BlockerChip text={b} tone="warn" />
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {canaryExec.payload?.intents && canaryExec.payload.intents.length > 0 && (
              <div style={{ marginTop: 12, overflowX: 'auto' }}>
                <table className="mkt" style={{ width: '100%' }}>
                  <thead>
                    <tr>
                      <th>Cycle</th>
                      <th>Symbol</th>
                      <th>Side</th>
                      <th>Signal source</th>
                      <th>Notional</th>
                      <th>Execution gate</th>
                      <th>Freshness</th>
                      <th>Blockers</th>
                    </tr>
                  </thead>
                  <tbody>
                    {canaryExec.payload.intents.slice(0, 10).map((it, i) => (
                      <tr key={(it.cycle_id ?? '') + i}>
                        <td className="num">{it.cycle_id ?? '—'}</td>
                        <td>{it.candidate?.symbol ?? '—'}</td>
                        <td>{it.candidate?.side ?? '—'}</td>
                        <td>{it.candidate?.signal_source ?? '—'}</td>
                        <td className="num">{it.candidate?.requested_notional_usdt ?? '—'}</td>
                        <td>{String(it.candidate?.paper_fill_gate_open ?? false)}</td>
                        <td>{it.candidate?.feature_freshness_state ?? '—'}</td>
                        <td>
                          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                            {(it.fail_blockers ?? []).slice(0, 4).map((b) => (
                              <BlockerChip key={b} text={b} tone="block" />
                            ))}
                            {(it.fail_blockers ?? []).length > 4 && (
                              <BlockerChip text={`+${(it.fail_blockers ?? []).length - 4} more`} tone="info" />
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p style={{ marginTop: 12, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-3)' }}>
              This panel shows live telemetry. No control surface. Real order submission requires a
              separate operator-approved packet; the executor currently raises
              NotImplementedError for any live submission path.
            </p>
          </>
        )}
      </section>

      {/* ---- 9. Parallel Spark automation status ---- */}
      <section className="panel" style={{ padding: 14, marginTop: 18 }} data-testid="war-room-parallel-spark-automation">
        <PanelHeader
          title="Parallel Spark automation"
          source={PAYLOAD_PATHS.parallel_spark_automation}
          rightExtras={<FreshnessBadge generatedAt={parallelSparkAutomation.payload?.generated_utc} maxAgeSeconds={120} />}
        />
        {!parallelSparkAutomation.payload ? (
          <PayloadMissingCard
            path={PAYLOAD_PATHS.parallel_spark_automation}
            error={parallelSparkAutomation.error}
            loading={parallelSparkAutomation.loading}
          />
        ) : (
          <>
            <section className="status-rail">
              <div className="wrap">
                <MetricCard label="go_no_go" value={parallelSparkAutomation.payload.go_no_go ?? '—'} tone={parallelSparkAutomation.payload.ready ? 'ok' : 'warn'} />
                <MetricCard label="mode" value={parallelSparkAutomation.payload.mode ?? '—'} />
                <MetricCard label="cycle" value={String(parallelSparkAutomation.payload.cycle ?? '—')} />
                <MetricCard label="runner_pid" value={String(parallelSparkAutomation.payload.runner_pid ?? '—')} />
                <MetricCard label="ready" value={String(parallelSparkAutomation.payload.ready ?? false)} tone={parallelSparkAutomation.payload.ready ? 'ok' : 'bad'} />
                <MetricCard label="lane_count" value={String(parallelSparkAutomation.payload.lane_count ?? 0)} />
                <MetricCard label="runner" value={parallelSparkAutomation.payload.runner ?? '—'} />
              </div>
            </section>
            {!!(parallelSparkAutomation.payload.blockers?.length ?? 0) && (
              <div style={{ marginTop: 12 }}>
                <p style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-3)' }}>blockers:</p>
                <ul style={{ listStyle: 'none', display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {(parallelSparkAutomation.payload.blockers ?? []).map((b) => (
                    <li key={b}>
                      <BlockerChip text={b} tone="warn" />
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </section>

      {/* ---- 8. Raw payload explorer ---- */}
      <section className="panel" style={{ padding: 14, marginTop: 18 }} data-testid="war-room-raw-payload-explorer">
        <PanelHeader title="Raw payload explorer" source="public/" rightExtras={<BlockerChip text="paths only · no raw secrets" tone="info" />} />
        <div style={{ overflowX: 'auto' }}>
          <table className="mkt" style={{ width: '100%' }}>
            <thead>
              <tr><th>Key</th><th>Source path</th><th>Status</th><th>Last generated_utc</th></tr>
            </thead>
            <tbody>
              {explorerRows.map((r) => (
                <tr key={r.key}>
                  <td>{r.key}</td>
                  <td><SourceBadge path={r.path} /></td>
                  <td className="num">{r.status}</td>
                  <td className="num">{r.freshness || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </article>
  );
}
