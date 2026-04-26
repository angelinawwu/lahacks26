"use client";

import type { EscalationEntry } from "@/lib/backendTypes";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

function formatId(id: string | null | undefined): string {
  if (!id) return "—";
  return id.replace(/^dr_/, "Dr. ").replace(/_/g, " ");
}

function shortTime(iso?: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  } catch {
    return "";
  }
}

export function EscalationChain({
  history,
  currentDoctor,
  currentDoctorName,
  compact = false,
}: {
  history: EscalationEntry[];
  currentDoctor?: string | null;
  currentDoctorName?: string | null;
  compact?: boolean;
}) {
  if (!history || history.length === 0) return null;

  // Build a deduped list: each from_doctor (older), ending with the most recent to_doctor.
  const chain: { id: string; ts?: string; reason?: string }[] = [];
  history.forEach((h, i) => {
    if (i === 0 && h.from_doctor) {
      chain.push({ id: h.from_doctor, ts: undefined });
    }
    chain.push({ id: h.to_doctor, ts: h.timestamp, reason: h.reason });
  });

  return (
    <div
      style={{
        marginTop: 6,
        padding: compact ? "6px 8px" : "8px 10px",
        background: "var(--color-background-tertiary)",
        border: HAIRLINE,
        borderRadius: 8,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 500,
          color: "var(--color-text-tertiary)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          marginBottom: 4,
        }}
      >
        Escalation chain · {history.length}
      </div>
      <div
        className="flex items-center"
        style={{ flexWrap: "wrap", gap: 4, fontSize: 11 }}
      >
        {chain.map((node, i) => {
          const isLast = i === chain.length - 1;
          const isCurrent = isLast && currentDoctor && node.id === currentDoctor;
          const label = isCurrent && currentDoctorName ? currentDoctorName : formatId(node.id);
          return (
            <span key={`${node.id}-${i}`} className="flex items-center" style={{ gap: 4 }}>
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  padding: "2px 7px",
                  borderRadius: 20,
                  background: isLast
                    ? "var(--color-background-info)"
                    : "var(--color-background-secondary)",
                  color: isLast
                    ? "var(--color-text-info)"
                    : "var(--color-text-secondary)",
                  fontWeight: isLast ? 500 : 400,
                  textDecoration: !isLast ? "line-through" : "none",
                  textDecorationColor: "var(--color-text-tertiary)",
                  whiteSpace: "nowrap",
                }}
                title={node.ts ? `${shortTime(node.ts)}${node.reason ? ` · ${node.reason}` : ""}` : undefined}
              >
                {label}
                {node.ts ? (
                  <span style={{ color: "var(--color-text-tertiary)", fontSize: 10 }}>
                    {shortTime(node.ts)}
                  </span>
                ) : null}
              </span>
              {!isLast ? (
                <span style={{ color: "var(--color-text-tertiary)" }}>→</span>
              ) : null}
            </span>
          );
        })}
      </div>
    </div>
  );
}
