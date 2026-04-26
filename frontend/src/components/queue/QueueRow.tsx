"use client";

import { useState } from "react";
import { PriorityBadge } from "@/components/badges";
import { EscalationChain } from "./EscalationChain";
import { formatMMSS } from "@/lib/useElapsed";
import type { QueuePage } from "@/lib/backendTypes";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

const PRIORITY_BORDER: Record<string, string> = {
  P1: "#E24B4A",
  P2: "#EF9F27",
  P3: "var(--color-border-info)",
  P4: "var(--color-border-tertiary)",
};

function pct(remaining?: number, total?: number): number {
  if (!remaining || !total || total <= 0) return 0;
  return Math.max(0, Math.min(1, remaining / total));
}

export function QueueRow({
  page,
  onEscalate,
  onCancel,
}: {
  page: QueuePage;
  onEscalate: (id: string) => Promise<void> | void;
  onCancel: (id: string) => Promise<void> | void;
}) {
  const [busy, setBusy] = useState<"escalate" | "cancel" | null>(null);

  const remaining = page.time_remaining_seconds ?? 0;
  const total = page.timeout_seconds ?? 60;
  const ratio = pct(remaining, total);
  const danger = ratio < 0.25;
  const escCount = page.escalation_count ?? page.escalation_history?.length ?? 0;
  const priority = String(page.priority ?? "P4");
  const borderColor = PRIORITY_BORDER[priority] ?? PRIORITY_BORDER.P4;

  async function run(action: "escalate" | "cancel") {
    if (busy) return;
    setBusy(action);
    try {
      if (action === "escalate") await onEscalate(page.id);
      else await onCancel(page.id);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div
      style={{
        padding: "10px 12px 10px 14px",
        borderBottom: HAIRLINE,
        borderLeft: `2px solid ${borderColor}`,
        background: "transparent",
        transition: "background 200ms ease",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = "var(--color-background-secondary)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "transparent";
      }}
    >
      <div className="flex items-start justify-between" style={{ gap: 8 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="flex items-center" style={{ gap: 6, marginBottom: 2 }}>
            <PriorityBadge priority={priority} />
            {escCount > 0 ? (
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 500,
                  color: "#7A1F1D",
                  background: "#FBE3E2",
                  padding: "1px 7px",
                  borderRadius: 20,
                }}
              >
                Escalated · {escCount}
              </span>
            ) : null}
            {page.room ? (
              <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
                {page.room}
              </span>
            ) : null}
          </div>
          <div
            style={{
              fontSize: 13,
              fontWeight: 500,
              color: "var(--color-text-primary)",
              lineHeight: 1.3,
              wordBreak: "break-word",
            }}
          >
            {page.message?.trim() || "Page"}
          </div>
          <div
            style={{
              fontSize: 11,
              color: "var(--color-text-secondary)",
              marginTop: 2,
            }}
          >
            {page.doctor?.name ?? page.doctor_id ?? "Unassigned"}
            {page.doctor?.specialty?.length
              ? ` · ${page.doctor.specialty.join(" · ")}`
              : ""}
          </div>
        </div>
        <div
          style={{
            fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
            fontSize: 12,
            fontWeight: 300,
            color: danger ? "var(--color-text-danger)" : "var(--color-text-primary)",
            whiteSpace: "nowrap",
          }}
        >
          {formatMMSS(remaining)}
        </div>
      </div>

      <div
        style={{
          marginTop: 8,
          height: 3,
          borderRadius: 20,
          background: "var(--color-background-secondary)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${Math.round(ratio * 100)}%`,
            height: "100%",
            background: danger ? "var(--color-text-danger)" : "var(--color-text-info)",
            transition: "width 400ms cubic-bezier(.165,.84,.44,1), background 200ms ease",
          }}
        />
      </div>

      {page.escalation_history && page.escalation_history.length > 0 ? (
        <EscalationChain
          history={page.escalation_history}
          currentDoctor={page.doctor_id}
          currentDoctorName={page.doctor?.name}
          compact
        />
      ) : null}

      <div className="flex items-center" style={{ gap: 6, marginTop: 8 }}>
        <button
          type="button"
          onClick={() => run("escalate")}
          disabled={busy !== null}
          style={{
            fontSize: 11,
            color: "var(--color-text-info)",
            padding: "3px 10px",
            border: "0.5px solid var(--color-border-info)",
            borderRadius: 20,
            background: "transparent",
            cursor: busy ? "not-allowed" : "pointer",
            transition: "background 200ms ease",
            opacity: busy && busy !== "escalate" ? 0.5 : 1,
          }}
          onMouseEnter={(e) => {
            if (!busy) e.currentTarget.style.background = "var(--color-background-info)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "transparent";
          }}
        >
          {busy === "escalate" ? "Escalating…" : "Escalate now"}
        </button>
        <button
          type="button"
          onClick={() => run("cancel")}
          disabled={busy !== null}
          style={{
            fontSize: 11,
            color: "#B23A38",
            padding: "3px 10px",
            border: "0.5px solid #E24B4A",
            borderRadius: 20,
            background: "transparent",
            cursor: busy ? "not-allowed" : "pointer",
            transition: "background 200ms ease",
            opacity: busy && busy !== "cancel" ? 0.5 : 1,
          }}
          onMouseEnter={(e) => {
            if (!busy) e.currentTarget.style.background = "#FBE3E2";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "transparent";
          }}
        >
          {busy === "cancel" ? "Cancelling…" : "Cancel"}
        </button>
      </div>
    </div>
  );
}
