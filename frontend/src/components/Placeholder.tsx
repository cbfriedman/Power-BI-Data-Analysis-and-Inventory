import type { ReactNode } from "react";

interface PlaceholderProps {
  title: string;
  phase: string;
  summary: string;
  children?: ReactNode;
}

/**
 * Placeholder for a screen that is scoped but not yet built.
 *
 * States which phase delivers it, so the shell is honest about what exists
 * rather than implying working features.
 */
export function Placeholder({ title, phase, summary, children }: PlaceholderProps) {
  return (
    <section className="placeholder">
      <header className="placeholder__header">
        <h1>{title}</h1>
        <span className="badge">{phase}</span>
      </header>
      <p className="placeholder__summary">{summary}</p>
      {children}
      <p className="placeholder__note">
        Not implemented yet. This scaffold contains no business logic — see{" "}
        <code>docs/phase1-status.md</code> for what is built and what is next.
      </p>
    </section>
  );
}
