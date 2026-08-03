import { Suspense } from 'react';
import { RouterProvider } from 'react-router-dom';
import { router } from './router';
import { AuthProvider } from './hooks/useAuth';
import { RealtimeProvider } from './lib/realtime/RealtimeProvider';

function RouteChunkFallback(): JSX.Element {
  return (
    <div
      aria-label="Loading route"
      data-testid="route-chunk-fallback"
      style={{
        minHeight: '100vh',
        background: 'var(--bg, #05070a)',
      }}
    />
  );
}

export default function App(): JSX.Element {
  return (
    <AuthProvider>
      <RealtimeProvider>
        <Suspense fallback={<RouteChunkFallback />}>
          <RouterProvider router={router} />
        </Suspense>
      </RealtimeProvider>
    </AuthProvider>
  );
}
