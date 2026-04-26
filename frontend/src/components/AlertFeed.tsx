"use client";

import type { AlertEvent } from "@/lib/types";
import type { PatternSignal } from "@/lib/backendTypes";
import { PriorityBadge } from "./badges";
import { PatternBadge } from "./proactive/PatternBadge";
import { formatMMSS, useElapsedSeconds } from "@/lib/useElapsed";
import { inferFloor, inferFloorWing } from "@/lib/floorData";
import type { FloorId, WingId } from "@/lib/floorData";

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

function matchPattern(a: AlertEvent, patterns: PatternSignal[] | undefined): PatternSignal | null {
  if (!patterns || patterns.length === 0) return null;
  const room = (a.room ?? "").toLowerCase();
  const specs = (a.specialty ?? []).map((s) => s.toLowerCase());
  for (const p of patterns) {
    const zone = (p.zone ?? "").toLowerCase();
    const spec = (p.specialty ?? "").toLowerCase();
    const rooms = (p.rooms ?? []).map((r) => r.toLowerCase());
    if (zone && room && (room === zone || room.includes(zone))) return p;
    if (rooms.length && room && rooms.some((r) => room === r || room.includes(r))) return p;
    if (spec && specs.includes(spec)) return p;
  }
  return null;
}

export function AlertFeed({
  alerts,
  patterns,
  onSelect,
  onFloorSelect,
  onAlertSelect,
}: {
  alerts: AlertEvent[];
  patterns?: PatternSignal[];
  onSelect?: (alert: AlertEvent) => void;
  onFloorSelect?: (floor: FloorId) => void;
  onAlertSelect?: (alert: { alert_id: string; floor: FloorId; wing: WingId; zone: string; priority: "P1" | "P2" | "P3" | "P4" } | null) => void;
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
        {alerts.map((a) => {
          const pattern = matchPattern(a, patterns);
          return (
          <button
            key={a.alert_id}
            type="button"
            onClick={() => {
              onSelect?.(a);
              if (a.room && onFloorSelect) {
                const floor = inferFloor(a.room);
                onFloorSelect(floor);
                
                // Also set the selected alert for flashing
                if (onAlertSelect) {
                  // Convert AlertEvent to ActiveAlert format
                  const { wing } = inferFloorWing(a.room);
                  const activeAlert = {
                    alert_id: a.alert_id,
                    floor: floor,
                    wing: wing,
                    zone: a.room || "",
                    priority: a.priority as "P1" | "P2" | "P3" | "P4"
                  };
                  onAlertSelect(activeAlert);
                }
              }
            }}
            className="block w-full text-left"
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
            <div className="flex items-start justify-between" style={{ marginBottom: 3, gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text-primary)", minWidth: 0 }}>
                {a.title}
              </span>
              <div className="flex items-center" style={{ gap: 4, flexShrink: 0 }}>
                {pattern ? (
                  <PatternBadge
                    pattern={pattern.pattern_type}
                    zone={pattern.zone}
                    severity={pattern.severity}
                  />
                ) : null}
                <PriorityBadge priority={a.priority} />
              </div>
            </div>
            <div style={{ fontSize: 11, color: "var(--color-text-secondary)", lineHeight: 1.4 }}>
              {subText(a)}
            </div>
          </button>
          );
        })}
      </div>
    </div>
  );
}

export function isAlertLive(a: AlertEvent): boolean {
  return isLive(a.status);
}
