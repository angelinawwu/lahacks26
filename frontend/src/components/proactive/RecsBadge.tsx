"use client";

import type { ProactiveRecommendation } from "@/lib/backendTypes";

export function RecsBadge({
  count,
  hasCritical,
  onClick,
}: {
  count: number;
  hasCritical?: boolean;
  onClick: () => void;
}) {
  const accent = hasCritical ? "#E24B4A" : "var(--color-text-info)";
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        position: "relative",
        fontSize: 12,
        padding: "4px 10px",
        border: "0.5px solid var(--color-border-tertiary)",
        borderRadius: 20,
        color: count > 0 ? "var(--color-text-primary)" : "var(--color-text-secondary)",
        background: "transparent",
        cursor: "pointer",
        transition: "background 200ms ease",
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = "var(--color-background-secondary)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "transparent";
      }}
      aria-label={`${count} pending recommendations`}
    >
      <span
        aria-hidden
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: count > 0 ? accent : "var(--color-text-tertiary)",
          boxShadow: count > 0 && hasCritical ? `0 0 0 0 ${accent}` : undefined,
          animation: count > 0 && hasCritical ? "polaris-pulse 1.4s ease-in-out infinite" : undefined,
          display: "inline-block",
        }}
      />
      Recs
      {count > 0 ? (
        <span
          style={{
            fontSize: 10,
            fontWeight: 500,
            color: "#FCEBEB",
            background: accent,
            padding: "1px 6px",
            borderRadius: 20,
            lineHeight: 1.6,
          }}
        >
          {count}
        </span>
      ) : null}
    </button>
  );
}

export function hasCriticalRec(recs: ProactiveRecommendation[]): boolean {
  return recs.some((r) => r.severity === "critical" || r.severity === "high");
}
