"use client";

import { useState } from "react";
import { approvePage, rejectPage } from "@/lib/backendApi";
import { PriorityBadge } from "@/components/badges";
import type { QueuePage } from "@/lib/backendTypes";
import type { ClinicianRecord } from "@/lib/types";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";
const AMBER = "#E0A100";
const AMBER_BG = "rgba(224,161,0,0.06)";

interface Props {
  page: QueuePage;
  clinicians: ClinicianRecord[];
  onApproved: (page: QueuePage) => void;
  onRejected: (pageId: string) => void;
}

export function PendingApprovalRow({ page, clinicians, onApproved, onRejected }: Props) {
  const [swapping, setSwapping] = useState(false);
  const [overrideId, setOverrideId] = useState<string>(page.doctor_id ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const aiDoctor = page.assigned_clinician_name ?? page.doctor?.name ?? page.doctor_id ?? "—";

  async function handleConfirm() {
    setBusy(true);
    setErr(null);
    try {
      const updated = await approvePage(page.id, swapping && overrideId !== page.doctor_id ? overrideId : undefined);
      onApproved(updated);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleReject() {
    setBusy(true);
    setErr(null);
    try {
      await rejectPage(page.id);
      onRejected(page.id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  const available = clinicians.filter((c) => c.status !== "off_shift");

  return (
    <div
      style={{
        background: AMBER_BG,
        border: `0.5px solid ${AMBER}`,
        borderRadius: 10,
        padding: "12px 14px",
        marginBottom: 8,
      }}
    >
      <div className="flex items-start justify-between" style={{ gap: 10, marginBottom: 8 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              fontSize: 10,
              fontWeight: 600,
              color: AMBER,
              textTransform: "uppercase",
              letterSpacing: "0.07em",
              marginBottom: 3,
            }}
          >
            Pending operator approval
          </div>
          <div
            style={{
              fontSize: 13,
              fontWeight: 500,
              color: "var(--color-text-primary)",
              lineHeight: 1.3,
              wordBreak: "break-word",
            }}
          >
            {page.title || page.message || page.id}
          </div>
          {page.room ? (
            <div style={{ fontSize: 11, color: "var(--color-text-secondary)", marginTop: 2 }}>
              {page.room}
            </div>
          ) : null}
        </div>
        <PriorityBadge priority={page.priority} />
      </div>

      {page.reasoning ? (
        <div
          style={{
            fontSize: 11,
            color: "var(--color-text-secondary)",
            background: "var(--color-background-secondary)",
            border: HAIRLINE,
            borderRadius: 6,
            padding: "6px 8px",
            marginBottom: 10,
            lineHeight: 1.4,
          }}
        >
          <span style={{ color: "var(--color-text-info)", fontWeight: 500, marginRight: 4 }}>AI:</span>
          {page.reasoning}
        </div>
      ) : null}

      <div style={{ marginBottom: 10 }}>
        <div
          style={{
            fontSize: 11,
            color: "var(--color-text-secondary)",
            marginBottom: 4,
          }}
        >
          AI selected:{" "}
          <strong style={{ color: "var(--color-text-primary)" }}>{aiDoctor}</strong>
          {page.specialty?.length ? (
            <span style={{ color: "var(--color-text-tertiary)" }}>
              {" "}· {page.specialty.join(", ")}
            </span>
          ) : null}
        </div>

        <button
          type="button"
          onClick={() => setSwapping((v) => !v)}
          style={{
            fontSize: 11,
            padding: "3px 8px",
            borderRadius: 6,
            border: HAIRLINE,
            background: swapping ? "var(--color-background-secondary)" : "transparent",
            color: "var(--color-text-secondary)",
            cursor: "pointer",
          }}
        >
          {swapping ? "Cancel swap" : "Swap doctor"}
        </button>

        {swapping ? (
          <select
            value={overrideId}
            onChange={(e) => setOverrideId(e.target.value)}
            style={{
              display: "block",
              width: "100%",
              marginTop: 6,
              padding: "6px 8px",
              fontSize: 12,
              border: HAIRLINE,
              borderRadius: 8,
              background: "var(--color-background-primary)",
              color: "var(--color-text-primary)",
            }}
          >
            <option value="">— select doctor —</option>
            {available.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.status.replace(/_/g, " ")}){c.on_call ? " · on call" : ""}
              </option>
            ))}
          </select>
        ) : null}
      </div>

      {err ? (
        <div style={{ fontSize: 11, color: "var(--color-text-danger)", marginBottom: 6 }}>
          {err}
        </div>
      ) : null}

      <div className="flex" style={{ gap: 6 }}>
        <button
          type="button"
          disabled={busy || (swapping && !overrideId)}
          onClick={handleConfirm}
          style={{
            flex: 1,
            height: 34,
            borderRadius: 8,
            border: `0.5px solid ${AMBER}`,
            background: busy ? "transparent" : AMBER,
            color: busy ? AMBER : "#fff",
            fontSize: 12,
            fontWeight: 600,
            cursor: busy ? "default" : "pointer",
            opacity: swapping && !overrideId ? 0.5 : 1,
            transition: "background 150ms ease",
          }}
        >
          {busy ? "…" : swapping && overrideId && overrideId !== page.doctor_id ? "Swap & send" : "Confirm"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={handleReject}
          style={{
            height: 34,
            padding: "0 14px",
            borderRadius: 8,
            border: "0.5px solid #E24B4A",
            background: "transparent",
            color: "#B23A38",
            fontSize: 12,
            fontWeight: 500,
            cursor: busy ? "default" : "pointer",
          }}
        >
          Reject
        </button>
      </div>
    </div>
  );
}
