"use client";

import type { IncomingPagePayload } from "@/lib/types";
import { PriorityBadge } from "./badges";
import { formatMMSS, useRemainingSeconds } from "@/lib/useElapsed";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

export function ActivePageCard({
  page,
  onAccept,
  onDecline,
}: {
  page: IncomingPagePayload;
  onAccept: () => void;
  onDecline: () => void;
}) {
  const remaining = useRemainingSeconds(page.created_at, page.ack_deadline_seconds);
  const overdue = remaining <= 0;

  return (
    <section
      className="medpage-card-in"
      style={{
        background: "var(--color-background-primary)",
        border: HAIRLINE,
        borderRadius: 12,
        padding: 16,
        boxShadow: "0 1px 0 rgba(0,0,0,0.02)",
      }}
    >
      <div className="flex items-start justify-between" style={{ gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Incoming page
          </div>
          <div
            style={{
              fontSize: 20,
              fontWeight: 600,
              color: "var(--color-text-primary)",
              marginTop: 4,
              lineHeight: 1.25,
              wordBreak: "break-word",
            }}
          >
            {page.title}
          </div>
          {page.room ? (
            <div style={{ fontSize: 13, color: "var(--color-text-secondary)", marginTop: 2 }}>
              {page.room}
            </div>
          ) : null}
        </div>
        <PriorityBadge priority={page.priority} />
      </div>

      <p
        style={{
          fontSize: 12,
          color: "var(--color-text-secondary)",
          background: "var(--color-background-secondary)",
          border: HAIRLINE,
          borderRadius: 8,
          padding: "8px 10px",
          margin: "12px 0 0",
          lineHeight: 1.4,
        }}
      >
        <span style={{ color: "var(--color-text-info)", fontWeight: 500, marginRight: 4 }}>AI:</span>
        {page.reasoning}
      </p>

      <div
        className="flex items-center justify-between"
        style={{ marginTop: 12, fontSize: 11, color: "var(--color-text-tertiary)" }}
      >
        <span>Auto-escalates in</span>
        <span
          style={{
            fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
            fontSize: 13,
            fontWeight: 500,
            color: overdue ? "var(--color-text-danger)" : "var(--color-text-primary)",
          }}
        >
          {formatMMSS(remaining)}
        </span>
      </div>

      <div className="grid gap-2" style={{ gridTemplateColumns: "1fr 1fr", marginTop: 12 }}>
        <button
          type="button"
          onClick={onDecline}
          style={{
            height: 44,
            borderRadius: 10,
            border: "0.5px solid #E24B4A",
            color: "#B23A38",
            background: "transparent",
            fontSize: 14,
            fontWeight: 500,
            cursor: "pointer",
            transition: "background 200ms ease",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "#FBE3E2"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
        >
          Decline
        </button>
        <button
          type="button"
          onClick={onAccept}
          style={{
            height: 44,
            borderRadius: 10,
            border: "0.5px solid #1D9E75",
            background: "#1D9E75",
            color: "#FFFFFF",
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
            transition: "background 200ms ease",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "#178A65"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "#1D9E75"; }}
        >
          Accept
        </button>
      </div>
    </section>
  );
}
