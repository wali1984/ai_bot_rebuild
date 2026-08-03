/**
 * NERVYX ONE — Public Landing Page
 * Redesigned: premium dark crypto analytics aesthetic
 * Streams live market data from /api/v2/market/overview via the shared realtime resource.
 */

import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { NERVYX_BRAND } from '../../brand/nervyxBrand';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import meta from './meta';

// ─── Types ────────────────────────────────────────────────────────────────────
interface TickerRow {
  symbol: string;
  last_price: number | null;
  change_24h: number | null;
  volume_24h: number | null;
  turnover_24h: number | null;
}

interface MarketOverviewData {
  tickers?: TickerRow[];
  symbols?: string[];
  count?: number;
}

// ─── Formatters ───────────────────────────────────────────────────────────────
function fmtPrice(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return `$${v.toLocaleString('en-US', { minimumFractionDigits: v > 10 ? 2 : 4, maximumFractionDigits: v > 10 ? 2 : 6 })}`;
}

function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—';
  const pct = Math.abs(v) <= 1 ? v * 100 : v;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

function fmtVol(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 2 }).format(v);
}

function changeColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return 'rgba(190,210,230,0.45)';
  const pct = Math.abs(v) <= 1 ? v * 100 : v;
  return pct >= 0 ? '#12b886' : '#ff6b6b';
}

// ─── Sub-components ───────────────────────────────────────────────────────────
const HERO_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'] as const;

function HeroPriceCard({ ticker, stale }: { ticker: TickerRow | undefined; stale: boolean }): JSX.Element {
  const sym = ticker?.symbol ?? 'BTC';
  const base = sym.replace('USDT', '');
  const price = ticker?.last_price;
  const change = ticker?.change_24h;
  const pct = change == null || !Number.isFinite(change) ? null : (Math.abs(change) <= 1 ? change * 100 : change);
  const up = pct == null ? null : pct >= 0;
  const color = up == null ? 'rgba(190,210,230,0.4)' : up ? '#12b886' : '#ff6b6b';
  const borderColor = up == null ? 'rgba(255,255,255,0.06)' : up ? 'rgba(18,184,134,0.2)' : 'rgba(255,107,107,0.2)';
  // Honest freshness: only claim LIVE while the overview envelope is fresh or
  // delayed; a stale/offline feed must not keep asserting LIVE to the public.
  const badgeLabel = ticker ? (stale ? 'STALE' : 'LIVE') : 'LOADING';
  const badgeColor = ticker && stale ? '#f59e0b' : color;

  return (
    <div
      style={{
        background: '#0e1a26',
        border: `1px solid ${borderColor}`,
        borderRadius: 10,
        padding: '16px 18px',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        minWidth: 140,
        flex: 1,
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* bottom accent line */}
      <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 2, background: color, opacity: 0.6 }} />

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.14em', color: 'rgba(190,210,230,0.65)' }}>
          {base}
        </span>
        <span
          style={{
            fontSize: 10,
            fontFamily: 'var(--font-mono)',
            padding: '2px 6px',
            borderRadius: 4,
            background: `${badgeColor}14`,
            color: badgeColor,
            letterSpacing: '0.06em',
          }}
        >
          {badgeLabel}
        </span>
      </div>

      <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em', color: '#e8f4ff', fontFamily: 'var(--font-mono)' }}>
        {ticker ? fmtPrice(price) : (
          <span style={{ color: 'rgba(190,210,230,0.3)', fontSize: 14 }}>Connecting...</span>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color, fontWeight: 600 }}>
          {ticker ? fmtPct(change) : '—'}
        </span>
        <span style={{ fontSize: 11, color: 'rgba(190,210,230,0.4)' }}>24h</span>
      </div>
    </div>
  );
}

function MoverCard({ row }: { row: TickerRow; type: 'gainer' | 'loser' }): JSX.Element {
  const base = row.symbol.replace('USDT', '');
  const pct = row.change_24h == null ? null : (Math.abs(row.change_24h) <= 1 ? row.change_24h * 100 : row.change_24h);
  // Color by the actual sign of the move, never by list category: on quiet
  // days the TOP LOSERS column contains positive movers and must not paint
  // gains in loss-red.
  const color = pct == null ? 'rgba(190,210,230,0.45)' : pct >= 0 ? '#12b886' : '#ff6b6b';

  return (
    <Link
      to={`/market/${row.symbol}`}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '10px 14px',
        background: '#0e1a26',
        border: '1px solid rgba(255,255,255,0.06)',
        borderRadius: 8,
        textDecoration: 'none',
        gap: 10,
        transition: 'border-color 120ms ease',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: '#e8f4ff', fontFamily: 'var(--font-mono)', letterSpacing: '0.06em' }}>
          {base}
        </span>
        <span style={{ fontSize: 11, color: 'rgba(190,210,230,0.45)' }}>
          {fmtVol(row.turnover_24h ?? row.volume_24h)} vol
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
        <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: '#c8d8e8' }}>
          {fmtPrice(row.last_price)}
        </span>
        <span style={{ fontSize: 12, fontWeight: 700, fontFamily: 'var(--font-mono)', color }}>
          {pct == null ? '—' : `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`}
        </span>
      </div>
    </Link>
  );
}

function LoadingSkeleton({ count = 5 }: { count?: number }): JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          style={{
            height: 52,
            borderRadius: 8,
            background: 'linear-gradient(90deg, #0e1a26 0%, #142030 50%, #0e1a26 100%)',
            backgroundSize: '200% 100%',
            border: '1px solid rgba(255,255,255,0.04)',
          }}
        />
      ))}
    </div>
  );
}

function FeatureCard({ icon, title, desc }: { icon: string; title: string; desc: string }): JSX.Element {
  return (
    <div
      style={{
        background: '#0e1a26',
        border: '1px solid rgba(255,255,255,0.07)',
        borderRadius: 10,
        padding: '24px 22px',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}
    >
      <div
        style={{
          width: 40,
          height: 40,
          borderRadius: 10,
          background: 'rgba(79,209,255,0.08)',
          border: '1px solid rgba(79,209,255,0.18)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 18,
        }}
      >
        {icon}
      </div>
      <div>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#e8f4ff', marginBottom: 6 }}>{title}</div>
        <div style={{ fontSize: 13, color: 'rgba(190,210,230,0.6)', lineHeight: 1.55 }}>{desc}</div>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function PublicLandingPage(): JSX.Element {
  const marketResource = useRealtimeResource<MarketOverviewData>({
    url: '/api/v2/market/overview',
    source: '/api/v2/market/overview',
    pollIntervalMs: 20_000,
    staleThresholdMs: 60_000,
    mode: 'read_only',
  });
  const marketTickers = useMemo(
    () => (marketResource.envelope.data?.tickers ?? []).filter((ticker): ticker is TickerRow => Boolean(ticker?.symbol)),
    [marketResource.envelope.data?.tickers],
  );
  const marketStatus = marketTickers.length
    ? 'ok'
    : marketResource.loading
      ? 'loading'
      : marketResource.error
        ? 'error'
        : 'idle';
  const overviewFreshness = marketResource.envelope.freshness_status;
  const overviewStale = overviewFreshness !== 'fresh' && overviewFreshness !== 'delayed';

  // Hero price cards — BTC, ETH, SOL, BNB
  const heroTickers = useMemo(() => {
    const map = new Map(marketTickers.map((t) => [t.symbol, t]));
    return HERO_SYMBOLS.map((sym) => map.get(sym));
  }, [marketTickers]);

  // Top 5 gainers
  const gainers = useMemo(() => {
    return [...marketTickers]
      .filter((r) => r.change_24h != null && r.last_price != null)
      .sort((a, b) => {
        const pa = Math.abs(a.change_24h ?? 0) <= 1 ? (a.change_24h ?? 0) * 100 : (a.change_24h ?? 0);
        const pb = Math.abs(b.change_24h ?? 0) <= 1 ? (b.change_24h ?? 0) * 100 : (b.change_24h ?? 0);
        return pb - pa;
      })
      .slice(0, 5);
  }, [marketTickers]);

  // Top 5 losers
  const losers = useMemo(() => {
    return [...marketTickers]
      .filter((r) => r.change_24h != null && r.last_price != null)
      .sort((a, b) => {
        const pa = Math.abs(a.change_24h ?? 0) <= 1 ? (a.change_24h ?? 0) * 100 : (a.change_24h ?? 0);
        const pb = Math.abs(b.change_24h ?? 0) <= 1 ? (b.change_24h ?? 0) * 100 : (b.change_24h ?? 0);
        return pa - pb;
      })
      .slice(0, 5);
  }, [marketTickers]);

  const isLoading = (marketStatus === 'idle' || marketStatus === 'loading') && marketTickers.length === 0;
  const hasData = marketStatus === 'ok' && marketTickers.length > 0;

  const S = {
    page: {
      minHeight: '100vh',
      background: '#0a0f14',
      color: '#e8f4ff',
      fontFamily: 'var(--font-sans)',
      WebkitFontSmoothing: 'antialiased',
    } as React.CSSProperties,
    wrap: {
      width: '100%',
      maxWidth: 1280,
      margin: '0 auto',
      padding: '0 24px',
    } as React.CSSProperties,
  };

  return (
    <main style={S.page} data-testid="page-public-landing" data-page-id={meta.id}>

      {/* ── STATUS RAIL ─────────────────────────────────────────────────── */}
      <div
        style={{
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          background: '#0c1520',
        }}
      >
        <div
          style={{
            ...S.wrap,
            display: 'grid',
            // auto-fit + minmax so the rail wraps to 2-3 columns on narrow
            // viewports instead of overlapping glyphs at fixed 6 columns.
            gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
            gap: 0,
          }}
        >
          {[
            { k: 'Market feeds', v: isLoading ? 'Connecting...' : hasData ? `${marketTickers.filter((t) => t.last_price != null).length} symbols` : 'Error', ok: hasData },
            { k: 'BTC price', v: heroTickers[0] ? fmtPrice(heroTickers[0].last_price) : '...', ok: !!heroTickers[0] },
            { k: 'ETH price', v: heroTickers[1] ? fmtPrice(heroTickers[1].last_price) : '...', ok: !!heroTickers[1] },
            { k: 'Data source', v: hasData ? 'WebSocket' : 'Connecting...', ok: hasData },
            { k: 'Execution', v: 'Restricted', warn: true },
            { k: 'Trading gate', v: 'Approval gated', bad: true },
          ].map(({ k, v, ok, warn, bad }) => (
            <div
              key={k}
              style={{
                padding: '8px 16px 8px 0',
                borderRight: '1px solid rgba(255,255,255,0.05)',
                display: 'flex',
                flexDirection: 'column',
                gap: 2,
              }}
            >
              <span style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'rgba(190,210,230,0.35)', letterSpacing: '0.12em', textTransform: 'uppercase' }}>
                {k}
              </span>
              <span style={{
                fontSize: 11,
                fontFamily: 'var(--font-mono)',
                color: bad ? '#ff6b6b' : warn ? '#f59e0b' : ok ? '#12b886' : 'rgba(190,210,230,0.7)',
              }}>
                {v}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* ── HERO SECTION ─────────────────────────────────────────────────── */}
      <section style={{ padding: '64px 0 48px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <div style={S.wrap}>
          <img
            src={NERVYX_BRAND.assets.logoOnMidnight}
            alt="NERVYX ONE"
            style={{
              display: 'block',
              width: 'min(260px, 68vw)',
              height: 62,
              objectFit: 'contain',
              objectPosition: 'left center',
              marginBottom: 18,
            }}
          />

          {/* Eyebrow */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
            <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#4fd1ff' }} />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.14em', color: 'rgba(190,210,230,0.5)', textTransform: 'uppercase' }}>
              Adaptive market intelligence platform
            </span>
          </div>

          {/* Headline */}
          <h1 style={{
            fontSize: 'clamp(32px, 5vw, 56px)',
            fontWeight: 700,
            letterSpacing: 0,
            lineHeight: 1.08,
            margin: '0 0 16px',
            color: '#e8f4ff',
            maxWidth: 720,
          }}>
            NERVYX ONE
            <span style={{ color: '#4fd1ff' }}> — </span>
            <span style={{ color: 'rgba(190,210,230,0.7)' }}>Adaptive Market Intelligence Platform</span>
          </h1>

          <p style={{ fontSize: 16, color: 'rgba(190,210,230,0.65)', lineHeight: 1.6, maxWidth: 580, margin: '0 0 32px' }}>
            AI-powered signals, real-time derivatives analytics, and risk-governed execution intelligence.
            Professional-grade trading infrastructure for approval-gated execution workflows.
          </p>

          {/* CTA buttons */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 48 }}>
            <Link
              to="/markets"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '10px 20px',
                borderRadius: 8,
                background: '#4fd1ff',
                color: '#0a0f14',
                fontWeight: 700,
                fontSize: 13,
                textDecoration: 'none',
                letterSpacing: '0.01em',
              }}
            >
              View Markets →
            </Link>
            <Link
              to="/login"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '10px 20px',
                borderRadius: 8,
                border: '1px solid rgba(79,209,255,0.3)',
                background: 'rgba(79,209,255,0.07)',
                color: '#4fd1ff',
                fontWeight: 600,
                fontSize: 13,
                textDecoration: 'none',
              }}
            >
              Sign In
            </Link>
            <Link
              to="/signals"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '10px 20px',
                borderRadius: 8,
                border: '1px solid rgba(255,255,255,0.1)',
                background: 'rgba(255,255,255,0.03)',
                color: 'rgba(190,210,230,0.8)',
                fontWeight: 500,
                fontSize: 13,
                textDecoration: 'none',
              }}
            >
              View Signals
            </Link>
          </div>

          {/* Hero price cards */}
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {HERO_SYMBOLS.map((sym, i) => (
              <HeroPriceCard key={sym} ticker={heroTickers[i]} stale={overviewStale} />
            ))}
          </div>
        </div>
      </section>

      {/* ── LIVE MARKET PULSE ────────────────────────────────────────────── */}
      <section style={{ padding: '48px 0', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <div style={S.wrap}>
          {/* Section heading */}
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
            <div>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'rgba(190,210,230,0.4)', letterSpacing: '0.14em', textTransform: 'uppercase' }}>
                01 / Market pulse
              </span>
              <h2 style={{ fontSize: 22, fontWeight: 600, color: '#e8f4ff', margin: '6px 0 0', letterSpacing: '-0.02em' }}>
                Live Gainers &amp; Losers
              </h2>
            </div>
            {hasData && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(190,210,230,0.4)' }}>
                {marketTickers.length} symbols · WebSocket live · API fallback 20s
              </span>
            )}
          </div>

          {/* Connecting state */}
          {isLoading && (
            <div style={{ textAlign: 'center', padding: '40px 20px', color: 'rgba(190,210,230,0.4)', fontSize: 13, fontFamily: 'var(--font-mono)' }}>
              Connecting to market data...
            </div>
          )}

          {/* Error state */}
          {marketStatus === 'error' && (
            <div style={{ textAlign: 'center', padding: '40px 20px', color: '#f59e0b', fontSize: 13, fontFamily: 'var(--font-mono)' }}>
              Market feed temporarily unavailable — retrying...
            </div>
          )}

          {/* Gainers/Losers grid */}
          {hasData && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 24 }}>
              {/* Top Gainers */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#12b886' }} />
                  <span style={{ fontSize: 12, fontWeight: 600, color: '#12b886', fontFamily: 'var(--font-mono)', letterSpacing: '0.06em' }}>
                    TOP GAINERS
                  </span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {gainers.length ? gainers.map((row) => (
                    <MoverCard key={row.symbol} row={row} type="gainer" />
                  )) : <LoadingSkeleton />}
                </div>
              </div>

              {/* Top Losers */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#ff6b6b' }} />
                  <span style={{ fontSize: 12, fontWeight: 600, color: '#ff6b6b', fontFamily: 'var(--font-mono)', letterSpacing: '0.06em' }}>
                    TOP LOSERS
                  </span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {losers.length ? losers.map((row) => (
                    <MoverCard key={row.symbol} row={row} type="loser" />
                  )) : <LoadingSkeleton />}
                </div>
              </div>
            </div>
          )}

          {/* Skeleton while loading */}
          {isLoading && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 24 }}>
              <div><LoadingSkeleton /></div>
              <div><LoadingSkeleton /></div>
            </div>
          )}
        </div>
      </section>


      {/* ── FEATURES STRIP ───────────────────────────────────────────────── */}
      <section style={{ padding: '48px 0', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <div style={S.wrap}>
          <div style={{ marginBottom: 28 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'rgba(190,210,230,0.4)', letterSpacing: '0.14em', textTransform: 'uppercase' }}>
              02 / Platform capabilities
            </span>
            <h2 style={{ fontSize: 22, fontWeight: 600, color: '#e8f4ff', margin: '6px 0 0', letterSpacing: '-0.02em' }}>
              Professional-Grade Trading Infrastructure
            </h2>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
            <FeatureCard
              icon="🤖"
              title="AI Signals"
              desc="Evidence-based signals with confidence scores, feature snapshots, calibration metadata, and full explainability for every prediction."
            />
            <FeatureCard
              icon="🛡️"
              title="Risk Gating"
              desc="Multi-layer risk validation before any execution. Every signal passes through the risk gateway — no exceptions, no overrides."
            />
            <FeatureCard
              icon="📄"
              title="Execution Telemetry"
              desc="Position tracking, P&amp;L, execution ledger, and approval-governed workflow visibility."
            />
            <FeatureCard
              icon="📊"
              title="Derivatives Analytics"
              desc="Funding rates, open interest, liquidation levels, long/short ratios, and basis tracking across 600+ symbols."
            />
            <FeatureCard
              icon="🔍"
              title="Signal Explainability"
              desc="Every prediction includes exact input data, feature freshness, model version, checkpoint reference, and source evidence."
            />
            <FeatureCard
              icon="📋"
              title="Audit Ledger"
              desc="Full audit trail for every signal, decision, and execution event. Immutable evidence chain for review and compliance."
            />
          </div>
        </div>
      </section>

      {/* ── BOTTOM CTA ───────────────────────────────────────────────────── */}
      <section style={{ padding: '56px 0' }}>
        <div style={{ ...S.wrap, textAlign: 'center' }}>
          <div
            style={{
              background: 'linear-gradient(135deg, #0e1a26 0%, #0c1520 100%)',
              border: '1px solid rgba(79,209,255,0.15)',
              borderRadius: 16,
              padding: '48px 32px',
              maxWidth: 680,
              margin: '0 auto',
            }}
          >
            <div style={{ width: 48, height: 48, borderRadius: 12, background: 'rgba(79,209,255,0.08)', border: '1px solid rgba(79,209,255,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 22, margin: '0 auto 20px' }}>
              🚀
            </div>
            <h2 style={{ fontSize: 26, fontWeight: 700, color: '#e8f4ff', letterSpacing: '-0.025em', margin: '0 0 12px' }}>
              Ready to explore the platform?
            </h2>
            <p style={{ fontSize: 14, color: 'rgba(190,210,230,0.6)', lineHeight: 1.6, margin: '0 0 28px', maxWidth: 460, marginLeft: 'auto', marginRight: 'auto' }}>
              Sign in to access your dashboard, full trader toolkit, signal history, positions, and risk control panel.
            </p>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
              <Link
                to="/login"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '11px 24px',
                  borderRadius: 8,
                  background: '#4fd1ff',
                  color: '#0a0f14',
                  fontWeight: 700,
                  fontSize: 14,
                  textDecoration: 'none',
                  letterSpacing: '0.01em',
                }}
              >
                Sign In to Dashboard →
              </Link>
              <Link
                to="/status"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '11px 24px',
                  borderRadius: 8,
                  border: '1px solid rgba(255,255,255,0.1)',
                  background: 'rgba(255,255,255,0.03)',
                  color: 'rgba(190,210,230,0.75)',
                  fontWeight: 500,
                  fontSize: 14,
                  textDecoration: 'none',
                }}
              >
                View System Status
              </Link>
            </div>
            <div style={{ marginTop: 20, fontSize: 11, fontFamily: 'var(--font-mono)', color: 'rgba(190,210,230,0.3)', letterSpacing: '0.04em' }}>
              REAL-TIME MARKET INTELLIGENCE · EXECUTION TELEMETRY · RISK-GOVERNED WORKFLOWS
            </div>
          </div>
        </div>
      </section>

    </main>
  );
}
