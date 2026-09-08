/**
 * Minimal API client.
 *
 * Deliberately small at scaffold stage. Once endpoints exist, the response
 * types here are replaced by types generated from the FastAPI OpenAPI schema
 * (`openapi-typescript`), so the contract has one source of truth.
 */

import { apiUrl } from "./config";

export interface DependencyHealth {
  name: string;
  status: "ok" | "unavailable";
  detail: string | null;
}

export interface ReadinessResponse {
  status: "ok" | "degraded";
  service: string;
  environment: string;
  api_version: string;
  checked_at: string;
  dependencies: DependencyHealth[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly statusCode: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(apiUrl(path), {
    signal,
    headers: { Accept: "application/json" },
    cache: "no-store",
  });

  if (!response.ok && response.status !== 503) {
    throw new ApiError(`Request to ${path} failed`, response.status);
  }

  return (await response.json()) as T;
}

/**
 * Read the API readiness probe.
 *
 * A 503 is a meaningful answer here, not a failure: it means the API is up but
 * a dependency is down, which is exactly what the shell should display.
 */
export function fetchReadiness(signal?: AbortSignal): Promise<ReadinessResponse> {
  return getJson<ReadinessResponse>("/health", signal);
}
