import Link from "next/link";
import type { ReactNode } from "react";

const NAV_ITEMS: ReadonlyArray<{ href: string; label: string }> = [
  { href: "/", label: "Overview" },
  { href: "/vendors", label: "Vendors" },
  { href: "/profiles", label: "Import profiles" },
  { href: "/imports", label: "Imports" },
  { href: "/exceptions", label: "Exception queue" },
  { href: "/products", label: "Products" },
  { href: "/watchlist", label: "Watchlist" },
  { href: "/availability", label: "Availability" },
  { href: "/audit", label: "Audit log" },
];

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="shell">
      <aside className="shell__sidebar">
        <div className="shell__brand">
          <span className="shell__brand-name">PRMS</span>
          <span className="shell__brand-sub">Milestone 1</span>
        </div>
        <nav aria-label="Main">
          <ul className="nav">
            {NAV_ITEMS.map((item) => (
              <li key={item.href}>
                <Link href={item.href} className="nav__link">
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </aside>
      <main className="shell__main">{children}</main>
    </div>
  );
}
