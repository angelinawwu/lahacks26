"use client";

import { useState } from "react";
import { manualPage } from "@/lib/backendApi";
import type { QueuePage } from "@/lib/backendTypes";
import type { ClinicianRecord } from "@/lib/types";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

const ROOMS = [
  "er", "icu", "nicu", "labor_delivery", "ortho_unit",
  "or_1", "or_2", "ward_3a", "ward_3b",
];

const PRIORITIES = ["P1", "P2", "P3", "P4"] as const;

const labelStyle: React.CSSProperties = {
  fontSize: 11,
  color: "var(--color-text-secondary)",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  marginBottom: 4,
  display: "block",
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "8px 10px",
  border: HAIRLINE,
  borderRadius: 8,
  background: "var(--color-background-secondary)",
  color: "var(--color-text-primary)",
  fontSize: 13,
  outline: "none",
};

interface Props {
  open: boolean;
  onClose: () => void;
  clinicians: ClinicianRecord[];
  onPageSent: (page: QueuePage) => void;
}

export function ManualOverridePanel({ open, onClose, clinicians, onPageSent }: Props) {
  const [doctorId, setDoctorId] = useState("");
  const [priority, setPriority] = useState<"P1" | "P2" | "P3" | "P4">("P2");
  const [room, setRoom] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  if (!open) return null;

  const available = clinicians.filter((c) => c.status !== "off_shift");
  const canSubmit = !!doctorId && !!message.trim() && !submitting;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setResult(null);
    try {
      const page = await manualPage({
        doctor_id: doctorId,
        message: message.trim(),
        priority,
        room: room || undefined,
      });
      const doc = clinicians.find((c) => c.id === doctorId);
      setResult({ ok: true, msg: `Paged ${doc?.name ?? doctorId}` });
      onPageSent(page);
      setDoctorId("");
      setMessage("");
      setRoom("");
      setPriority("P2");
    } catch (err) {
      setResult({ ok: false, msg: err instanceof Error ? err.message : "Failed to send" });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.25)",
          zIndex: 200,
        }}
      />
      <aside
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: 340,
          background: "var(--color-background-primary)",
          borderLeft: HAIRLINE,
          zIndex: 201,
          display: "flex",
          flexDirection: "column",
          boxShadow: "-2px 0 12px rgba(0,0,0,0.08)",
        }}
      >
        <div
          className="flex items-center justify-between"
          style={{
            padding: "14px 16px",
            borderBottom: HAIRLINE,
            flexShrink: 0,
          }}
        >
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>Manual override</div>
            <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 2 }}>
              Page a doctor directly — bypasses AI
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              fontSize: 18,
              lineHeight: 1,
              border: "none",
              background: "transparent",
              color: "var(--color-text-tertiary)",
              cursor: "pointer",
              padding: "2px 6px",
            }}
          >
            ×
          </button>
        </div>

        <form
          onSubmit={handleSubmit}
          style={{
            flex: 1,
            overflowY: "auto",
            padding: 16,
            display: "flex",
            flexDirection: "column",
            gap: 14,
          }}
        >
          <div>
            <label style={labelStyle} htmlFor="mo-doctor">Doctor</label>
            <select
              id="mo-doctor"
              value={doctorId}
              onChange={(e) => setDoctorId(e.target.value)}
              required
              style={inputStyle}
            >
              <option value="">— select doctor —</option>
              {available.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                  {c.on_call ? " · on call" : ""}
                  {" "}({c.status.replace(/_/g, " ")})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label style={labelStyle}>Priority</label>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(4, 1fr)",
                border: HAIRLINE,
                borderRadius: 8,
                overflow: "hidden",
              }}
            >
              {PRIORITIES.map((p) => {
                const active = priority === p;
                const colors: Record<string, string> = {
                  P1: "#C0392B",
                  P2: "#E0A100",
                  P3: "#3478F6",
                  P4: "#6B7280",
                };
                return (
                  <button
                    key={p}
                    type="button"
                    onClick={() => setPriority(p)}
                    style={{
                      padding: "8px 0",
                      fontSize: 12,
                      fontWeight: active ? 600 : 400,
                      border: "none",
                      background: active ? colors[p] : "transparent",
                      color: active ? "#fff" : colors[p],
                      cursor: "pointer",
                      transition: "background 150ms ease, color 150ms ease",
                    }}
                  >
                    {p}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <label style={labelStyle} htmlFor="mo-room">Room</label>
            <select
              id="mo-room"
              value={room}
              onChange={(e) => setRoom(e.target.value)}
              style={inputStyle}
            >
              <option value="">— optional —</option>
              {ROOMS.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>

          <div>
            <label style={labelStyle} htmlFor="mo-message">Situation / message</label>
            <textarea
              id="mo-message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Describe the situation for the clinician"
              rows={4}
              required
              style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
            />
          </div>

          {result ? (
            <div
              style={{
                fontSize: 12,
                padding: "8px 10px",
                borderRadius: 8,
                border: HAIRLINE,
                color: result.ok ? "var(--color-text-success, #1D9E75)" : "var(--color-text-danger)",
                background: result.ok ? "rgba(29,158,117,0.06)" : "rgba(224,75,74,0.06)",
              }}
            >
              {result.msg}
            </div>
          ) : null}

          <button
            type="submit"
            disabled={!canSubmit}
            style={{
              height: 44,
              borderRadius: 10,
              border: "none",
              background: canSubmit ? "var(--color-text-primary)" : "var(--color-background-secondary)",
              color: canSubmit ? "var(--color-background-primary)" : "var(--color-text-tertiary)",
              fontSize: 14,
              fontWeight: 600,
              cursor: canSubmit ? "pointer" : "default",
              transition: "background 150ms ease, color 150ms ease",
            }}
          >
            {submitting ? "Sending…" : "Send page"}
          </button>
        </form>
      </aside>
    </>
  );
}
