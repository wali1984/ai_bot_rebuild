export type ApiEnvelope<T> = {
  schema_version: string;
  request_id: string;
  server_ts_ms: number;
  result: T;
};

export type ApiErrorEnvelope = {
  schema_version: string;
  request_id: string;
  server_ts_ms: number;
  error: {
    code: string;
    class: string;
    http_status: number;
    message: string;
    field?: string | null;
    retriable: boolean;
    retry_after_ms?: number | null;
    details?: Record<string, unknown>;
  };
};
