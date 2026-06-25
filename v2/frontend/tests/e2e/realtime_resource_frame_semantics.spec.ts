import { expect, test } from '@playwright/test';
import type { ValidatedDataEnvelope } from '../../src/types/dataContract';
import { realtimeResourceTestHooks } from '../../src/hooks/useRealtimeResource';

type Payload = { price: number; frame: string };

function envelope(
  overrides: Partial<ValidatedDataEnvelope<Payload>> = {},
): ValidatedDataEnvelope<Payload> {
  return {
    data: { price: 100, frame: 'base' },
    source: '/api/v2/market/overview',
    source_type: 'websocket',
    endpoint: '/api/v2/market/overview',
    timestamp: Date.parse('2026-06-23T19:00:00Z'),
    received_at: Date.parse('2026-06-23T19:00:01Z'),
    lag_ms: 0,
    freshness_status: 'fresh',
    data_quality_status: 'valid',
    missing_fields: [],
    warnings: [],
    errors: [],
    mode: 'read_only',
    ...overrides,
  };
}

test.describe('realtime resource frame semantics', () => {
  test('preserves the current payload when a later frame is stale and incomplete', () => {
    const previous = envelope({ data: { price: 101, frame: 'current' } });
    const stale = envelope({
      data: null,
      timestamp: Date.parse('2026-06-23T19:00:05Z'),
      received_at: Date.parse('2026-06-23T19:00:06Z'),
      freshness_status: 'stale',
      data_quality_status: 'missing',
      missing_fields: ['data'],
      warnings: ['backend reported stale data'],
    });

    const merged = realtimeResourceTestHooks.mergeRealtimeResourceEnvelope(previous, stale);

    expect(merged.preservedReason).toBe('stale_or_incomplete');
    expect(merged.shouldCache).toBe(false);
    expect(merged.envelope.data).toEqual({ price: 101, frame: 'current' });
    expect(merged.envelope.received_at).toBe(stale.received_at);
    expect(merged.envelope.warnings).toContain('Latest resource frame was stale or incomplete; preserving last current payload');
  });

  test('preserves the current payload when a fresh frame arrives out of order', () => {
    const previous = envelope({
      data: { price: 102, frame: 'newer' },
      timestamp: Date.parse('2026-06-23T19:00:10Z'),
    });
    const older = envelope({
      data: { price: 99, frame: 'older' },
      timestamp: Date.parse('2026-06-23T19:00:02Z'),
      received_at: Date.parse('2026-06-23T19:00:12Z'),
    });

    const merged = realtimeResourceTestHooks.mergeRealtimeResourceEnvelope(previous, older);

    expect(merged.preservedReason).toBe('out_of_order');
    expect(merged.shouldCache).toBe(false);
    expect(merged.envelope.data).toEqual({ price: 102, frame: 'newer' });
    expect(merged.envelope.received_at).toBe(older.received_at);
    expect(merged.envelope.warnings).toContain('Latest resource frame was older than the current payload; preserving last current payload');
  });

  test('accepts duplicate current frames without adding preservation warnings', () => {
    const previous = envelope({
      data: { price: 102, frame: 'duplicate' },
      timestamp: Date.parse('2026-06-23T19:00:10Z'),
    });
    const duplicate = envelope({
      data: { price: 102, frame: 'duplicate' },
      timestamp: previous.timestamp,
      received_at: Date.parse('2026-06-23T19:00:12Z'),
    });

    const merged = realtimeResourceTestHooks.mergeRealtimeResourceEnvelope(previous, duplicate);

    expect(merged.preservedReason).toBeNull();
    expect(merged.shouldCache).toBe(true);
    expect(merged.envelope.data).toEqual({ price: 102, frame: 'duplicate' });
    expect(merged.envelope.warnings.join(' ')).not.toContain('preserving last current payload');
  });

  test('accepts current API fallback frames while keeping their source type visible', () => {
    const empty = envelope({
      data: null,
      source_type: 'unavailable',
      timestamp: null,
      received_at: null,
      freshness_status: 'unavailable',
      data_quality_status: 'missing',
    });
    const fallback = envelope({
      data: { price: 103, frame: 'api-fallback' },
      source_type: 'api',
      source: '/api/v2/market/overview',
      timestamp: Date.parse('2026-06-23T19:00:15Z'),
      freshness_status: 'fresh',
      data_quality_status: 'valid',
      warnings: ['HTTP fallback used after WebSocket disconnect'],
    });

    const merged = realtimeResourceTestHooks.mergeRealtimeResourceEnvelope(empty, fallback);

    expect(merged.preservedReason).toBeNull();
    expect(merged.shouldCache).toBe(true);
    expect(merged.envelope.source_type).toBe('api');
    expect(merged.envelope.warnings).toContain('HTTP fallback used after WebSocket disconnect');
  });

  test('parses backend frame timestamps before falling back to receive time', () => {
    const receivedAt = Date.parse('2026-06-23T19:01:00Z');

    expect(realtimeResourceTestHooks.resourceFrameTimestampMs(
      { timestamp: '2026-06-23T19:00:30Z' },
      receivedAt,
    )).toBe(Date.parse('2026-06-23T19:00:30Z'));

    expect(realtimeResourceTestHooks.resourceFrameTimestampMs(
      { received_at: Date.parse('2026-06-23T19:00:35Z') },
      receivedAt,
    )).toBe(Date.parse('2026-06-23T19:00:35Z'));

    expect(realtimeResourceTestHooks.resourceFrameTimestampMs(
      { generated_at: 'not-a-date' },
      receivedAt,
    )).toBe(receivedAt);
  });
});
