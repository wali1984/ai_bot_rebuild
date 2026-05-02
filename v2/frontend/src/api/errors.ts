import type { ApiErrorEnvelope } from "./envelope";

export class V2ApiError extends Error {
  readonly envelope: ApiErrorEnvelope;

  constructor(envelope: ApiErrorEnvelope) {
    super(envelope.error.message);
    this.name = "V2ApiError";
    this.envelope = envelope;
  }
}

export function isApiErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (!value || typeof value !== "object") return false;
  const maybe = value as { error?: unknown };
  return !!maybe.error && typeof maybe.error === "object";
}
