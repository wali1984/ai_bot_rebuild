import { useEffect, useMemo, useRef, useState } from 'react';
import { useOptionalEnterpriseRealtime } from '../lib/realtime/RealtimeProvider';
import type { ApiV2Envelope } from '../types/apiV2';

export interface PaperActivityData {
  positions: Array<Record<string, unknown>>;
  fills: Array<Record<string, unknown>>;
  executions: Array<Record<string, unknown>>;
  open_orders: Array<Record<string, unknown>>;
  orders: Array<Record<string, unknown>>;
  order_history: Array<Record<string, unknown>>;
  audit_events: Array<Record<string, unknown>>;
  risk_profile?: Record<string, unknown>;
  summary?: Record<string, unknown>;
  stream?: Record<string, unknown>;
}

export interface PaperActivityStreamState {
  connected: boolean;
  source: 'websocket' | 'http_fallback' | 'unavailable';
  envelope: ApiV2Envelope<PaperActivityData> | null;
  data: PaperActivityData;
  stale: boolean;
  loading: boolean;
  error: string | null;
  warnings: string[];
}

export interface PaperActivityStreamOptions {
  httpFallback?: boolean;
  initialHttpSeed?: boolean;
}

const EMPTY_ACTIVITY: PaperActivityData = {
  positions: [],
  fills: [],
  executions: [],
  open_orders: [],
  orders: [],
  order_history: [],
  audit_events: [],
  summary: {},
  stream: {},
};

function rows(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === 'object')
    : [];
}

function normalizeActivity(value: unknown): PaperActivityData {
  const record = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  return {
    positions: rows(record.positions),
    fills: rows(record.fills),
    executions: rows(record.executions).length ? rows(record.executions) : rows(record.fills),
    open_orders: rows(record.open_orders),
    orders: rows(record.orders),
    order_history: rows(record.order_history).length ? rows(record.order_history) : rows(record.orders),
    audit_events: rows(record.audit_events),
    risk_profile: record.risk_profile && typeof record.risk_profile === 'object' ? record.risk_profile as Record<string, unknown> : {},
    summary: record.summary && typeof record.summary === 'object' ? record.summary as Record<string, unknown> : {},
    stream: record.stream && typeof record.stream === 'object' ? record.stream as Record<string, unknown> : {},
  };
}

function withRetainedRows(next: PaperActivityData, prior: PaperActivityData | null, priorAt: number | null): PaperActivityData {
  if (!prior || !priorAt || Date.now() - priorAt > 90_000) return next;
  return {
    ...next,
    positions: next.positions.length ? next.positions : prior.positions,
    fills: next.fills.length ? next.fills : prior.fills,
    executions: next.executions.length ? next.executions : prior.executions,
    orders: next.orders.length ? next.orders : prior.orders,
    order_history: next.order_history.length ? next.order_history : prior.order_history,
    audit_events: next.audit_events.length ? next.audit_events : prior.audit_events,
    summary: {
      ...(prior.summary ?? {}),
      ...(next.summary ?? {}),
      frontend_retained_rows: (
        !next.positions.length && prior.positions.length
          ? 'positions'
          : undefined
      ),
    },
  };
}

function paperActivityUrls(intervalMs: number): string[] {
  if (typeof window === 'undefined') return [];
  const origin = window.location.origin;
  const protocol = origin.startsWith('https:') ? 'wss:' : 'ws:';
  return ['/api/v2/ws/paper-activity', '/ws/paper-activity'].map((path) => {
    const url = new URL(path, origin);
    url.protocol = protocol;
    url.searchParams.set('interval_ms', String(intervalMs));
    return url.toString();
  });
}

async function fetchPaperActivity(signal?: AbortSignal): Promise<ApiV2Envelope<PaperActivityData>> {
  const response = await fetch('/api/v2/paper/activity', { credentials: 'include', signal });
  if (!response.ok) throw new Error(await response.text().catch(() => response.statusText));
  const envelope = await response.json() as ApiV2Envelope<unknown>;
  return {
    ...envelope,
    data: normalizeActivity(envelope.data),
  };
}

export function usePaperActivityStream(
  intervalMs = 1000,
  options: PaperActivityStreamOptions = {},
): PaperActivityStreamState {
  const { httpFallback = true, initialHttpSeed = true } = options;
  const sharedRealtime = useOptionalEnterpriseRealtime();
  const subscribeResourcePath = sharedRealtime?.subscribeResourcePath;
  const [envelope, setEnvelope] = useState<ApiV2Envelope<PaperActivityData> | null>(null);
  const [connected, setConnected] = useState(false);
  const [source, setSource] = useState<PaperActivityStreamState['source']>('unavailable');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const lastGoodRef = useRef<{ data: PaperActivityData; at: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let fallbackTimer: number | null = null;
    let reconnectTimer: number | null = null;
    let unsubscribeSharedResource: (() => void) | null = null;
    let receivedSharedFrame = false;
    const urls = paperActivityUrls(intervalMs);

    const applyEnvelope = (raw: ApiV2Envelope<unknown>, streamSource: PaperActivityStreamState['source']) => {
      const normalized = normalizeActivity(raw.data);
      const retained = withRetainedRows(normalized, lastGoodRef.current?.data ?? null, lastGoodRef.current?.at ?? null);
      if (
        retained.positions.length
        || retained.fills.length
        || retained.orders.length
        || retained.audit_events.length
      ) {
        lastGoodRef.current = { data: retained, at: Date.now() };
      }
      setEnvelope({ ...raw, data: retained } as ApiV2Envelope<PaperActivityData>);
      setSource(streamSource);
      setLoading(false);
      setError(null);
    };

    const poll = async () => {
      const controller = new AbortController();
      try {
        const next = await fetchPaperActivity(controller.signal);
        if (!cancelled) applyEnvelope(next, 'http_fallback');
      } catch (err) {
        if (!cancelled) {
          setError((err as Error).message);
          setLoading(false);
          setSource('unavailable');
        }
      }
    };

    const startFallback = () => {
      if (!httpFallback) {
        setSource('unavailable');
        setConnected(false);
        setLoading(false);
        setError('paper_activity_websocket_unavailable');
        return;
      }
      if (fallbackTimer !== null) window.clearInterval(fallbackTimer);
      void poll();
      fallbackTimer = window.setInterval(() => void poll(), Math.max(1500, intervalMs * 2));
    };

    if (initialHttpSeed && httpFallback && !subscribeResourcePath) {
      // Seed positions immediately via HTTP so fallback-enabled views appear before the WS connects.
      void poll();
    }

    if (subscribeResourcePath) {
      unsubscribeSharedResource = subscribeResourcePath('/api/v2/paper/activity', (raw) => {
        if (cancelled) return;
        receivedSharedFrame = true;
        applyEnvelope(raw as unknown as ApiV2Envelope<unknown>, 'websocket');
        setConnected(true);
      });
      if (initialHttpSeed && httpFallback) {
        fallbackTimer = window.setTimeout(() => {
          if (!cancelled && !receivedSharedFrame) startFallback();
        }, Math.min(5_000, Math.max(2_000, intervalMs * 4)));
      }
      return () => {
        cancelled = true;
        unsubscribeSharedResource?.();
        if (fallbackTimer !== null) window.clearInterval(fallbackTimer);
        if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      };
    }

    const connect = (index = 0) => {
      if (cancelled || !urls.length || index >= urls.length) {
        setConnected(false);
        startFallback();
        return;
      }
      try {
        socket = new WebSocket(urls[index]);
      } catch {
        connect(index + 1);
        return;
      }
      socket.onopen = () => {
        if (cancelled) return;
        setConnected(true);
        setSource('websocket');
      };
      socket.onmessage = (event) => {
        if (cancelled) return;
        try {
          applyEnvelope(JSON.parse(event.data) as ApiV2Envelope<unknown>, 'websocket');
        } catch (err) {
          setError((err as Error).message);
        }
      };
      socket.onerror = () => {
        if (cancelled) return;
        setConnected(false);
        setError('paper_activity_websocket_error');
      };
      socket.onclose = () => {
        if (cancelled) return;
        setConnected(false);
        if (index + 1 < urls.length) {
          connect(index + 1);
          return;
        }
        startFallback();
        reconnectTimer = window.setTimeout(() => connect(0), 5000);
      };
    };

    connect();

    return () => {
      cancelled = true;
      socket?.close();
      if (fallbackTimer !== null) window.clearInterval(fallbackTimer);
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
    };
  }, [httpFallback, initialHttpSeed, intervalMs, subscribeResourcePath]);

  const data = useMemo(() => envelope?.data ?? EMPTY_ACTIVITY, [envelope]);
  return {
    connected,
    source,
    envelope,
    data,
    stale: envelope?.stale ?? true,
    loading,
    error,
    warnings: envelope?.warnings ?? [],
  };
}

export const paperActivityStreamTestHooks = {
  normalizeActivity,
  withRetainedRows,
};
