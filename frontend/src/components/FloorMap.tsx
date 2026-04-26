"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
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
  selectedFloor?: FloorId | null;
  onFloorSelect?: (floor: FloorId | null) => void;
  onClinicianClick?: (id: string) => void;
  selectedAlert?: ActiveAlert | null;
  onAlertSelect?: (alert: ActiveAlert | null) => void;
};

export function FloorMap({ clinicians, alerts, selectedFloor, onFloorSelect, onClinicianClick, selectedAlert, onAlertSelect }: FloorMapProps) {
  const [internalSelectedFloor, setInternalSelectedFloor] = useState<FloorId | null>(null);
  const [internalSelectedAlert, setInternalSelectedAlert] = useState<ActiveAlert | null>(null);
  
  // Use external state if provided, otherwise use internal state
  const currentFloor = selectedFloor !== undefined ? selectedFloor : internalSelectedFloor;
  const handleFloorSelect = onFloorSelect || setInternalSelectedFloor;
  const currentAlert = selectedAlert !== undefined ? selectedAlert : internalSelectedAlert;
  const handleAlertSelect = onAlertSelect || setInternalSelectedAlert;

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
        <button
          type="button"
          onClick={() => handleFloorSelect(null)}
          style={{
            fontSize: 12,
            fontWeight: 500,
            padding: "4px 12px",
            borderRadius: 999,
            border: "1px solid #CBD5E1",
            background: !currentFloor ? "#0F172A" : "transparent",
            color: !currentFloor ? "#F8FAFC" : "#0F172A",
            cursor: "pointer",
            transition: "background 200ms ease, color 200ms ease",
          }}
        >
          All
        </button>
        {FLOOR_IDS.map((id) => {
          const active = currentFloor === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => handleFloorSelect(id)}
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
        {currentFloor ? (
          <button
            type="button"
            onClick={() => handleFloorSelect(null)}
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
          {currentFloor ? (
            <motion.div
              key={`plan-${currentFloor}`}
              className="absolute inset-0"
              initial={{ opacity: 0, y: 0 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 0 }}
              transition={{ duration: 0.02, ease: [0.165, 0.84, 0.44, 1] }}
            >
              <FloorPlan
                floor={currentFloor}
                clinicians={clinicians}
                alerts={alerts}
                onClinicianClick={onClinicianClick}
                onBack={() => handleFloorSelect(null)}
                selectedAlert={currentAlert}
                onAlertSelect={handleAlertSelect}
              />
            </motion.div>
          ) : (
            <motion.div
              key="stack"
              className="absolute inset-0"
              initial={{ opacity: 0, y: 0 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 0 }}
              transition={{ duration: 0.02, ease: [0.165, 0.84, 0.44, 1] }}
            >
              <FloorStack
                clinicians={clinicians}
                alerts={alerts}
                onSelectFloor={handleFloorSelect}
              />
            </motion.div>
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
