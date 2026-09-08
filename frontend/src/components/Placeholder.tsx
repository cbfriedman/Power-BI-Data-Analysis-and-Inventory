import type { ComponentType, SVGProps } from "react";

import { ClockIcon } from "@/components/icons";

interface PlaceholderProps {
  title: string;
  summary: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  /** What this screen will let someone do. Kept concrete, not aspirational. */
  capabilities?: readonly string[];
}

/**
 * A screen that is designed but not yet available.
 *
 * Says so plainly rather than rendering an empty table, which reads as broken
 * rather than unbuilt. Describing what the screen will do keeps the navigation
 * meaningful and lets a reviewer sanity-check the scope before it is built.
 *
 * Carries no delivery-schedule information: project status changes far more
 * often than this file does, so putting it here guarantees the interface
 * eventually tells someone something untrue.
 */
export function Placeholder({ title, summary, icon: IconComponent, capabilities }: PlaceholderProps) {
  return (
    <>
      <header className="page-header">
        <div className="page-header__title-row">
          <h1>{title}</h1>
          <span className="badge">
            <ClockIcon style={{ width: 12, height: 12 }} />
            Not yet available
          </span>
        </div>
      </header>

      <div className="empty">
        <span className="empty__icon">
          <IconComponent />
        </span>
        <h2 className="empty__title">{title}</h2>
        <p className="empty__text">{summary}</p>

        {capabilities && capabilities.length > 0 ? (
          <ul className="empty__list">
            {capabilities.map((capability) => (
              <li key={capability}>
                <ArrowGlyph />
                <span>{capability}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </>
  );
}

function ArrowGlyph() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}
