"use client";

import type { CSSProperties } from "react";
import type { PatternType } from "@/lib/backendTypes";

const TONES: Record<string, { bg: string; fg: string; label: string }> = {
  alert_concentration: { bg: "var(--color-background-info)", fg: "var(--color-text-info)", label: "Cluster" },
  ack_gap:             { bg: "#FAEEDA", fg: "#633806", label: "ACK gap" },
  coverage_hole:       { bg: "#FBE3E2", fg: "#7A1F1D", label: "Coverage gap" },
  caseload_concentration: { bg: "var(--color-background-secondary)", fg: "var(--color-text-secondary)", label: "Caseload" },
};

const SEVERITY_DOT: Record<string, string> = {
  critical: "#E24B4A",
  high: "#EF9F27",
  medium: "var(--color-text-info)",
  low: "var(--color-text-tertiary)",
};

const pillStyle = (bg: string, fg: string): CSSProperties => ({
  background: bg,
  color: fg,
  fontSize: 10,
  fontWeight: 500,
  padding: "1px 7px",
  borderRadius: 20,
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  lineHeight: 1.5,
  whiteSpace: "nowrap",
});

export function PatternBadge({
  pattern,
  zone,
  severity,
  label,
}: {
  pattern: PatternType | string;
  zone?: string;
  severity?: string;
  label?: string;
}) {
  const tone = TONES[pattern] ?? TONES.caseload_concentration;
  const text = label ?? (zone ? `${tone.label}: ${zone}` : tone.label);
  return (
    <span style={pillStyle(tone.bg, tone.fg)}>
      {severity ? (
        <span
          aria-hidden
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: SEVERITY_DOT[severity] ?? SEVERITY_DOT.medium,
            display: "inline-block",
          }}
        />
      ) : null}
      {text}
    </span>
  );
}

export function severityColor(sev?: string): string {
  return SEVERITY_DOT[sev ?? "medium"] ?? SEVERITY_DOT.medium;
}
