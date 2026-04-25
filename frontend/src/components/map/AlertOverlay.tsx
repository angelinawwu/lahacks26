"use client";

import { motion } from "framer-motion";
import { PRIORITY_PULSE, type Rect } from "@/lib/floorData";

type Priority = "P1" | "P2" | "P3" | "P4";

export function AlertOverlay({
  rect,
  priority,
}: {
  rect: Rect;
  priority: Priority;
}) {
  const tone = PRIORITY_PULSE[priority] ?? PRIORITY_PULSE.P3;

  return (
    <g pointerEvents="none">
      <motion.rect
        x={rect.x}
        y={rect.y}
        width={rect.w}
        height={rect.h}
        fill={tone.color}
        initial={{ opacity: 0 }}
        animate={{ opacity: [tone.opacity * 0.4, tone.opacity, tone.opacity * 0.4] }}
        transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.rect
        x={rect.x}
        y={rect.y}
        width={rect.w}
        height={rect.h}
        fill="none"
        stroke={tone.color}
        strokeWidth={2}
        initial={{ opacity: 0 }}
        animate={{ opacity: [0.4, 0.9, 0.4] }}
        transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
      />
    </g>
  );
}
