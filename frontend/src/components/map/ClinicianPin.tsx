"use client";

import { motion, useReducedMotion } from "framer-motion";
import { useState } from "react";
import { STATUS_COLORS } from "@/lib/floorData";
import type { ClinicianPin as ClinicianPinT } from "@/lib/types";

const EASE_OUT_QUART = [0.165, 0.84, 0.44, 1] as const;

export function ClinicianPin({
  pin,
  cx,
  cy,
  onClick,
}: {
  pin: ClinicianPinT;
  cx: number;
  cy: number;
  onClick?: (id: string) => void;
}) {
  const reduced = useReducedMotion();
  const [hover, setHover] = useState(false);
  const fill = STATUS_COLORS[pin.status] ?? STATUS_COLORS.available;
  const showRipple = pin.status === "paging" && !reduced;

  return (
    <motion.g
      style={{ cursor: onClick ? "pointer" : "default" }}
      onClick={() => onClick?.(pin.id)}
      onHoverStart={() => setHover(true)}
      onHoverEnd={() => setHover(false)}
      initial={{ opacity: 0, scale: 0.6 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.25, ease: EASE_OUT_QUART }}
    >
      {showRipple ? (
        <motion.circle
          cx={cx}
          cy={cy}
          r={8}
          fill="none"
          stroke={fill}
          strokeWidth={2}
          initial={{ scale: 1, opacity: 0.6 }}
          animate={{ scale: 2.4, opacity: 0 }}
          transition={{ duration: 1.4, repeat: Infinity, ease: "easeOut" }}
          style={{ transformOrigin: `${cx}px ${cy}px` }}
        />
      ) : null}
      <circle
        cx={cx}
        cy={cy}
        r={8}
        fill={fill}
        stroke="#FFFFFF"
        strokeWidth={1.5}
      />
      {hover ? (
        <g pointerEvents="none">
          <rect
            x={cx + 12}
            y={cy - 28}
            width={Math.max(120, pin.name.length * 6.4)}
            height={36}
            rx={4}
            fill="#0F172A"
            opacity={0.92}
          />
          <text
            x={cx + 18}
            y={cy - 14}
            fill="#F8FAFC"
            style={{ fontSize: 10, fontWeight: 500 }}
          >
            {pin.name}
          </text>
          <text
            x={cx + 18}
            y={cy - 2}
            fill="#94A3B8"
            style={{ fontSize: 9 }}
          >
            {pin.status} · {pin.zone}
          </text>
        </g>
      ) : null}
    </motion.g>
  );
}
