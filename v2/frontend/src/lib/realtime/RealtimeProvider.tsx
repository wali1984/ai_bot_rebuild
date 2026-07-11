import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  type EnterpriseRealtimeBootstrap,
  type EnterpriseRealtimeFrame,
  type EnterpriseResourceName,
  type EnterpriseUiSnapshot,
  fetchRealtimeBootstrap,
  loadCachedRealtimeBootstrap,
  realtimeWebSocketUrl,
  saveCachedRealtimeBootstrap,
} from './resourceClient';

type RealtimeState = {
  bootstrap: EnterpriseRealtimeBootstrap | null;
  resources: Partial<Record<EnterpriseResourceName, EnterpriseUiSnapshot>>;
  status: 'connecting' | 'connected' | 'degraded' | 'offline';
  error: string | null;
  sequence: number;
  lastGoodAt: number | null;
  refetch: () => Promise<void>;
  subscribeResourcePath: (path: string, listener: (payload: Record<string, unknown>) => void) => () => void;
};

const RealtimeContext = createContext<RealtimeState | null>(null);

const DEFAULT_RESOURCES: EnterpriseResourceName[] = [
  'dashboard',
  'markets',
  'ai_brain',
  'risk',
  'portfolio',
  'providers',
  'system_health',
  'trader_cockpit',
];
const INITIAL_SOCKET_CONNECT_DELAY_MS = 350;

function resourcesFromBootstrap(bootstrap: EnterpriseRealtimeBootstrap): Partial<Record<EnterpriseResourceName, EnterpriseUiSnapshot>> {
  return bootstrap.resources ?? {};
}

function subscribedPaths(subscribers: Map<string, Set<(payload: Record<string, unknown>) => void>>): string[] {
  return [...subscribers.keys()].sort();
}

function samePaths(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

export function RealtimeProvider({ children }: { children: ReactNode }): JSX.Element {
  const [bootstrap, setBootstrap] = useState<EnterpriseRealtimeBootstrap | null>(() => loadCachedRealtimeBootstrap());
  const [resources, setResources] = useState<Partial<Record<EnterpriseResourceName, EnterpriseUiSnapshot>>>(() => {
    const cached = loadCachedRealtimeBootstrap();
    return cached ? resourcesFromBootstrap(cached) : {};
  });
  const [status, setStatus] = useState<RealtimeState['status']>(() => loadCachedRealtimeBootstrap() ? 'degraded' : 'connecting');
  const [error, setError] = useState<string | null>(null);
  const [sequence, setSequence] = useState(0);
  const [lastGoodAt, setLastGoodAt] = useState<number | null>(() => loadCachedRealtimeBootstrap() ? Date.now() : null);
  const [resourcePaths, setResourcePaths] = useState<string[]>([]);
  const socketRef = useRef<WebSocket | null>(null);
  const resourcePathSubscribersRef = useRef(new Map<string, Set<(payload: Record<string, unknown>) => void>>());

  const applyBootstrap = useCallback((payload: EnterpriseRealtimeBootstrap) => {
    setBootstrap(payload);
    setResources((previous) => ({ ...previous, ...resourcesFromBootstrap(payload) }));
    setLastGoodAt(Date.now());
    setError(null);
    saveCachedRealtimeBootstrap(payload);
  }, []);

  const refetch = useCallback(async () => {
    let timeout: number | null = null;
    const timeoutPromise = new Promise<null>((resolve) => {
      timeout = window.setTimeout(() => resolve(null), 4_000);
    });
    try {
      const payload = await Promise.race([fetchRealtimeBootstrap(), timeoutPromise]);
      if (!payload) {
        throw new Error('realtime_bootstrap_timeout');
      }
      applyBootstrap(payload);
      setStatus((current) => current === 'offline' ? 'degraded' : current);
    } finally {
      if (timeout !== null) window.clearTimeout(timeout);
    }
  }, [applyBootstrap]);

  const subscribeResourcePath = useCallback<RealtimeState['subscribeResourcePath']>((path, listener) => {
    const normalized = path.trim();
    if (!normalized) return () => undefined;
    const subscribers = resourcePathSubscribersRef.current;
    const listeners = subscribers.get(normalized) ?? new Set<(payload: Record<string, unknown>) => void>();
    listeners.add(listener);
    subscribers.set(normalized, listeners);
    setResourcePaths((previous) => {
      const next = subscribedPaths(subscribers);
      return samePaths(previous, next) ? previous : next;
    });
    return () => {
      const currentListeners = subscribers.get(normalized);
      if (!currentListeners) return;
      currentListeners.delete(listener);
      if (currentListeners.size === 0) {
        subscribers.delete(normalized);
      }
      setResourcePaths((previous) => {
        const next = subscribedPaths(subscribers);
        return samePaths(previous, next) ? previous : next;
      });
    };
  }, []);

  const notifyResourcePathSubscribers = useCallback((path: string, payload: Record<string, unknown>) => {
    const listeners = resourcePathSubscribersRef.current.get(path);
    if (!listeners) return;
    for (const listener of listeners) {
      listener(payload);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let initialConnectTimer: number | null = null;
    let reconnectTimer: number | null = null;
    let fallbackTimer: number | null = null;
    let reconnectAttempt = 0;

    void refetch().catch((err) => {
      if (!cancelled) {
        setStatus('degraded');
        setError((err as Error).message);
      }
    });

    const connect = () => {
      if (cancelled) return;
      const socketUrl = realtimeWebSocketUrl(DEFAULT_RESOURCES, 2_000, resourcePaths, 15_000);
      if (!socketUrl) {
        setStatus('degraded');
        return;
      }
      const previousSocket = socketRef.current;
      if (previousSocket && previousSocket.readyState !== WebSocket.CLOSED) {
        previousSocket.onclose = null;
        previousSocket.onerror = null;
        previousSocket.onmessage = null;
        previousSocket.onopen = null;
        previousSocket.close();
      }
      setStatus((current) => current === 'connected' ? current : 'connecting');
      const socket = new WebSocket(socketUrl);
      socketRef.current = socket;

      socket.onopen = () => {
        reconnectAttempt = 0;
        setStatus('connected');
        setError(null);
      };
      socket.onmessage = (event) => {
        try {
          const frame = JSON.parse(event.data) as EnterpriseRealtimeFrame;
          setSequence(frame.sequence);
          if (frame.type === 'bootstrap') {
            applyBootstrap(frame.payload);
            return;
          }
          if (frame.type === 'resource_delta') {
            setResources((previous) => ({
              ...previous,
              [frame.resource]: frame.payload,
            }));
            setLastGoodAt(Date.now());
            setError(null);
            return;
          }
          if (frame.type === 'resource_path_delta') {
            notifyResourcePathSubscribers(frame.path, frame.payload);
            setLastGoodAt(Date.now());
            setError(null);
          }
        } catch (err) {
          setError((err as Error).message);
        }
      };
      socket.onerror = () => {
        setStatus('degraded');
        setError('enterprise_realtime_socket_error');
      };
      socket.onclose = () => {
        if (cancelled) return;
        if (socketRef.current !== socket) return;
        setStatus((current) => current === 'connected' ? 'degraded' : current);
        const delay = Math.min(30_000, 1_000 * (2 ** reconnectAttempt));
        reconnectAttempt += 1;
        reconnectTimer = window.setTimeout(connect, delay);
      };
    };

    initialConnectTimer = window.setTimeout(connect, INITIAL_SOCKET_CONNECT_DELAY_MS);
    fallbackTimer = window.setInterval(() => {
      if (document.visibilityState === 'hidden') return;
      void refetch().catch((err) => {
        setStatus((current) => current === 'connected' ? 'degraded' : current);
        setError((err as Error).message);
      });
    }, 15_000);

    return () => {
      cancelled = true;
      socketRef.current?.close();
      if (initialConnectTimer) window.clearTimeout(initialConnectTimer);
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      if (fallbackTimer) window.clearInterval(fallbackTimer);
    };
  }, [applyBootstrap, notifyResourcePathSubscribers, refetch, resourcePaths]);

  const value = useMemo<RealtimeState>(
    () => ({ bootstrap, resources, status, error, sequence, lastGoodAt, refetch, subscribeResourcePath }),
    [bootstrap, error, lastGoodAt, refetch, resources, sequence, status, subscribeResourcePath],
  );

  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>;
}

export function useEnterpriseRealtime(): RealtimeState {
  const context = useContext(RealtimeContext);
  if (!context) throw new Error('useEnterpriseRealtime must be used within RealtimeProvider');
  return context;
}

export function useOptionalEnterpriseRealtime(): RealtimeState | null {
  return useContext(RealtimeContext);
}

export function useEnterpriseRealtimeResource<T = unknown>(resource: EnterpriseResourceName): EnterpriseUiSnapshot<T> | null {
  return (useEnterpriseRealtime().resources[resource] as EnterpriseUiSnapshot<T> | undefined) ?? null;
}
