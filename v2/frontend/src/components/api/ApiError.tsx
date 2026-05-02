interface ApiErrorPayload {
  class: string;
  message: string;
}

interface Props {
  error: ApiErrorPayload;
  requestId: string | null;
}

export function ApiError({ error, requestId }: Props): JSX.Element {
  return (
    <div role="alert" className="api-error" data-testid="api-error">
      <div><strong>error.class:</strong> <code>{error.class}</code></div>
      <div><strong>error.message:</strong> {error.message}</div>
      <div><strong>request_id:</strong> <code>{requestId ?? 'unknown'}</code></div>
    </div>
  );
}
