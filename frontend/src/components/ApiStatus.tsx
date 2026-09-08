"use client";

import { useEffect, useState } from "react";

import { DatabaseIcon, PlugIcon } from "@/components/icons";
import { fetchReadiness, type ReadinessResponse } from "@/lib/api-client";
import { apiBaseUrl } from "@/lib/config";

type State =
  | { kind: "loading" }
  | { kind: "loaded"; readiness: ReadinessResponse }
  | { kind: "unreachable" };

/**
 * Polls the readiness probe.
 *
 * Shared by the sidebar badge and the dashboard card so the two can never
 * disagree about whether the backend is up.
 */
function useReadiness(pollMs = 30_000): State {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    async function check() {
      try {
        const readiness = await fetchReadiness(controller.signal);
        if (!cancelled) setState({ kind: "loaded", readiness });
      } catch (error: unknown) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (!cancelled) setState({ kind: "unreachable" });
      }
    }

    void check();
    const timer = window.setInterval(() => void check(), pollMs);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [pollMs]);

  return state;
}

/** Compact indicator for the sidebar footer. */
export function SidebarStatus() {
  const state = useReadiness();

  const tone =
    state.kind === "loading"
      ? { className: "", label: "Checking…" }
      : state.kind === "unreachable"
        ? { className: "badge--danger", label: "Offline" }
        : state.readiness.status === "ok"
          ? { className: "badge--ok", label: "Operational" }
          : { className: "badge--warn", label: "Degraded" };

  return (
    <div className="status-mini">
      <span className={`badge ${tone.className}`}>
        <span className={`dot${state.kind === "loading" ? " dot--pulse" : ""}`} />
        {tone.label}
      </span>
      <span className="status-mini__label">System</span>
    </div>
  );
}

/** Full status card for the dashboard. */
export function SystemStatusCard() {
  const state = useReadiness();

  return (
    <div className="card">
      <div className="card__header">
        <span className="card__title">
          <PlugIcon />
          System status
        </span>
        {state.kind === "loaded" ? (
          <span
            className={`badge ${state.readiness.status === "ok" ? "badge--ok" : "badge--warn"}`}
          >
            <span className="dot" />
            {state.readiness.status === "ok" ? "All systems operational" : "Degraded"}
          </span>
        ) : state.kind === "unreachable" ? (
          <span className="badge badge--danger">
            <span className="dot" />
            Unreachable
          </span>
        ) : (
          <span className="badge">
            <span className="dot dot--pulse" />
            Checking…
          </span>
        )}
      </div>

      <div className="kv">
        <div className="kv__row">
          <span className="kv__key">
            <PlugIcon style={{ width: 15, height: 15 }} />
            API service
          </span>
          <span className="kv__value">
            {state.kind === "loaded"
              ? state.readiness.service
              : state.kind === "unreachable"
                ? "Not responding"
                : "—"}
          </span>
        </div>

        <div className="kv__row">
          <span className="kv__key">
            <DatabaseIcon style={{ width: 15, height: 15 }} />
            Database
          </span>
          <span className="kv__value">
            {state.kind === "loaded"
              ? (state.readiness.dependencies.find((d) => d.name === "postgresql")?.status ??
                "unknown")
              : "—"}
          </span>
        </div>

        <div className="kv__row">
          <span className="kv__key">Environment</span>
          <span className="kv__value">
            {state.kind === "loaded" ? state.readiness.environment : "—"}
          </span>
        </div>

        <div className="kv__row">
          <span className="kv__key">Endpoint</span>
          <span className="kv__value">
            <code>{apiBaseUrl}</code>
          </span>
        </div>
      </div>

      {state.kind === "unreachable" ? (
        <p className="card__note">
          The interface cannot reach the API at <code>{apiBaseUrl}</code>. Check that the
          backend is running and that <code>NEXT_PUBLIC_API_BASE_URL</code> points at it.
        </p>
      ) : null}
    </div>
  );
}
