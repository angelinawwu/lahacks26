"use client";

import { motion } from "framer-motion";
import {
  WING_RECTS,
  WING_COLORS,
  getFloor,
  pinPositionsInRect,
  type FloorId,
  type WingId,
  type Rect,
} from "@/lib/floorData";
import type { ActiveAlert, ClinicianPin as ClinicianPinT } from "@/lib/types";
import { ClinicianPin } from "./ClinicianPin";
import { AlertOverlay } from "./AlertOverlay";

// Flashing room component for selected alerts
function FlashingRoom({ rect }: { rect: Rect }) {
  return (
    <motion.rect
      x={rect.x - 2}
      y={rect.y - 2}
      width={rect.w + 4}
      height={rect.h + 4}
      fill="#FFFFFF"
      fillOpacity={0.6}
      stroke="#FFFFFF"
      strokeWidth={4}
      initial={{ opacity: 0 }}
      animate={{ 
        opacity: [0, 1, 0, 1, 0, 1, 0],
        scale: [1, 1.02, 1, 1.02, 1, 1.02, 1]
      }}
      transition={{ 
        duration: 2.4, 
        ease: "easeInOut"
      }}
      style={{ 
        transformOrigin: "center",
        filter: "drop-shadow(0 0 12px rgba(255, 255, 255, 0.8))"
      }}
    />
  );
}

export function FloorPlan({
  floor,
  clinicians,
  alerts,
  onClinicianClick,
  onBack,
  selectedAlert,
  onAlertSelect,
}: {
  floor: FloorId;
  clinicians: ClinicianPinT[];
  alerts: ActiveAlert[];
  onClinicianClick?: (id: string) => void;
  onBack: () => void;
  selectedAlert?: ActiveAlert | null;
  onAlertSelect?: (alert: ActiveAlert | null) => void;
}) {
  const def = getFloor(floor);
  const floorClinicians = clinicians.filter((c) => c.floor === floor);
  const floorAlerts = alerts.filter((a) => a.floor === floor);

  // Group clinicians by wing for even distribution.
  const byWing = new Map<WingId, ClinicianPinT[]>();
  for (const c of floorClinicians) {
    if (!byWing.has(c.wing)) byWing.set(c.wing, []);
    byWing.get(c.wing)!.push(c);
  }

  // Find rooms whose name (or wing fallback) matches each alert.
  const alertRects: { rect: Rect; priority: ActiveAlert["priority"]; key: string }[] = [];
  for (const a of floorAlerts) {
    const room = def.rooms.find(
      (r) =>
        r.name.toLowerCase().includes(a.zone.toLowerCase()) ||
        r.id.toLowerCase().includes(a.zone.toLowerCase()),
    );
    const rect = room?.rect ?? WING_RECTS[a.wing];
    alertRects.push({ rect, priority: a.priority, key: a.alert_id });
  }

  // Find the room for the selected alert to flash it
  const selectedRoom = selectedAlert ? def.rooms.find(
    (r) =>
      r.name.toLowerCase().includes(selectedAlert.zone.toLowerCase()) ||
      r.id.toLowerCase().includes(selectedAlert.zone.toLowerCase()),
  ) : null;

  return (
    <motion.svg
      viewBox="0 0 1000 700"
      width="100%"
      height="100%"
      preserveAspectRatio="xMidYMid meet"
    >
      {/* Wings */}
      {def.wings.map((wing) => {
        const r = WING_RECTS[wing];
        const c = WING_COLORS[wing];
        return (
          <g key={wing}>
            <rect
              x={r.x}
              y={r.y}
              width={r.w}
              height={r.h}
              fill={c.fill}
              stroke={c.stroke}
              strokeWidth={1.5}
            />
            <text
              x={r.x + 10}
              y={r.y + 18}
              style={{ fontSize: 12, fontWeight: 600, fill: "#334155" }}
            >
              {c.label}
            </text>
          </g>
        );
      })}

      {/* Rooms */}
      {def.rooms.map((room) => {
        // Keep the room label clear of the wing's own header label (which
        // sits at wing.y + 18). If this room hugs the top of its wing, push
        // its label down so the zone caption stays readable.
        const wingTop = WING_RECTS[room.wing].y;
        const minLabelY = wingTop + 32;
        const labelY = Math.max(room.rect.y + 14, minLabelY);
        return (
          <g key={room.id}>
            <rect
              x={room.rect.x}
              y={room.rect.y}
              width={room.rect.w}
              height={room.rect.h}
              fill="#FFFFFF"
              fillOpacity={0.55}
              stroke={WING_COLORS[room.wing].stroke}
              strokeOpacity={0.5}
              strokeWidth={1}
            />
            <text
              x={room.rect.x + 6}
              y={labelY}
              style={{ fontSize: 10, fill: "#1F2937", fontWeight: 500 }}
            >
              {room.name}
            </text>
          </g>
        );
      })}

      {/* Alert overlays */}
      {alertRects.map((a) => (
        <AlertOverlay key={a.key} rect={a.rect} priority={a.priority} />
      ))}

      {/* Flashing room for selected alert - render on top */}
      {selectedRoom && selectedAlert && selectedAlert.floor === floor && (
        <FlashingRoom rect={selectedRoom.rect} />
      )}

      {/* Clinician pins */}
      {Array.from(byWing.entries()).flatMap(([wing, members]) => {
        const positions = pinPositionsInRect(WING_RECTS[wing], members.length);
        return members.map((m, i) => (
          <ClinicianPin
            key={m.id}
            pin={m}
            cx={positions[i].cx}
            cy={positions[i].cy}
            onClick={onClinicianClick}
          />
        ));
      })}


    </motion.svg>
  );
}
