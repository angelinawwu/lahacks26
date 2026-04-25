"use client";

import { motion } from "framer-motion";
import {
  FLOORS,
  WING_RECTS,
  WING_COLORS,
  STATUS_COLORS,
  PRIORITY_PULSE,
  type FloorId,
  type WingId,
} from "@/lib/floorData";
import type { ActiveAlert, ClinicianPin } from "@/lib/types";

const EASE_OUT_QUART = [0.165, 0.84, 0.44, 1] as const;

// Compress 0..1000 wing coords into the card's drawing area.
const CARD_W = 540;
const CARD_H = 160;
const SCALE_X = CARD_W / 1000;
const SCALE_Y = (CARD_H - 16) / 700;

function topPriority(alerts: ActiveAlert[]): "P1" | "P2" | "P3" | "P4" | null {
  const order: ("P1" | "P2" | "P3" | "P4")[] = ["P1", "P2", "P3", "P4"];
  for (const p of order) if (alerts.some((a) => a.priority === p)) return p;
  return null;
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
  // Render top to bottom: floor 6 first, A last.
  const ordered = [...FLOORS].reverse();

  return (
    <div
      className="flex h-full w-full items-center justify-center"
      style={{ perspective: 1200 }}
    >
      <div
        style={{
          transform: "rotateX(52deg) rotateZ(-30deg)",
          transformStyle: "preserve-3d",
        }}
      >
        {ordered.map((f, i) => {
          const fAlerts = alerts.filter((a) => a.floor === f.id);
          const fClinicians = clinicians.filter((c) => c.floor === f.id);
          const pulse = topPriority(fAlerts);
          return (
            <motion.div
              key={f.id}
              onClick={() => onSelectFloor(f.id)}
              whileHover={{ filter: "brightness(1.08)", y: -4 }}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: i * 0.04, ease: EASE_OUT_QUART }}
              style={{
                position: "relative",
                width: CARD_W,
                height: CARD_H,
                marginTop: i === 0 ? 0 : -CARD_H + 28,
                cursor: "pointer",
                transformStyle: "preserve-3d",
              }}
            >
              {/* Floor label badge */}
              <div
                style={{
                  position: "absolute",
                  left: -78,
                  top: 14,
                  fontSize: 12,
                  fontWeight: 600,
                  color: "#0F172A",
                  background: "#FFFFFF",
                  border: "1px solid #CBD5E1",
                  borderRadius: 6,
                  padding: "4px 10px",
                  transform: "rotateZ(30deg) rotateX(-52deg)",
                }}
              >
                {f.label}
              </div>

              <svg
                viewBox={`0 0 ${CARD_W} ${CARD_H}`}
                width={CARD_W}
                height={CARD_H}
                style={{ display: "block" }}
              >
                {/* Card background */}
                <rect
                  x={0}
                  y={0}
                  width={CARD_W}
                  height={CARD_H}
                  fill="#F8FAFC"
                  stroke="#CBD5E1"
                  strokeWidth={1}
                  rx={6}
                />

                {/* Wing footprints */}
                {f.wings.map((wing: WingId) => {
                  const r = WING_RECTS[wing];
                  const c = WING_COLORS[wing];
                  return (
                    <rect
                      key={wing}
                      x={r.x * SCALE_X}
                      y={r.y * SCALE_Y + 8}
                      width={r.w * SCALE_X}
                      height={r.h * SCALE_Y}
                      fill={c.fill}
                      stroke={c.stroke}
                      strokeWidth={0.8}
                    />
                  );
                })}

                {/* Pulse overlay if alerts on this floor */}
                {pulse ? (
                  <motion.rect
                    x={2}
                    y={2}
                    width={CARD_W - 4}
                    height={CARD_H - 4}
                    rx={6}
                    fill="none"
                    stroke={PRIORITY_PULSE[pulse].color}
                    strokeWidth={2}
                    initial={{ opacity: 0.3 }}
                    animate={{ opacity: [0.3, 0.85, 0.3] }}
                    transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
                  />
                ) : null}

                {/* Clinician dots clustered per wing */}
                {f.wings.flatMap((wing) => {
                  const members = fClinicians.filter((c) => c.wing === wing).slice(0, 6);
                  const r = WING_RECTS[wing];
                  return members.map((m, idx) => {
                    const cols = Math.ceil(Math.sqrt(members.length));
                    const rows = Math.ceil(members.length / cols);
                    const col = idx % cols;
                    const rw = Math.floor(idx / cols);
                    const cx =
                      (r.x + ((col + 0.5) * r.w) / cols) * SCALE_X;
                    const cy =
                      (r.y + ((rw + 0.5) * r.h) / rows) * SCALE_Y + 8;
                    return (
                      <circle
                        key={m.id}
                        cx={cx}
                        cy={cy}
                        r={3}
                        fill={STATUS_COLORS[m.status] ?? STATUS_COLORS.available}
                        stroke="#FFFFFF"
                        strokeWidth={0.6}
                      />
                    );
                  });
                })}
              </svg>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
