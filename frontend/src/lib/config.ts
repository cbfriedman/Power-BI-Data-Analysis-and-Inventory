/**
 * Environment-derived frontend configuration.
 *
 * NEXT_PUBLIC_* values are inlined into the browser bundle at build time, so
 * they are public by definition. Never put a secret in one.
 *
 * The URL must be reachable from the BROWSER, not from inside the Docker
 * network — so it is `http://localhost:8000`, not `http://api:8000`.
 */

const DEFAULT_API_BASE_URL = "http://localhost:8000";

export const apiBaseUrl: string =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/+$/, "") ?? DEFAULT_API_BASE_URL;

export const apiV1Prefix = "/api/v1";

/** Build an absolute URL for a versioned API path. */
export function apiUrl(path: string): string {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${apiBaseUrl}${apiV1Prefix}${suffix}`;
}
