// Shared detection + one-shot reload for stale dynamic-import (code-split) chunks
// after a redeploy. Used by the global handlers in main.tsx AND the router error
// boundary, since React Router catches lazy-import failures before they reach
// window error handlers.

const RELOAD_KEY = 'nervyx-chunk-reload-at';

export function isStaleChunkError(input: unknown): boolean {
  const text = String(
    (typeof input === 'object' && input !== null && 'message' in input
      ? (input as { message?: unknown }).message
      : input) ?? '',
  ).toLowerCase();
  return (
    text.includes('dynamically imported module') ||       // Chrome / Firefox / router
    text.includes('importing a module script failed') ||  // Safari
    text.includes('error loading dynamically imported') ||
    text.includes('chunkloaderror') ||
    (text.includes('failed to fetch') && text.includes('module'))
  );
}

/** Reload once (rate-limited) so the browser fetches the fresh index.html + chunks. */
export function reloadForStaleChunkOnce(): boolean {
  const last = Number(sessionStorage.getItem(RELOAD_KEY) || 0);
  if (Date.now() - last > 15_000) {
    sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
    window.location.reload();
    return true;
  }
  return false;
}
