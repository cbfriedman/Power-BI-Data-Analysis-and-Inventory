"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { NAV_ICONS } from "@/components/icons";
import { SidebarStatus } from "@/components/ApiStatus";
import { ThemeToggle } from "@/components/ThemeToggle";

interface NavItem {
  href: string;
  label: string;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

/**
 * Navigation grouped by the job being done rather than by table name.
 *
 * "Catalogue" is reference data you maintain; "Ingestion" is the recurring
 * operational loop; "Monitoring" is what you check. A flat list of nine links
 * makes the user work out those relationships for themselves.
 */
const NAV_GROUPS: readonly NavGroup[] = [
  {
    label: "Overview",
    items: [{ href: "/", label: "Dashboard" }],
  },
  {
    label: "Catalogue",
    items: [
      { href: "/products", label: "Products" },
      { href: "/vendors", label: "Vendors" },
    ],
  },
  {
    label: "Ingestion",
    items: [
      { href: "/imports", label: "Imports" },
      { href: "/profiles", label: "Import profiles" },
      { href: "/exceptions", label: "Exception queue" },
    ],
  },
  {
    label: "Monitoring",
    items: [
      { href: "/watchlist", label: "Watchlist" },
      { href: "/availability", label: "Availability" },
      { href: "/audit", label: "Audit log" },
    ],
  },
];

const PAGE_TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/products": "Products",
  "/vendors": "Vendors",
  "/imports": "Imports",
  "/profiles": "Import profiles",
  "/exceptions": "Exception queue",
  "/watchlist": "Watchlist",
  "/availability": "Availability",
  "/audit": "Audit log",
};

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar__brand">
          <span className="brand__mark" aria-hidden="true">
            PR
          </span>
          <span className="brand__text">
            <span className="brand__name">PRMS</span>
            <span className="brand__sub">Purchasing &amp; Replenishment</span>
          </span>
        </div>

        <nav className="sidebar__nav" aria-label="Main">
          {NAV_GROUPS.map((group) => (
            <div className="nav__group" key={group.label}>
              <div className="nav__group-label">{group.label}</div>
              <ul className="nav__list">
                {group.items.map((item) => {
                  const IconComponent = NAV_ICONS[item.href];
                  const isActive = pathname === item.href;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        className={`nav__link${isActive ? " nav__link--active" : ""}`}
                        aria-current={isActive ? "page" : undefined}
                      >
                        {IconComponent ? <IconComponent className="nav__icon" /> : null}
                        {item.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <div className="sidebar__footer">
          <SidebarStatus />
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <span className="topbar__title">{PAGE_TITLES[pathname] ?? "PRMS"}</span>
          <div className="topbar__actions">
            <ThemeToggle />
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
