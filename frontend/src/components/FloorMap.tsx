"use client";

import { useState } from "react";
import { AnimatePresence } from "framer-motion";
import { FLOOR_IDS, STATUS_COLORS, type FloorId } from "@/lib/floorData";
import type { ActiveAlert, ClinicianPin } from "@/lib/types";
import { FloorStack } from "./map/FloorStack";
import { FloorPlan } from "./map/FloorPlan";

const STATUS_LEGEND: { label: string; status: keyof typeof STATUS_COLORS }[] = [
  { label: "Available", status: "available" },
  { label: "Paging", status: "paging" },
  { label: "In procedure", status: "in_procedure" },
  { label: "On case", status: "on_case" },
  { label: "Off shift", status: "off_shift" },
];

export type FloorMapProps = {
  clinicians: ClinicianPin[];
  alerts: ActiveAlert[];
  onClinicianClick?: (id: string) => void;
};

export function FloorMap({ clinicians, alerts, onClinicianClick }: FloorMapProps) {
  const [selectedFloor, setSelectedFloor] = useState<FloorId | null>(null);

  return (
    <div className="flex h-full w-full flex-col" style={{ background: "#F1F5F9" }}>
      {/* Floor selector pills */}
      <div
        className="flex items-center gap-2"
        style={{
          padding: "10px 14px",
          borderBottom: "1px solid #E2E8F0",
          background: "#FFFFFF",
        }}
      >
        <span style={{ fontSize: 11, color: "#64748B", marginRight: 4 }}>FLOOR</span>
        {FLOOR_IDS.map((id) => {
          const active = selectedFloor === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => setSelectedFloor(id)}
              style={{
                fontSize: 12,
                fontWeight: 500,
                padding: "4px 12px",
                borderRadius: 999,
                border: "1px solid #CBD5E1",
                background: active ? "#0F172A" : "transparent",
                color: active ? "#F8FAFC" : "#0F172A",
                cursor: "pointer",
                transition: "background 200ms ease, color 200ms ease",
              }}
            >
              {id}
            </button>
          );
        })}
        <div style={{ flex: 1 }} />
        {selectedFloor ? (
          <button
            type="button"
            onClick={() => setSelectedFloor(null)}
            style={{
              fontSize: 12,
              padding: "4px 12px",
              borderRadius: 999,
              border: "1px solid #CBD5E1",
              background: "transparent",
              color: "#0F172A",
              cursor: "pointer",
              transition: "background 200ms ease",
            }}
          >
            ← All floors
          </button>
        ) : null}
      </div>

      {/* Map area */}
      <div className="relative flex-1 overflow-hidden">
        <AnimatePresence mode="wait">
          {selectedFloor ? (
            <div key={`plan-${selectedFloor}`} className="absolute inset-0">
              <FloorPlan
                floor={selectedFloor}
                clinicians={clinicians}
                alerts={alerts}
                onClinicianClick={onClinicianClick}
                onBack={() => setSelectedFloor(null)}
              />
            </div>
          ) : (
            <div key="stack" className="absolute inset-0">
              <FloorStack
                clinicians={clinicians}
                alerts={alerts}
                onSelectFloor={setSelectedFloor}
              />
            </div>
          )}
        </AnimatePresence>
      </div>

      {/* Legend */}
      <div
        className="flex flex-wrap items-center gap-4"
        style={{
          padding: "8px 14px",
          borderTop: "1px solid #E2E8F0",
          background: "#FFFFFF",
        }}
      >
        {STATUS_LEGEND.map((l) => (
          <div
            key={l.status}
            className="flex items-center gap-1.5"
            style={{ fontSize: 11, color: "#475569" }}
          >
            <span
              style={{
                width: 9,
                height: 9,
                borderRadius: "50%",
                background: STATUS_COLORS[l.status],
                display: "inline-block",
              }}
            />
            {l.label}
          </div>
        ))}
      </div>
    </div>
  );
}
