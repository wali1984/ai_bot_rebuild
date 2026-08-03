const ISO_TIMESTAMP_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/;

const estFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

function partMap(date: Date): Record<string, string> {
  return Object.fromEntries(estFormatter.formatToParts(date).map((part) => [part.type, part.value]));
}

export function isIsoTimestampString(value: unknown): value is string {
  return typeof value === 'string' && ISO_TIMESTAMP_RE.test(value);
}

export function formatEstTimestamp(value: unknown): string {
  if (!isIsoTimestampString(value)) return value === null || value === undefined || value === '' ? 'Timestamp pending' : String(value);
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const parts = partMap(date);
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second} EST`;
}

export function formatEstIfTimestamp(value: unknown): string | null {
  return isIsoTimestampString(value) ? formatEstTimestamp(value) : null;
}
