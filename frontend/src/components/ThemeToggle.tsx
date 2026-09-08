"use client";

import { useEffect, useState } from "react";

import { MoonIcon, SunIcon } from "@/components/icons";

type Theme = "light" | "dark";
const STORAGE_KEY = "prms-theme";

/**
 * Light/dark toggle.
 *
 * Until mounted it renders a neutral placeholder, because the server cannot
 * know the stored preference and rendering the wrong icon first produces a
 * visible flash. Preference lives in localStorage — a per-viewer convenience,
 * not shared state — and every access is guarded, since a browser set to block
 * site data throws on read.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    let stored: Theme | null = null;
    try {
      const value = window.localStorage.getItem(STORAGE_KEY);
      stored = value === "light" || value === "dark" ? value : null;
    } catch {
      stored = null;
    }

    const resolved =
      stored ??
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    setTheme(resolved);
    document.documentElement.dataset.theme = resolved;
  }, []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // A browser blocking site data is not a reason to refuse the change; it
      // simply will not persist across reloads.
    }
  }

  if (theme === null) {
    return <span className="icon-button" aria-hidden="true" />;
  }

  return (
    <button
      type="button"
      className="icon-button"
      onClick={toggle}
      aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
    >
      {theme === "dark" ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}
