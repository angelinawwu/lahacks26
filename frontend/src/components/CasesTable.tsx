"use client";

import type { CSSProperties } from "react";
import type { AlertEvent } from "@/lib/types";
import { PriorityBadge, StatusChip } from "./badges";
import { formatMMSS, useElapsedSeconds } from "@/lib/useElapsed";
import { inferFloor } from "@/lib/floorData";
import type { FloorId } from "@/lib/floorData";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

const thStyle: CSSProperties = {
  fontSize: 11,
  fontWeight: 500,
  color: "var(--color-text-secondary)",
  textAlign: "left",
  padding: "8px 12px",
  borderBottom: HAIRLINE,
  textTransform: "uppercase",
  letterSpacing: "0.05em",
};

const tdStyle: CSSProperties = {
  fontSize: 12,
  padding: "10px 12px",
  borderBottom: HAIRLINE,
  color: "var(--color-text-primary)",
  verticalAlign: "top",
};

function specialtyLabel(specialty?: string[] | null): string {
  if (!specialty || specialty.length === 0) return "—";
  return specialty
    .map((s) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()))
    .join(" · ");
}

function CaseTimer({ a }: { a: AlertEvent }) {
  const elapsed = useElapsedSeconds(a.created_at);
  const isLive = a.status === "paging" || a.status === "awaiting" || a.status === "escalating";
  if (isLive) {
    return (
      <span style={{ fontSize: 11, color: "var(--color-text-danger)", fontWeight: 500 }}>
        {formatMMSS(elapsed)}
      </span>
    );
  }
  const min = Math.floor(elapsed / 60);
  return (
    <span style={{ color: "var(--color-text-secondary)", fontSize: 11 }}>
      {min < 1 ? "<1 min" : `${min} min`}
    </span>
  );
}

export function CasesTable({
  cases,
  onOverride,
  onFloorSelect,
}: {
  cases: AlertEvent[];
  onOverride?: (a: AlertEvent) => void;
  onFloorSelect?: (floor: FloorId) => void;
}) {
  const awaiting = cases.filter(
    (c) => c.status === "paging" || c.status === "awaiting",
  ).length;
  const escalating = cases.filter((c) => c.status === "escalating").length;

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full" style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={thStyle}>Case</th>
              <th style={thStyle}>Priority</th>
              <th style={thStyle}>Assigned to</th>
              <th style={thStyle}>Status</th>
              <th style={thStyle}>Timer</th>
              <th style={thStyle}></th>
            </tr>
          </thead>
          <tbody>
            {cases.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ ...tdStyle, color: "var(--color-text-tertiary)", textAlign: "center", padding: "32px 12px" }}>
                  No active cases.
                </td>
              </tr>
            ) : null}
            {cases.map((a) => {
              const action = a.status === "escalating" ? "Reassign" : "Override";
              return (
                <tr
                  key={a.alert_id}
                  onClick={() => {
                    if (a.room && onFloorSelect) {
                      const floor = inferFloor(a.room);
                      onFloorSelect(floor);
                    }
                  }}
                  style={{ cursor: a.room ? "pointer" : "default" }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "var(--color-background-secondary)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "transparent";
                  }}
                >
                  <td style={tdStyle}>
                    <span style={{ fontWeight: 500 }}>{a.title}</span>
                    <br />
                    <span style={{ color: "var(--color-text-tertiary)", fontSize: 11 }}>
                      {a.room ? `${a.room} · ` : ""}Active case
                    </span>
                  </td>
                  <td style={tdStyle}>
                    <PriorityBadge priority={a.priority} />
                  </td>
                  <td style={tdStyle}>
                    {a.assigned_clinician_name ? (
                      <>
                        <span style={{ fontWeight: 500 }}>{a.assigned_clinician_name}</span>
                        <br />
                        <span style={{ color: "var(--color-text-tertiary)", fontSize: 11 }}>
                          {specialtyLabel(a.specialty)}
                        </span>
                      </>
                    ) : (
                      <>
                        <span style={{ fontWeight: 500 }}>Escalating…</span>
                        <br />
                        <span style={{ color: "var(--color-text-danger)", fontSize: 11 }}>
                          No assigned clinician
                        </span>
                      </>
                    )}
                  </td>
                  <td style={tdStyle}>
                    <StatusChip status={a.status} />
                  </td>
                  <td style={tdStyle}>
                    <CaseTimer a={a} />
                  </td>
                  <td style={tdStyle}>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onOverride?.(a);
                      }}
                      style={{
                        fontSize: 11,
                        color: "var(--color-text-info)",
                        padding: "3px 8px",
                        border: "0.5px solid var(--color-border-info)",
                        borderRadius: 20,
                        whiteSpace: "nowrap",
                        background: "transparent",
                        cursor: "pointer",
                        transition: "background 200ms ease",
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = "var(--color-background-info)";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = "transparent";
                      }}
                    >
                      {action}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div
        style={{
          padding: "12px 14px",
          borderTop: HAIRLINE,
          fontSize: 12,
          color: "var(--color-text-secondary)",
        }}
      >
        {cases.length} active case{cases.length === 1 ? "" : "s"} · {awaiting}{" "}
        awaiting acknowledgment · {escalating} escalating
      </div>
    </div>
  );
}
