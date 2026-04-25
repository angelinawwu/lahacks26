"use client";

import type { ClinicianRecord } from "@/lib/types";
import {
  RoomShapes,
  resolveRoomKey,
  getRoom,
  ROOMS,
} from "./FloorMapRooms";

const STATUS_COLORS: Record<string, { fill: string; text: string }> = {
  paging:       { fill: "#378ADD", text: "#0C447C" },
  in_procedure: { fill: "#7F77DD", text: "#3C3489" },
  available:    { fill: "#1D9E75", text: "#085041" },
  on_case:      { fill: "#BA7517", text: "#633806" },
  off_shift:    { fill: "#9CA3AF", text: "#374151" },
};

const ZONE_TO_ROOM: Record<string, string> = {
  floor_3_corridor: "corridor",
  nurses_station: "nurses_station",
  icu: "icu_412",
  or_1: "or_1",
  or_2: "or_1",
  break_room: "break_room",
  supply: "supply",
  parking_garage: "supply",
};

interface PinPoint {
  cx: number;
  cy: number;
}

function pinFor(c: ClinicianRecord, idx: number): PinPoint {
  const roomKey = ZONE_TO_ROOM[c.zone] ?? "corridor";
  const room = getRoom(roomKey) ?? ROOMS[6];
  const offsets: PinPoint[] = [
    { cx: -22, cy: -10 },
    { cx: 22, cy: -10 },
    { cx: -22, cy: 10 },
    { cx: 22, cy: 10 },
  ];
  const off = offsets[idx % offsets.length];
  return { cx: room.cx + off.cx, cy: room.cy + off.cy };
}

function shortName(name: string): string {
  return name.replace(/^Dr\.?\s*/i, "").split(" ").slice(-1)[0] ?? name;
}

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

export function FloorMap({
  clinicians,
  activeAlertRoom,
  floorLabel = "Floor 3 — live",
  onPinClick,
}: {
  clinicians: ClinicianRecord[];
  activeAlertRoom?: string | null;
  floorLabel?: string;
  onPinClick?: (clinician: ClinicianRecord) => void;
}) {
  const alertRoom = getRoom(resolveRoomKey(activeAlertRoom));

  // place pins, grouping by room so we can offset siblings
  const grouped = new Map<string, ClinicianRecord[]>();
  for (const c of clinicians) {
    const key = ZONE_TO_ROOM[c.zone] ?? "corridor";
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)!.push(c);
  }

  return (
    <div
      className="relative h-full w-full overflow-hidden"
      style={{
        background: "var(--color-background-tertiary)",
        borderRight: HAIRLINE,
      }}
    >
      <span
        className="absolute"
        style={{
          top: 10,
          left: 12,
          fontSize: 11,
          color: "var(--color-text-secondary)",
          fontWeight: 500,
          background: "var(--color-background-primary)",
          padding: "3px 8px",
          borderRadius: 20,
          border: HAIRLINE,
          zIndex: 2,
        }}
      >
        {floorLabel}
      </span>

      <svg width="100%" height="100%" viewBox="0 0 380 420" preserveAspectRatio="xMidYMid meet">
        <RoomShapes />

        {alertRoom ? (
          <circle
            className="medpage-pulse"
            cx={alertRoom.cx + 5}
            cy={alertRoom.cy - 2}
            r={10}
            fill="#E24B4A"
          />
        ) : null}

        {Array.from(grouped.entries()).flatMap(([, members]) =>
          members.map((c, idx) => {
            const { cx, cy } = pinFor(c, idx);
            const tone = STATUS_COLORS[c.status] ?? STATUS_COLORS.available;
            return (
              <g
                key={c.id}
                style={{ cursor: onPinClick ? "pointer" : "default" }}
                onClick={() => onPinClick?.(c)}
              >
                <circle
                  cx={cx}
                  cy={cy}
                  r={7}
                  fill={tone.fill}
                  stroke="var(--color-background-primary)"
                  strokeWidth={1.5}
                />
                <text
                  x={cx + 10}
                  y={cy - 5}
                  style={{ fontSize: 10, fontWeight: 500, fill: tone.text }}
                >
                  {shortName(c.name)}
                </text>
              </g>
            );
          }),
        )}
      </svg>

      <div
        className="absolute bottom-0 left-0 right-0 flex flex-wrap gap-3"
        style={{
          padding: "8px 12px",
          borderTop: HAIRLINE,
          background: "var(--color-background-primary)",
        }}
      >
        {[
          ["Paging", "#378ADD"],
          ["In procedure", "#7F77DD"],
          ["Available", "#1D9E75"],
          ["On case", "#BA7517"],
        ].map(([label, color]) => (
          <div key={label} className="flex items-center gap-1.5" style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block" }} />
            {label}
          </div>
        ))}
      </div>
    </div>
  );
}
