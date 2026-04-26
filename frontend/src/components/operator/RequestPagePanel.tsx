"use client";

import { useEffect, useRef, useState } from "react";
import { createPageRequest, searchPatients } from "@/lib/backendApi";
import type { PageRequestRecord, PatientResult } from "@/lib/backendTypes";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";
const PRIORITIES = ["P1", "P2", "P3", "P4"] as const;
const PRIORITY_COLORS: Record<string, string> = {
  P1: "#C0392B", P2: "#E0A100", P3: "#3478F6", P4: "#6B7280",
};
const ROOMS = [
  "er", "icu", "nicu", "labor_delivery", "ortho_unit",
  "or_1", "or_2", "ward_3a", "ward_3b",
];
const DELAY_OPTIONS = [
  { label: "15 min", minutes: 15 },
  { label: "30 min", minutes: 30 },
  { label: "1 hr",  minutes: 60 },
  { label: "2 hr",  minutes: 120 },
];

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
  onRequestCreated: (record: PageRequestRecord) => void;
}

export function RequestPagePanel({ open, onClose, onRequestCreated }: Props) {
  // Patient toggle
  const [patientMode, setPatientMode] = useState<"search" | "manual">("search");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<PatientResult[]>([]);
  const [selectedPatient, setSelectedPatient] = useState<PatientResult | null>(null);
  const [searching, setSearching] = useState(false);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Manual patient fields
  const [patientName, setPatientName] = useState("");
  const [patientAge, setPatientAge] = useState("");
  const [chiefComplaint, setChiefComplaint] = useState("");
  const [vitals, setVitals] = useState("");

  // Common fields
  const [room, setRoom] = useState("");
  const [priority, setPriority] = useState<"P1" | "P2" | "P3" | "P4">("P2");
  const [situation, setSituation] = useState("");

  // Scheduling
  const [scheduled, setScheduled] = useState(false);
  const [delayMinutes, setDelayMinutes] = useState(30);
  const [customMinutes, setCustomMinutes] = useState("");

  // Submission
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  // Auto-fill situation when EHR patient selected
  useEffect(() => {
    if (selectedPatient && !situation) {
      const parts: string[] = [];
      if (selectedPatient.primary_diagnosis) parts.push(selectedPatient.primary_diagnosis);
      if (selectedPatient.comorbidities?.length) parts.push(`Comorbidities: ${selectedPatient.comorbidities.join(", ")}`);
      if (parts.length) setSituation(parts.join(". "));
    }
  }, [selectedPatient]);

  // Reset on close
  useEffect(() => {
    if (!open) {
      setSearchQuery(""); setSearchResults([]); setSelectedPatient(null);
      setPatientName(""); setPatientAge(""); setChiefComplaint(""); setVitals("");
      setRoom(""); setPriority("P2"); setSituation("");
      setScheduled(false); setDelayMinutes(30); setCustomMinutes("");
      setResult(null); setSubmitting(false); setPatientMode("search");
    }
  }, [open]);

  // Debounced patient search
  function handleSearchChange(v: string) {
    setSearchQuery(v);
    setSelectedPatient(null);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    if (!v.trim()) { setSearchResults([]); return; }
    searchTimer.current = setTimeout(async () => {
      setSearching(true);
      try {
        const results = await searchPatients(v);
        setSearchResults(results);
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
  }

  function selectPatient(p: PatientResult) {
    setSelectedPatient(p);
    setSearchQuery(p.name);
    setSearchResults([]);
    if (p.room && !room) setRoom(p.room);
  }

  const effectiveDelay = customMinutes ? parseInt(customMinutes) || 0 : delayMinutes;
  const canSubmit = !submitting && (
    patientMode === "search" ? !!selectedPatient || !!situation.trim() :
    !!(chiefComplaint.trim() || situation.trim())
  );

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setResult(null);

    let scheduledFor: string | null = null;
    if (scheduled) {
      const fireAt = new Date(Date.now() + effectiveDelay * 60 * 1000);
      scheduledFor = fireAt.toISOString();
    }

    try {
      const record = await createPageRequest({
        raw_text: situation.trim() || undefined,
        room: room || undefined,
        priority,
        patient_id: selectedPatient?.id,
        patient_name: patientMode === "manual" ? patientName || undefined : selectedPatient?.name,
        patient_age: patientMode === "manual" && patientAge ? parseInt(patientAge) : undefined,
        chief_complaint: patientMode === "manual" ? chiefComplaint || undefined : undefined,
        vitals: patientMode === "manual" ? vitals || undefined : undefined,
        scheduled_for: scheduledFor,
        requested_by: "operator",
      });
      const msg = scheduled
        ? `Scheduled in ${effectiveDelay} min`
        : "Dispatching now…";
      setResult({ ok: true, msg });
      onRequestCreated(record);
      setTimeout(onClose, 1200);
    } catch (err) {
      setResult({ ok: false, msg: err instanceof Error ? err.message : "Failed" });
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) return null;

  return (
    <>
      <div
        onClick={onClose}
        style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.25)", zIndex: 200 }}
      />
      <aside style={{
        position: "fixed", top: 0, right: 0, bottom: 0, width: 360,
        background: "var(--color-background-primary)",
        borderLeft: HAIRLINE, zIndex: 201, display: "flex", flexDirection: "column",
        boxShadow: "-2px 0 12px rgba(0,0,0,0.08)",
      }}>
        {/* Header */}
        <div style={{ padding: "14px 16px", borderBottom: HAIRLINE, flexShrink: 0 }}
          className="flex items-center justify-between">
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>Request a Page</div>
            <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 2 }}>
              Runs through AI dispatch with patient EHR context
            </div>
          </div>
          <button type="button" onClick={onClose} style={{
            fontSize: 18, lineHeight: 1, border: "none",
            background: "transparent", color: "var(--color-text-tertiary)", cursor: "pointer", padding: "2px 6px",
          }}>×</button>
        </div>

        <form onSubmit={handleSubmit} style={{
          flex: 1, overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 14,
        }}>
          {/* Patient toggle */}
          <div>
            <label style={labelStyle}>Patient</label>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", border: HAIRLINE, borderRadius: 8, overflow: "hidden", marginBottom: 8 }}>
              {(["search", "manual"] as const).map((m) => (
                <button key={m} type="button" onClick={() => setPatientMode(m)} style={{
                  padding: "7px 0", fontSize: 12, border: "none",
                  background: patientMode === m ? "var(--color-text-primary)" : "transparent",
                  color: patientMode === m ? "var(--color-background-primary)" : "var(--color-text-secondary)",
                  cursor: "pointer", fontWeight: patientMode === m ? 600 : 400,
                  transition: "background 150ms ease",
                }}>
                  {m === "search" ? "Search EHR" : "Enter manually"}
                </button>
              ))}
            </div>

            {patientMode === "search" ? (
              <div style={{ position: "relative" }}>
                <input
                  value={searchQuery}
                  onChange={(e) => handleSearchChange(e.target.value)}
                  placeholder="Name or patient ID…"
                  style={inputStyle}
                  autoComplete="off"
                />
                {searching && (
                  <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 4 }}>
                    Searching…
                  </div>
                )}
                {!searching && searchQuery.trim() && !selectedPatient && searchResults.length === 0 && (
                  <div style={{
                    fontSize: 11,
                    color: "var(--color-text-tertiary)",
                    marginTop: 4,
                    fontStyle: "italic",
                  }}>
                    Patient not found — switch to “Enter manually” to page without an EHR record.
                  </div>
                )}
                {searchResults.length > 0 && (
                  <div style={{
                    position: "absolute", top: "100%", left: 0, right: 0, zIndex: 10,
                    background: "var(--color-background-primary)",
                    border: HAIRLINE, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                    maxHeight: 200, overflowY: "auto", marginTop: 2,
                  }}>
                    {searchResults.map((p) => (
                      <button key={p.id} type="button" onClick={() => selectPatient(p)} style={{
                        display: "block", width: "100%", textAlign: "left",
                        padding: "8px 10px", border: "none", background: "transparent",
                        borderBottom: HAIRLINE, cursor: "pointer",
                      }}
                        onMouseEnter={(e) => { e.currentTarget.style.background = "var(--color-background-secondary)"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                      >
                        <div style={{ fontSize: 13, fontWeight: 500 }}>{p.name}</div>
                        <div style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
                          {[p.room && `Room ${p.room}`, p.primary_diagnosis].filter(Boolean).join(" · ")}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
                {selectedPatient && (
                  <div style={{
                    marginTop: 6, padding: "6px 8px", borderRadius: 6,
                    background: "var(--color-background-secondary)", border: HAIRLINE, fontSize: 12,
                  }}>
                    <strong>{selectedPatient.name}</strong>
                    {selectedPatient.primary_diagnosis && (
                      <span style={{ color: "var(--color-text-secondary)", marginLeft: 6 }}>
                        {selectedPatient.primary_diagnosis}
                      </span>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <input value={patientName} onChange={(e) => setPatientName(e.target.value)}
                  placeholder="Name (optional)" style={inputStyle} />
                <input value={patientAge} onChange={(e) => setPatientAge(e.target.value)}
                  placeholder="Age (optional)" type="number" min={0} max={150} style={inputStyle} />
                <input value={chiefComplaint} onChange={(e) => setChiefComplaint(e.target.value)}
                  placeholder="Chief complaint *" style={inputStyle} />
                <input value={vitals} onChange={(e) => setVitals(e.target.value)}
                  placeholder="Vitals (optional)" style={inputStyle} />
              </div>
            )}
          </div>

          {/* Room */}
          <div>
            <label style={labelStyle} htmlFor="rp-room">Room</label>
            <select id="rp-room" value={room} onChange={(e) => setRoom(e.target.value)} style={inputStyle}>
              <option value="">— optional —</option>
              {ROOMS.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>

          {/* Priority */}
          <div>
            <label style={labelStyle}>Priority</label>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", border: HAIRLINE, borderRadius: 8, overflow: "hidden" }}>
              {PRIORITIES.map((p) => (
                <button key={p} type="button" onClick={() => setPriority(p)} style={{
                  padding: "8px 0", fontSize: 12, fontWeight: priority === p ? 600 : 400,
                  border: "none",
                  background: priority === p ? PRIORITY_COLORS[p] : "transparent",
                  color: priority === p ? "#fff" : PRIORITY_COLORS[p],
                  cursor: "pointer", transition: "background 150ms ease, color 150ms ease",
                }}>{p}</button>
              ))}
            </div>
          </div>

          {/* Situation */}
          <div>
            <label style={labelStyle} htmlFor="rp-situation">Situation</label>
            <textarea id="rp-situation" value={situation} onChange={(e) => setSituation(e.target.value)}
              placeholder="Describe the situation (auto-filled from EHR if available)"
              rows={3} style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }} />
          </div>

          {/* Schedule toggle */}
          <div>
            <div className="flex items-center" style={{ gap: 8, marginBottom: scheduled ? 10 : 0 }}>
              <label style={{ ...labelStyle, marginBottom: 0, cursor: "pointer" }}>
                <input type="checkbox" checked={scheduled} onChange={(e) => setScheduled(e.target.checked)}
                  style={{ marginRight: 6 }} />
                Schedule for later
              </label>
            </div>
            {scheduled && (
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {DELAY_OPTIONS.map((d) => (
                  <button key={d.label} type="button" onClick={() => { setDelayMinutes(d.minutes); setCustomMinutes(""); }}
                    style={{
                      padding: "5px 10px", borderRadius: 20, fontSize: 12, cursor: "pointer",
                      border: HAIRLINE,
                      background: delayMinutes === d.minutes && !customMinutes ? "var(--color-text-primary)" : "transparent",
                      color: delayMinutes === d.minutes && !customMinutes ? "var(--color-background-primary)" : "var(--color-text-secondary)",
                      transition: "background 150ms ease",
                    }}>
                    {d.label}
                  </button>
                ))}
                <input
                  value={customMinutes}
                  onChange={(e) => setCustomMinutes(e.target.value)}
                  placeholder="custom min"
                  type="number" min={1} max={1440}
                  style={{ ...inputStyle, width: 90, padding: "5px 8px", borderRadius: 20 }}
                />
              </div>
            )}
          </div>

          {result && (
            <div style={{
              fontSize: 12, padding: "8px 10px", borderRadius: 8, border: HAIRLINE,
              color: result.ok ? "var(--color-text-success, #1D9E75)" : "var(--color-text-danger)",
              background: result.ok ? "rgba(29,158,117,0.06)" : "rgba(224,75,74,0.06)",
            }}>
              {result.msg}
            </div>
          )}

          <button type="submit" disabled={!canSubmit} style={{
            height: 44, borderRadius: 10, border: "none",
            background: canSubmit ? "var(--color-text-primary)" : "var(--color-background-secondary)",
            color: canSubmit ? "var(--color-background-primary)" : "var(--color-text-tertiary)",
            fontSize: 14, fontWeight: 600,
            cursor: canSubmit ? "pointer" : "default",
            transition: "background 150ms ease, color 150ms ease",
          }}>
            {submitting ? "Sending…" : scheduled ? `Schedule in ${effectiveDelay} min` : "Dispatch now"}
          </button>
        </form>
      </aside>
    </>
  );
}
