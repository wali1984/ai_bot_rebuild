import type { ApiEnvelope, ApiErrorEnvelope } from "./envelope";
import { V2ApiError, isApiErrorEnvelope } from "./errors";

export type ApiClientOptions = {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
};

export class V2ApiClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? "/api/v1";
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  async get<T>(path: string): Promise<ApiEnvelope<T>> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method: "GET",
      headers: { Accept: "application/json" },
    });

    const body = await response.json();

    if (!response.ok || isApiErrorEnvelope(body)) {
      throw new V2ApiError(body as ApiErrorEnvelope);
    }

    return body as ApiEnvelope<T>;
  }
}
