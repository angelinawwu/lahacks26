"use client";

import { QueueRow } from "./QueueRow";
import { cancelPage, escalatePage } from "@/lib/backendApi";
import type { QueuePage } from "@/lib/backendTypes";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

export function QueuePanel({
  pages,
  onUpdate,
}: {
  pages: QueuePage[];
  onUpdate?: (page: QueuePage) => void;
}) {
  async function handleEscalate(id: string) {
    try {
      const updated = await escalatePage(id);
      onUpdate?.(updated);
    } catch (e) {
      console.error("escalate failed", e);
    }
  }

  async function handleCancel(id: string) {
    try {
      const updated = await cancelPage(id);
      onUpdate?.(updated);
    } catch (e) {
      console.error("cancel failed", e);
    }
  }

  const counts = {
    P1: pages.filter((p) => p.priority === "P1").length,
    P2: pages.filter((p) => p.priority === "P2").length,
    P3: pages.filter((p) => p.priority === "P3").length,
    P4: pages.filter((p) => p.priority === "P4").length,
  };

  return (
    <div
      className="flex h-full flex-col overflow-hidden"
      style={{ background: "var(--color-background-primary)" }}
    >
      <div
        className="flex items-center justify-between"
        style={{
          padding: "10px 12px 8px",
          fontSize: 11,
          fontWeight: 500,
          color: "var(--color-text-secondary)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          borderBottom: HAIRLINE,
        }}
      >
        <span>Page queue</span>
        <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", fontWeight: 400 }}>
          {pages.length === 0
            ? "Empty"
            : `${pages.length} · P1 ${counts.P1} · P2 ${counts.P2}`}
        </span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {pages.length === 0 ? (
          <div
            className="px-3 py-8 text-center"
            style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}
          >
            Queue is empty.
          </div>
        ) : (
          pages.map((p) => (
            <QueueRow
              key={p.id}
              page={p}
              onEscalate={handleEscalate}
              onCancel={handleCancel}
            />
          ))
        )}
      </div>
    </div>
  );
}
