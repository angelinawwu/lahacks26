"use client";

import type { PatternSignal } from "@/lib/backendTypes";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

export function CoverageBanner({ patterns }: { patterns: PatternSignal[] }) {
  const holes = patterns.filter((p) => p.pattern_type === "coverage_hole");
  if (holes.length === 0) return null;
  return (
    <div
      role="status"
      style={{
        margin: "8px 12px 0",
        padding: "8px 12px",
        background: "#FBE3E2",
        border: "0.5px solid #E24B4A",
        borderRadius: 8,
        fontSize: 12,
        color: "#7A1F1D",
        lineHeight: 1.4,
        display: "flex",
        alignItems: "flex-start",
        gap: 8,
      }}
    >
      <span aria-hidden style={{ marginTop: 1 }}>⚠</span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 500, marginBottom: 2 }}>
          Coverage gap{holes.length > 1 ? "s" : ""} detected
        </div>
        <div>
          {holes
            .map((h) => h.specialty || h.zone || h.message || "Unknown area")
            .join(" · ")}
        </div>
      </div>
      <span aria-hidden style={{ flex: 1, borderTop: HAIRLINE, opacity: 0 }} />
    </div>
  );
}
