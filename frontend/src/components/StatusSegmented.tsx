"use client";

import type { ClinicianStatus } from "@/lib/types";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

const OPTIONS: { value: ClinicianStatus; label: string }[] = [
  { value: "available", label: "Available" },
  { value: "in_procedure", label: "In Procedure" },
  { value: "off_shift", label: "Off Shift" },
];

export function StatusSegmented({
  value,
  onChange,
}: {
  value: ClinicianStatus;
  onChange: (next: ClinicianStatus) => void;
}) {
  return (
    <div
      className="grid w-full"
      style={{
        gridTemplateColumns: "1fr 1fr 1fr",
        background: "var(--color-background-secondary)",
        border: HAIRLINE,
        borderRadius: 10,
        padding: 3,
        gap: 3,
      }}
      role="radiogroup"
      aria-label="Clinician status"
    >
      {OPTIONS.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(opt.value)}
            style={{
              padding: "8px 0",
              fontSize: 12,
              fontWeight: 500,
              borderRadius: 8,
              border: "none",
              cursor: "pointer",
              background: active ? "var(--color-background-primary)" : "transparent",
              color: active ? "var(--color-text-primary)" : "var(--color-text-secondary)",
              boxShadow: active ? "0 0 0 0.5px var(--color-border-tertiary)" : "none",
              transition: "background 200ms ease, color 200ms ease",
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
