"use client";

import { useEffect, useState } from "react";

import { fetchReadiness, type ReadinessResponse } from "@/lib/api-client";
import { apiBaseUrl } from "@/lib/config";

type State =
  | { kind: "loading" }
  | { kind: "loaded"; readiness: ReadinessResponse }
  | { kind: "unreachable" };

/**
 * Live API status indicator.
 *
 * Doubles as a check that the environment-based API URL is wired correctly:
 * if NEXT_PUBLIC_API_BASE_URL is wrong, this says so immediately.
 */
export function ApiStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    fetchReadiness(controller.signal)
      .then((readiness) => setState({ kind: "loaded", readiness }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({ kind: "unreachable" });
      });

    return () => controller.abort();
  }, []);

  if (state.kind === "loading") {
    return (
      <p className="status status--pending">
        <span className="status__dot" /> Checking API…
      </p>
    );
  }

  if (state.kind === "unreachable") {
    return (
      <p className="status status--error">
        <span className="status__dot" /> API unreachable at <code>{apiBaseUrl}</code>
      </p>
    );
  }

  const { readiness } = state;
  const healthy = readiness.status === "ok";

  return (
    <div className={`status ${healthy ? "status--ok" : "status--warn"}`}>
      <p>
        <span className="status__dot" /> API <strong>{readiness.status}</strong> · {readiness.service}{" "}
        · env <code>{readiness.environment}</code>
      </p>
      <ul className="status__deps">
        {readiness.dependencies.map((dependency) => (
          <li key={dependency.name}>
            {dependency.name}: <strong>{dependency.status}</strong>
            {dependency.detail ? ` — ${dependency.detail}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}
