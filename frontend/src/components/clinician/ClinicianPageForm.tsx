"use client";

import { useState } from "react";
import { postDispatch } from "@/lib/api";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

const ROOMS = [
  "er",
  "icu",
  "nicu",
  "labor_delivery",
  "ortho_unit",
  "or_1",
  "or_2",
  "ward_3a",
  "ward_3b",
];

const SPECIALTIES = [
  "cardiology",
  "neurology",
  "orthopaedics",
  "obstetrics",
  "neonatology",
  "internal_medicine",
  "general_surgery",
];

interface Props {
  clinicianId: string;
}

export function ClinicianPageForm({ clinicianId }: Props) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [room, setRoom] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim() || submitting) return;
    setSubmitting(true);
    setResult(null);
    try {
      const res = await postDispatch({
        raw_text: text.trim(),
        room: room || undefined,
        specialty_hint: specialty || undefined,
      });
      const top = res.case?.candidates?.[0];
      setResult({
        ok: true,
        msg: top
          ? `Paged ${top.name} (${res.priority?.priority ?? "—"})`
          : `Dispatched (${res.priority?.priority ?? "—"})`,
      });
      setText("");
      setRoom("");
      setSpecialty("");
    } catch (err) {
      setResult({ ok: false, msg: err instanceof Error ? err.message : "Failed to send" });
    } finally {
      setSubmitting(false);
    }
  }

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
    background: "var(--color-background-primary)",
    color: "var(--color-text-primary)",
    fontSize: 13,
    outline: "none",
  };

  return (
    <div>
      <div
        style={{
          fontSize: 11,
          color: "var(--color-text-secondary)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          marginBottom: 6,
        }}
      >
        Send a page
      </div>
      <div
        style={{
          border: HAIRLINE,
          borderRadius: 12,
          background: "var(--color-background-primary)",
          overflow: "hidden",
        }}
      >
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          style={{
            width: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "12px 14px",
            fontSize: 13,
            background: "transparent",
            color: "var(--color-text-primary)",
            border: "none",
            cursor: "pointer",
            transition: "background 200ms ease",
          }}
        >
          <span style={{ fontWeight: 500 }}>
            {open ? "Cancel" : "New page request"}
          </span>
          <span style={{ fontSize: 16, color: "var(--color-text-tertiary)" }}>
            {open ? "−" : "+"}
          </span>
        </button>

        {open ? (
          <form onSubmit={submit} style={{ padding: 14, borderTop: HAIRLINE, display: "flex", flexDirection: "column", gap: 10 }}>
            <div>
              <label style={labelStyle} htmlFor="page-text">Describe the situation</label>
              <textarea
                id="page-text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="e.g. Chest pain in room 412, patient diaphoretic"
                rows={3}
                required
                style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
              />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div>
                <label style={labelStyle} htmlFor="page-room">Room</label>
                <select
                  id="page-room"
                  value={room}
                  onChange={(e) => setRoom(e.target.value)}
                  style={inputStyle}
                >
                  <option value="">—</option>
                  {ROOMS.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </div>
              <div>
                <label style={labelStyle} htmlFor="page-specialty">Specialty</label>
                <select
                  id="page-specialty"
                  value={specialty}
                  onChange={(e) => setSpecialty(e.target.value)}
                  style={inputStyle}
                >
                  <option value="">—</option>
                  {SPECIALTIES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
              {result ? (
                <span
                  style={{
                    fontSize: 11,
                    color: result.ok ? "var(--color-text-success)" : "var(--color-text-danger)",
                  }}
                >
                  {result.msg}
                </span>
              ) : (
                <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
                  From {clinicianId}
                </span>
              )}
              <button
                type="submit"
                disabled={submitting || !text.trim()}
                style={{
                  padding: "8px 14px",
                  border: HAIRLINE,
                  borderRadius: 8,
                  background: submitting ? "var(--color-background-tertiary)" : "var(--color-text-primary)",
                  color: submitting ? "var(--color-text-tertiary)" : "var(--color-background-primary)",
                  fontSize: 13,
                  fontWeight: 500,
                  cursor: submitting ? "default" : "pointer",
                  transition: "opacity 200ms ease",
                  opacity: !text.trim() ? 0.5 : 1,
                }}
              >
                {submitting ? "Sending…" : "Send page"}
              </button>
            </div>
          </form>
        ) : null}
      </div>
    </div>
  );
}
