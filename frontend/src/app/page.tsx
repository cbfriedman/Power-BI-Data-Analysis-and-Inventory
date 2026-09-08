import { ApiStatus } from "@/components/ApiStatus";
import { apiBaseUrl } from "@/lib/config";

export default function OverviewPage() {
  return (
    <section>
      <header className="placeholder__header">
        <h1>Overview</h1>
        <span className="badge">Phase 0 — scaffold</span>
      </header>

      <p className="placeholder__summary">
        Purchasing &amp; Replenishment Management System, Milestone 1. The application shell and
        backend scaffold are in place; no business logic is implemented yet.
      </p>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Backend connectivity</h2>
        <ApiStatus />
        <p className="placeholder__note" style={{ marginTop: 14 }}>
          Configured API base URL: <code>{apiBaseUrl}</code> (from{" "}
          <code>NEXT_PUBLIC_API_BASE_URL</code>)
        </p>
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>What exists</h2>
        <ul className="list">
          <li>FastAPI backend with liveness and readiness probes</li>
          <li>PostgreSQL via Docker Compose, with a named volume and health check</li>
          <li>SQLAlchemy 2 base and Alembic wiring — no business tables yet</li>
          <li>Structured JSON logging with request correlation ids</li>
          <li>Ruff, mypy, and pytest configured and passing</li>
          <li>This Next.js shell with placeholder screens</li>
        </ul>
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>What is next</h2>
        <ul className="list">
          <li>Phase 1 — database foundation and audit logging</li>
          <li>Phase 2 — vendor database</li>
          <li>Phase 3 — Nineyard integration (blocked on the API specification)</li>
        </ul>
      </div>
    </section>
  );
}
