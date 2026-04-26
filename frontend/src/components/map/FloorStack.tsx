"use client";

import { motion } from "framer-motion";
import { useState } from "react";
import {
  FLOORS,
  WING_RECTS,
  WING_COLORS,
  STATUS_COLORS,
  PRIORITY_PULSE,
  type FloorId,
  type WingId,
  type Rect,
} from "@/lib/floorData";
import type { ActiveAlert, ClinicianPin } from "@/lib/types";

const EASE_OUT_QUART = [0.165, 0.84, 0.44, 1] as const;

// Simple utility to darken a hex color by ~15% for hover.
function darkenColor(hex: string): string {
  const num = parseInt(hex.replace("#", ""), 16);
  const r = Math.max(0, ((num >> 16) & 255) - 30);
  const g = Math.max(0, ((num >> 8) & 255) - 30);
  const b = Math.max(0, (num & 255) - 30);
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, "0")}`;
}

// Isometric projection (classic 2:1 dimetric).
const ISO_ANGLE_X = (Math.PI / 180) * 30;
const ISO_ANGLE_Y = (Math.PI / 180) * 30;
const SIN_X = Math.sin(ISO_ANGLE_X);
const COS_Y = Math.cos(ISO_ANGLE_Y);

// Floor plan dimensions in plane-space, before iso projection.
const PLANE_W = 380;
const PLANE_H = 160;
const LABEL_LEFT_X = 220;
const LABEL_W = 65;
// Vertical (z) gap between stacked floors.
const FLOOR_GAP = 60;
// Diagonal stagger per floor in screen-space (x shifts right as floors go up).
const STAGGER_X = 80;

const VIEW_W = 760;
const VIEW_H = 580;

// Project a (x,y,z) point to 2D using isometric matrix, centered in viewBox.
function project(x: number, y: number, z: number) {
  const px = (x - y) * COS_Y;
  const py = (x + y) * SIN_X - z;
  return { x: px + VIEW_W / 2, y: py + VIEW_H / 2 };
}

function topPriority(alerts: ActiveAlert[]): "P1" | "P2" | "P3" | "P4" | null {
  const order: ("P1" | "P2" | "P3" | "P4")[] = ["P1", "P2", "P3", "P4"];
  for (const p of order) if (alerts.some((a) => a.priority === p)) return p;
  return null;
}

// Compute parallelogram path for a floor plane at given z.
function planePath(z: number) {
  const half = PLANE_W / 2;
  const halfH = PLANE_H / 2;
  const a = project(-half, -halfH, z);
  const b = project(half, -halfH, z);
  const c = project(half, halfH, z);
  const d = project(-half, halfH, z);
  return `M ${a.x} ${a.y} L ${b.x} ${b.y} L ${c.x} ${c.y} L ${d.x} ${d.y} Z`;
}

// Map a wing rect from the 0..1000 / 0..700 viewBox into local plane coords.
function wingPlaneRect(wingId: WingId) {
  const r = WING_RECTS[wingId];
  const sx = PLANE_W / 1000;
  const sy = PLANE_H / 700;
  return {
    x: r.x * sx - PLANE_W / 2,
    y: r.y * sy - PLANE_H / 2,
    w: r.w * sx,
    h: r.h * sy,
  };
}

function wingPath(wingId: WingId, z: number) {
  const r = wingPlaneRect(wingId);
  const a = project(r.x, r.y, z);
  const b = project(r.x + r.w, r.y, z);
  const c = project(r.x + r.w, r.y + r.h, z);
  const d = project(r.x, r.y + r.h, z);
  return `M ${a.x} ${a.y} L ${b.x} ${b.y} L ${c.x} ${c.y} L ${d.x} ${d.y} Z`;
}

// Project an arbitrary rect from 0..1000/0..700 space onto a floor's iso plane.
function rectPath(rect: Rect, z: number) {
  const sx = PLANE_W / 1000;
  const sy = PLANE_H / 700;
  const lx = rect.x * sx - PLANE_W / 2;
  const ly = rect.y * sy - PLANE_H / 2;
  const lw = rect.w * sx;
  const lh = rect.h * sy;
  const a = project(lx, ly, z);
  const b = project(lx + lw, ly, z);
  const c = project(lx + lw, ly + lh, z);
  const d = project(lx, ly + lh, z);
  return `M ${a.x} ${a.y} L ${b.x} ${b.y} L ${c.x} ${c.y} L ${d.x} ${d.y} Z`;
}

export function FloorStack({
  clinicians,
  alerts,
  onSelectFloor,
}: {
  clinicians: ClinicianPin[];
  alerts: ActiveAlert[];
  onSelectFloor: (id: FloorId) => void;
}) {
  const [hovered, setHovered] = useState<FloorId | null>(null);
  const mid = (FLOORS.length - 1) / 2;

  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      width="100%"
      height="100%"
      preserveAspectRatio="xMidYMid meet"
      style={{ display: "block" }}
    >
      {FLOORS.map((f, i) => {
        const baseZ = (i - mid) * FLOOR_GAP;
        const fAlerts = alerts.filter((a) => a.floor === f.id);
        const fClinicians = clinicians.filter((c) => c.floor === f.id);
        const pulse = topPriority(fAlerts);
        const isHovered = hovered === f.id;
        const labelAnchor = project(-PLANE_W / 2 - 8, -PLANE_H / 2 + 80, baseZ);

        return (
          <motion.g
            key={f.id}
            onClick={() => onSelectFloor(f.id)}
            onHoverStart={() => setHovered(f.id)}
            onHoverEnd={() => setHovered(null)}
            initial={{ opacity: 0, x: (i - mid) * STAGGER_X - 8 }}
            animate={{ opacity: 1, x: (i - mid) * STAGGER_X }}
            transition={{
              duration: 0.25,
              delay: (FLOORS.length - i) * 0.05,
              ease: [0.165, 0.84, 0.44, 1],
            }}
            style={{ cursor: "pointer" }}
          >
            {/* Wing fills */}
            {f.wings.map((wing) => {
              const c = WING_COLORS[wing];
              return (
                <path
                  key={wing}
                  d={wingPath(wing, baseZ)}
                  fill={isHovered ? darkenColor(c.fill) : c.fill}
                  stroke={c.stroke}
                  strokeWidth={0.6}
                />
              );
            })}

            {/* Room subdivisions */}
            {f.rooms.map((room) => (
              <path
                key={room.id}
                d={rectPath(room.rect, baseZ)}
                fill="none"
                stroke={WING_COLORS[room.wing].stroke}
                strokeWidth={0.5}
                strokeOpacity={0.7}
              />
            ))}

            {/* Pulse outline if alerts on this floor — traced per wing */}
            {pulse
              ? f.wings.map((wing) => (
                  <motion.path
                    key={`pulse-${wing}`}
                    d={wingPath(wing, baseZ)}
                    fill="none"
                    stroke={PRIORITY_PULSE[pulse].color}
                    strokeWidth={2}
                    initial={{ opacity: 0.3 }}
                    animate={{ opacity: [0.3, 0.85, 0.3] }}
                    transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
                  />
                ))
              : null}

            {/* Clinician dots clustered per wing */}
            {f.wings.flatMap((wing) => {
              const members = fClinicians.filter((c) => c.wing === wing).slice(0, 6);
              const r = wingPlaneRect(wing);
              const cols = Math.max(1, Math.ceil(Math.sqrt(members.length)));
              const rows = Math.max(1, Math.ceil(members.length / cols));
              return members.map((m, idx) => {
                const col = idx % cols;
                const rw = Math.floor(idx / cols);
                const lx = r.x + ((col + 0.5) * r.w) / cols;
                const ly = r.y + ((rw + 0.5) * r.h) / rows;
                const p = project(lx, ly, baseZ);
                return (
                  <circle
                    key={m.id}
                    cx={p.x}
                    cy={p.y}
                    r={3}
                    fill={STATUS_COLORS[m.status] ?? STATUS_COLORS.available}
                    stroke="#FFFFFF"
                    strokeWidth={0.6}
                  />
                );
              });
            })}

            {/* Floor label — left of the floor, tightly wrapped */}
            <g>
              <rect
                x={LABEL_LEFT_X - LABEL_W}
                y={labelAnchor.y - 8}
                width={LABEL_W}
                height={20}
                rx={3}
                fill={isHovered ? "#F1F5F9" : "#FFFFFF"}
                stroke="#CBD5E1"
                strokeWidth={1}
              />
              <text
                x={LABEL_LEFT_X - LABEL_W / 2}
                y={labelAnchor.y + 3}
                dominantBaseline="middle"
                textAnchor="middle"
                style={{ fontSize: 11, fontWeight: 600, fill: "#0F172A" }}
              >
                {f.label.replace("Floor ", "FLOOR ")}
              </text>
            </g>
          </motion.g>
        );
      })}
    </svg>
  );
}

