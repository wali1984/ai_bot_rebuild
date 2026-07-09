const DEFAULT_FAVORITES = new Set(['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT']);

/** Normalize and deduplicate a list of symbol strings into a valid Set, falling back to defaults if empty. */
export function marketFavoriteSymbolSet(symbols: string[]): Set<string> {
  const valid = symbols
    .map((s) => s.toUpperCase().trim())
    .filter((s) => /^[A-Z0-9]{3,20}$/.test(s));
  const deduplicated = [...new Set(valid)];
  return deduplicated.length > 0 ? new Set(deduplicated) : new Set(DEFAULT_FAVORITES);
}

export function normalizeWatchlistInput(value: string): string[] {
  return [...new Set(
    value
      .split(/[\s,]+/)
      .map((symbol) => symbol.trim().toUpperCase())
      .filter((symbol) => /^[A-Z0-9]{3,32}$/.test(symbol)),
  )].slice(0, 100);
}

const SOURCE_URL_LABELS: Record<string, string> = {
  '/api/v2/portfolio': 'Trader account source',
  'unavailable': 'Data source unavailable',
};

export function sourceText(input: string): string {
  return SOURCE_URL_LABELS[input] ?? input;
}
