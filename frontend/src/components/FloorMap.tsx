"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { FLOOR_IDS, STATUS_COLORS, type FloorId } from "@/lib/floorData";
import type { ActiveAlert, ClinicianPin } from "@/lib/types";
import { FloorStack } from "./map/FloorStack";
import { FloorPlan } from "./map/FloorPlan";

// Stack geometry constants — must mirror values in FloorStack.tsx so the
// FloorPlan can tilt in from the exact parallelogram position of the selected
// floor in the isometric stack.
const STACK_VIEW_W = 760;
const STACK_VIEW_H = 600;
const STACK_STAGGER_X = 80;
const STACK_FLOOR_GAP = 60;
const STACK_PLANE_W = 380;
// Rotations that approximate the 2:1 dimetric projection used by FloorStack.
// rotateX(54.7deg) + rotateZ(45deg) yields the same parallelogram shape as the
// projection matrix `[[cos30,-cos30],[sin30,sin30]]` modulo a uniform scale.
const TILT_ROTATE_X = 54.7;
const TILT_ROTATE_Z = 45;
const TILT_EASE = [0.165, 0.84, 0.44, 1] as const;

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

  // Keyboard shortcuts: 0 → Floor A, 1–6 → Floors 1–6, Space → all floors.
  // Ignored while the user is typing into an input/textarea/contenteditable.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.tagName === "SELECT" ||
          t.isContentEditable)
      ) {
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      if (e.code === "Space" || e.key === " ") {
        e.preventDefault();
        handleFloorSelect(null);
        return;
      }
      if (e.key === "0") {
        e.preventDefault();
        handleFloorSelect("A");
        return;
      }
      if (/^[1-6]$/.test(e.key)) {
        e.preventDefault();
        handleFloorSelect(e.key as FloorId);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handleFloorSelect]);

  // Track the most recently selected floor so the exit animation can tilt
  // the FloorPlan back to the correct parallelogram slot in the stack even
  // after `currentFloor` has been cleared.
  const lastFloorRef = useRef<FloorId | null>(currentFloor ?? null);
  useEffect(() => {
    if (currentFloor) lastFloorRef.current = currentFloor;
  }, [currentFloor]);

  // Compute the per-floor tilt origin: where the selected floor's
  // parallelogram sits inside the stack's viewBox, expressed as a percentage
  // offset from the container center. This drives the start/end position of
  // the 3D tilt animation so the FloorPlan unfolds from exactly where the
  // user clicked.
  const tiltFloor: FloorId | null = currentFloor ?? lastFloorRef.current;
  const floorIdx = tiltFloor ? FLOOR_IDS.indexOf(tiltFloor) : -1;
  const mid = (FLOOR_IDS.length - 1) / 2;
  const offsetUnits = floorIdx >= 0 ? floorIdx - mid : 0;
  const tiltDxPct = (offsetUnits * STACK_STAGGER_X) / STACK_VIEW_W * 100;
  const tiltDyPct = -(offsetUnits * STACK_FLOOR_GAP) / STACK_VIEW_H * 100;
  const tiltScale = STACK_PLANE_W / 1000; // 2D plan viewBox is 1000 wide.

  const tiltedState = {
    x: `${tiltDxPct}%`,
    y: `${tiltDyPct}%`,
    scale: tiltScale,
    rotateX: TILT_ROTATE_X,
    rotateZ: TILT_ROTATE_Z,
    opacity: 0,
  };
  const flatState = {
    x: "0%",
    y: "0%",
    scale: 1,
    rotateX: 0,
    rotateZ: 0,
    opacity: 1,
  };

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
        <span style={{ fontSize: 11, color: "#64748B", marginRight: 4, fontFamily: "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace", fontWeight: 300, textTransform: "uppercase", letterSpacing: "0.08em" }}>Floor</span>
        <button
          type="button"
          onClick={() => handleFloorSelect(null)}
          style={{
            fontSize: 12,
            fontWeight: 300,
            padding: "4px 12px",
            borderRadius: 999,
            border: "1px solid #CBD5E1",
            background: !currentFloor ? "#0F172A" : "transparent",
            color: !currentFloor ? "#F8FAFC" : "#0F172A",
            cursor: "pointer",
            transition: "background 200ms ease, color 200ms ease",
            fontFamily: "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
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
                fontWeight: 300,
                padding: "4px 12px",
                borderRadius: 999,
                border: "1px solid #CBD5E1",
                background: active ? "#0F172A" : "transparent",
                color: active ? "#F8FAFC" : "#0F172A",
                cursor: "pointer",
                transition: "background 200ms ease, color 200ms ease",
                fontFamily: "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
              }}
            >
              {id}
            </button>
          );
        })}
      </div>

      {/* Map area */}
      <div
        className="relative flex-1 overflow-hidden"
        style={{ perspective: 1600, perspectiveOrigin: "50% 50%" }}
      >
        {/* Stack: stays mounted; fades out (without tilting itself) while the
            FloorPlan tilts in from the selected floor's parallelogram. */}
        <motion.div
          className="absolute inset-0"
          animate={{ opacity: currentFloor ? 0 : 1 }}
          transition={{
            duration: currentFloor ? 0.18 : 0.3,
            delay: currentFloor ? 0 : 0.18,
            ease: TILT_EASE,
          }}
          style={{ pointerEvents: currentFloor ? "none" : "auto" }}
        >
          <FloorStack
            clinicians={clinicians}
            alerts={alerts}
            onSelectFloor={handleFloorSelect}
          />
        </motion.div>

        {/* All-floors button — fixed bottom-right overlay, only when a floor
            is selected. */}
        <AnimatePresence>
          {currentFloor ? (
            <motion.button
              key="all-floors-btn"
              type="button"
              onClick={() => handleFloorSelect(null)}
              className="absolute z-10"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 6 }}
              transition={{ duration: 0.2, delay: 0.26, ease: TILT_EASE }}
              style={{
                right: 16,
                bottom: 16,
                fontSize: 12,
                fontWeight: 300,
                padding: "6px 12px",
                borderRadius: 999,
                border: "1px solid #CBD5E1",
                background: "#FFFFFF",
                color: "#0F172A",
                cursor: "pointer",
                boxShadow: "0 1px 2px rgba(15, 23, 42, 0.06)",
                transition: "background 200ms ease, color 200ms ease",
                fontFamily: "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
              }}
            >
              ← All floors
            </motion.button>
          ) : null}
        </AnimatePresence>

        {/* Floor navigation arrows — fixed overlay, not part of the tilt. */}
        <AnimatePresence>
          {currentFloor ? (() => {
            const idx = FLOOR_IDS.indexOf(currentFloor);
            const prev = idx > 0 ? FLOOR_IDS[idx - 1] : null;
            const next = idx >= 0 && idx < FLOOR_IDS.length - 1 ? FLOOR_IDS[idx + 1] : null;
            return (
              <motion.div
                key="floor-nav"
                className="pointer-events-none absolute inset-x-0 bottom-4 z-10 flex items-center justify-center gap-4"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 6 }}
                transition={{ duration: 0.2, delay: 0.26, ease: TILT_EASE }}
              >
                <button
                  type="button"
                  disabled={!prev}
                  onClick={() => prev && handleFloorSelect(prev)}
                  className="pointer-events-auto"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    fontSize: 12,
                    fontWeight: 300,
                    padding: "6px 12px",
                    borderRadius: 999,
                    border: "1px solid #CBD5E1",
                    background: "#FFFFFF",
                    color: prev ? "#0F172A" : "#94A3B8",
                    cursor: prev ? "pointer" : "not-allowed",
                    boxShadow: "0 1px 2px rgba(15, 23, 42, 0.06)",
                    transition: "background 200ms ease, color 200ms ease",
                    fontFamily: "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace",
                    textTransform: "uppercase",
                    letterSpacing: "0.08em",
                  }}
                >
                  <span aria-hidden style={{ fontSize: 14, lineHeight: 1 }}>↓</span>
                  <span style={{ fontSize: 10, color: "#64748B" }}>Floor</span>
                  <span>{prev ?? "—"}</span>
                </button>
                <span
                  className="pointer-events-none"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 4,
                    fontSize: 13,
                    fontWeight: 300,
                    color: "#0F172A",
                    padding: "0 6px",
                    fontFamily: "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace",
                    textTransform: "uppercase",
                    letterSpacing: "0.08em",
                  }}
                >
                  Floor {currentFloor}
                </span>
                <button
                  type="button"
                  disabled={!next}
                  onClick={() => next && handleFloorSelect(next)}
                  className="pointer-events-auto"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    fontSize: 12,
                    fontWeight: 300,
                    padding: "6px 12px",
                    borderRadius: 999,
                    border: "1px solid #CBD5E1",
                    background: "#FFFFFF",
                    color: next ? "#0F172A" : "#94A3B8",
                    cursor: next ? "pointer" : "not-allowed",
                    boxShadow: "0 1px 2px rgba(15, 23, 42, 0.06)",
                    transition: "background 200ms ease, color 200ms ease",
                    fontFamily: "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace",
                    textTransform: "uppercase",
                    letterSpacing: "0.08em",
                  }}
                >
                  <span style={{ fontSize: 10, color: "#64748B" }}>Floor</span>
                  <span>{next ?? "—"}</span>
                  <span aria-hidden style={{ fontSize: 14, lineHeight: 1 }}>↑</span>
                </button>
              </motion.div>
            );
          })() : null}
        </AnimatePresence>

        <AnimatePresence>
          {currentFloor ? (
            <motion.div
              key="plan-tilt"
              className="absolute inset-0"
              style={{
                transformStyle: "preserve-3d",
                transformOrigin: "50% 50%",
                willChange: "transform, opacity",
              }}
              initial={tiltedState}
              animate={flatState}
              exit={tiltedState}
              transition={{
                duration: 0.5,
                ease: TILT_EASE,
                opacity: { duration: 0.25, ease: TILT_EASE },
              }}
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
          ) : null}
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
