import { useEffect, useState } from "react";

import type { Level } from "./types";

// Rain rate [mm/h] is a magnitude, so it uses one hue from light to dark.
// Each entry is [lower bound, colour]; below the first bound counts as dry.
export const RAIN_STEPS: [number, string][] = [
  [0.1, "#cde2fb"],
  [0.5, "#9ec5f4"],
  [1, "#6da7ec"],
  [2, "#3987e5"],
  [5, "#2a78d6"],
  [10, "#1c5cab"],
  [20, "#184f95"],
  [50, "#0d366b"],
];

export function rainColor(rate: number | null | undefined): string | null {
  if (rate == null || rate < RAIN_STEPS[0][0]) return null;
  let color = RAIN_STEPS[0][1];
  for (const [bound, c] of RAIN_STEPS) if (rate >= bound) color = c;
  return color;
}

export function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

// Status colours are reserved for risk levels and always shown with a label
export const RISK: Record<Level, { color: string; label: string }> = {
  low: { color: "#0ca30c", label: "Low" },
  medium: { color: "#fab219", label: "Medium" },
  high: { color: "#d03b3b", label: "High" },
};

export interface SeriesColors {
  estimate: string;
  gauge: string;
  grid: string;
  axis: string;
  surface: string;
}

export const SERIES: Record<"light" | "dark", SeriesColors> = {
  light: { estimate: "#2a78d6", gauge: "#eb6834", grid: "#e1e0d9", axis: "#898781", surface: "#fcfcfb" },
  dark: { estimate: "#3987e5", gauge: "#d95926", grid: "#2c2c2a", axis: "#898781", surface: "#1a1a19" },
};

export function usePrefersDark(): boolean {
  const query = "(prefers-color-scheme: dark)";
  const [dark, setDark] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const onChange = (e: MediaQueryListEvent) => setDark(e.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return dark;
}
