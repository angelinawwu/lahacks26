"use client";

import type { AlertEvent } from "@/lib/types";
import { PriorityBadge } from "./badges";
import { formatMMSS, useElapsedSeconds } from "@/lib/useElapsed";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

function isLive(status: string) {
  return status === "paging" || status === "awaiting" || status === "escalating";
}

function LiveTimer({ iso }: { iso: string }) {
  const elapsed = useElapsedSeconds(iso);
  return (
    <span style={{ color: "var(--color-text-danger)", fontWeight: 500 }}>
      {formatMMSS(elapsed)}
    </span>
  );
}

function relativeAgo(iso?: string): string {
  if (!iso) return "";
  const ms = Date.now() - Date.parse(iso);
  if (Number.isNaN(ms)) return "";
  const min = Math.floor(ms / 60000);
  if (min < 1) return "just now";
  if (min === 1) return "1 min ago";
  if (min < 60) return `${min} min ago`;
  const hr = Math.floor(min / 60);
  return hr === 1 ? "1 hr ago" : `${hr} hr ago`;
}

function subText(a: AlertEvent) {
  const who = a.assigned_clinician_name ? `Dr. ${a.assigned_clinician_name.replace(/^Dr\.?\s*/, "")}` : null;
  switch (a.status) {
    case "paging":
    case "awaiting":
      return who ? <>Paging {who} · <LiveTimer iso={a.created_at} /></> : <>Paging · <LiveTimer iso={a.created_at} /></>;
    case "escalating":
      return <>Escalated · No response · <LiveTimer iso={a.created_at} /></>;
    case "accepted":
    case "en_route":
      return <>Accepted{who ? ` — ${who}` : ""} · {relativeAgo(a.responded_at ?? a.created_at)}</>;
    case "declined":
      return <>Declined{who ? ` — ${who}` : ""} · {relativeAgo(a.responded_at ?? a.created_at)}</>;
    case "resolved":
      return <>Resolved{who ? ` · ${who}` : ""} · {relativeAgo(a.responded_at ?? a.created_at)}</>;
    case "queued":
      return <>Queued · {relativeAgo(a.created_at)}</>;
    default:
      return <>{a.status} · {relativeAgo(a.created_at)}</>;
  }
}

export function AlertFeed({
  alerts,
  onSelect,
}: {
  alerts: AlertEvent[];
  onSelect?: (alert: AlertEvent) => void;
}) {
  return (
    <div
      className="flex h-full flex-col overflow-hidden"
      style={{ background: "var(--color-background-primary)" }}
    >
      <div
        className="flex items-center justify-between"
        style={{
          padding: "10px 12px 8px",
          fontSize: 11,
          fontWeight: 500,
          color: "var(--color-text-secondary)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          borderBottom: HAIRLINE,
        }}
      >
        <span>Alert feed</span>
        <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", fontWeight: 400 }}>
          {alerts.length === 0 ? "Idle" : "Live"}
        </span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {alerts.length === 0 ? (
          <div
            className="px-3 py-8 text-center"
            style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}
          >
            No alerts yet — waiting for dispatch.
          </div>
        ) : null}
        {alerts.map((a) => (
          <button
            key={a.alert_id}
            type="button"
            onClick={() => onSelect?.(a)}
            className="block w-full text-left transition-colors duration-200"
            style={{
              padding: "10px 12px",
              borderBottom: HAIRLINE,
              background: "transparent",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "var(--color-background-secondary)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "transparent";
            }}
          >
            <div className="flex items-start justify-between" style={{ marginBottom: 3 }}>
              <span style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text-primary)" }}>
                {a.title}
              </span>
              <PriorityBadge priority={a.priority} />
            </div>
            <div style={{ fontSize: 11, color: "var(--color-text-secondary)", lineHeight: 1.4 }}>
              {subText(a)}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

export function isAlertLive(a: AlertEvent): boolean {
  return isLive(a.status);
}
