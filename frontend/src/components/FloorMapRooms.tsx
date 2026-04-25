import type { ReactElement } from "react";

export interface RoomDef {
  key: string;
  label: string;
  x: number;
  y: number;
  w: number;
  h: number;
  cx: number;
  cy: number;
}

export const ROOMS: RoomDef[] = [
  { key: "icu_412",       label: "ICU 412",    x: 40,  y: 40,  w: 80,  h: 60, cx: 80,  cy: 70 },
  { key: "or_1",          label: "OR 1",       x: 140, y: 40,  w: 80,  h: 60, cx: 180, cy: 70 },
  { key: "rm_308",        label: "Rm 308",     x: 240, y: 40,  w: 80,  h: 60, cx: 280, cy: 70 },
  { key: "rm_310",        label: "Rm 310",     x: 40,  y: 140, w: 80,  h: 60, cx: 80,  cy: 170 },
  { key: "nurses_station",label: "Nurses stn", x: 140, y: 140, w: 80,  h: 60, cx: 180, cy: 170 },
  { key: "rm_314",        label: "Rm 314",     x: 240, y: 140, w: 80,  h: 60, cx: 280, cy: 170 },
  { key: "corridor",      label: "Corridor",   x: 40,  y: 240, w: 280, h: 60, cx: 180, cy: 270 },
  { key: "break_room",    label: "Break room", x: 40,  y: 340, w: 130, h: 50, cx: 105, cy: 367 },
  { key: "supply",        label: "Supply",     x: 190, y: 340, w: 130, h: 50, cx: 255, cy: 367 },
];

const ROOM_ALIASES: Record<string, string> = {
  "412": "icu_412",
  "icu": "icu_412",
  "icu_412": "icu_412",
  "rm_412": "icu_412",
  "room_412": "icu_412",
  "or": "or_1",
  "or_1": "or_1",
  "or_2": "or_1",
  "308": "rm_308",
  "rm_308": "rm_308",
  "room_308": "rm_308",
  "310": "rm_310",
  "rm_310": "rm_310",
  "room_310": "rm_310",
  "314": "rm_314",
  "rm_314": "rm_314",
  "room_314": "rm_314",
  "nurses_station": "nurses_station",
  "floor_3_corridor": "corridor",
  "corridor": "corridor",
  "break_room": "break_room",
  "supply": "supply",
};

export function resolveRoomKey(room?: string | null): string | null {
  if (!room) return null;
  const k = room.trim().toLowerCase().replace(/\s+/g, "_");
  if (ROOM_ALIASES[k]) return ROOM_ALIASES[k];
  for (const [alias, key] of Object.entries(ROOM_ALIASES)) {
    if (k.includes(alias)) return key;
  }
  return null;
}

export function getRoom(key: string | null): RoomDef | null {
  if (!key) return null;
  return ROOMS.find((r) => r.key === key) ?? null;
}

export function RoomShapes(): ReactElement {
  return (
    <g>
      <rect
        x={20}
        y={20}
        width={340}
        height={380}
        rx={6}
        fill="none"
        stroke="var(--color-border-secondary)"
        strokeWidth={0.5}
      />
      {ROOMS.map((r) => (
        <g key={r.key}>
          <rect
            x={r.x}
            y={r.y}
            width={r.w}
            height={r.h}
            rx={3}
            fill="var(--color-background-secondary)"
            stroke="var(--color-border-tertiary)"
            strokeWidth={0.5}
          />
          <text
            x={r.cx}
            y={r.cy + 2}
            textAnchor="middle"
            style={{ fontSize: 10, fill: "var(--color-text-tertiary)" }}
          >
            {r.label}
          </text>
        </g>
      ))}
    </g>
  );
}
