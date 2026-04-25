import type { CSSProperties } from "react";

type Tone = {
  bg: string;
  fg: string;
  border?: string;
};

const PRIORITY_TONES: Record<string, Tone> = {
  P1: { bg: "#E24B4A", fg: "#FCEBEB" },
  P2: { bg: "#EF9F27", fg: "#412402" },
  P3: { bg: "var(--color-background-info)", fg: "var(--color-text-info)" },
  P4: { bg: "var(--color-background-secondary)", fg: "var(--color-text-secondary)" },
};

const STATUS_TONES: Record<string, Tone> = {
  paging:     { bg: "#FAEEDA", fg: "#633806" },
  awaiting:   { bg: "#FAEEDA", fg: "#633806" },
  accepted:   { bg: "#EAF3DE", fg: "#27500A" },
  en_route:   { bg: "#EAF3DE", fg: "#27500A" },
  escalating: { bg: "#FBE3E2", fg: "#7A1F1D" },
  declined:   { bg: "#FBE3E2", fg: "#7A1F1D" },
  resolved:   { bg: "var(--color-background-secondary)", fg: "var(--color-text-secondary)" },
  queued:     { bg: "var(--color-background-secondary)", fg: "var(--color-text-secondary)" },
  available:  { bg: "var(--color-background-secondary)", fg: "var(--color-text-secondary)" },
};

const pillStyle = (tone: Tone): CSSProperties => ({
  background: tone.bg,
  color: tone.fg,
  fontSize: 10,
  fontWeight: 500,
  padding: "1px 7px",
  borderRadius: 20,
  display: "inline-block",
  lineHeight: 1.5,
  whiteSpace: "nowrap",
});

export function PriorityBadge({ priority }: { priority: string }) {
  const tone = PRIORITY_TONES[priority] ?? PRIORITY_TONES.P4;
  return <span style={pillStyle(tone)}>{priority}</span>;
}

const STATUS_LABELS: Record<string, string> = {
  paging: "Awaiting ACK",
  awaiting: "Awaiting ACK",
  accepted: "Accepted · En route",
  en_route: "En route",
  escalating: "Escalating",
  declined: "Declined",
  resolved: "Resolved",
  queued: "Queued",
  available: "Available",
};

export function StatusChip({
  status,
  label,
}: {
  status: string;
  label?: string;
}) {
  const tone = STATUS_TONES[status] ?? STATUS_TONES.queued;
  const text = label ?? STATUS_LABELS[status] ?? status;
  return (
    <span
      style={{
        ...pillStyle(tone),
        padding: "2px 7px",
      }}
    >
      {text}
    </span>
  );
}

export function CountBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span
      style={{
        background: "#E24B4A",
        color: "#FCEBEB",
        fontSize: 10,
        fontWeight: 500,
        padding: "1px 6px",
        borderRadius: 20,
        marginLeft: 5,
        lineHeight: 1.6,
      }}
    >
      {count}
    </span>
  );
}
