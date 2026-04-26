"use client";

import { useEffect, useRef, useState } from "react";
import { postDispatch } from "@/lib/api";

// Minimal typings for the Web Speech API (not in lib.dom yet in all TS versions)
interface SpeechRecognitionResultLike {
  0: { transcript: string };
  isFinal: boolean;
}
interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onerror: ((e: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function getSpeechRecognition(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

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
  const [patientId, setPatientId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const [voiceSupported, setVoiceSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const recogRef = useRef<SpeechRecognitionLike | null>(null);
  const baseTextRef = useRef<string>("");
  const autoSendRef = useRef<boolean>(false);
  const finalTranscriptRef = useRef<string>("");

  useEffect(() => {
    setVoiceSupported(getSpeechRecognition() !== null);
    return () => {
      try {
        recogRef.current?.abort();
      } catch {
        /* noop */
      }
    };
  }, []);

  async function dispatchText(raw: string) {
    if (submitting) return;
    const trimmed = raw.trim();
    // Allow submit if at least one field is provided.
    if (!trimmed && !room && !specialty && !patientId.trim()) return;
    setSubmitting(true);
    setResult(null);
    try {
      const res = await postDispatch({
        raw_text: trimmed || undefined,
        room: room || undefined,
        specialty_hint: specialty || undefined,
        patient_id: patientId.trim() || undefined,
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
      setPatientId("");
    } catch (err) {
      setResult({ ok: false, msg: err instanceof Error ? err.message : "Failed to send" });
    } finally {
      setSubmitting(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    await dispatchText(text);
  }

  function startListening(autoSend: boolean) {
    const Ctor = getSpeechRecognition();
    if (!Ctor) {
      setVoiceError("Voice input not supported in this browser");
      return;
    }
    setVoiceError(null);
    setResult(null);
    if (!open) setOpen(true);
    autoSendRef.current = autoSend;
    baseTextRef.current = autoSend ? "" : (text ? text.trimEnd() + " " : "");
    finalTranscriptRef.current = "";
    if (autoSend) setText("");

    const recog = new Ctor();
    recog.lang = "en-US";
    recog.continuous = true;
    recog.interimResults = true;
    recog.onresult = (e) => {
      let finalChunk = "";
      let interimChunk = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        const t = r[0]?.transcript ?? "";
        if (r.isFinal) finalChunk += t;
        else interimChunk += t;
      }
      if (finalChunk) finalTranscriptRef.current += finalChunk;
      setInterim(interimChunk);
      setText(
        (baseTextRef.current + finalTranscriptRef.current + interimChunk)
          .replace(/\s+/g, " ")
          .trimStart(),
      );
    };
    recog.onerror = (e) => {
      setVoiceError(e?.error ? `Mic error: ${e.error}` : "Mic error");
    };
    recog.onend = () => {
      setListening(false);
      setInterim("");
      const finalText = (baseTextRef.current + finalTranscriptRef.current)
        .replace(/\s+/g, " ")
        .trim();
      setText(finalText);
      if (autoSendRef.current && finalText) {
        void dispatchText(finalText);
      }
      autoSendRef.current = false;
    };

    try {
      recog.start();
      recogRef.current = recog;
      setListening(true);
    } catch (err) {
      setVoiceError(err instanceof Error ? err.message : "Failed to start mic");
      setListening(false);
    }
  }

  function stopListening() {
    try {
      recogRef.current?.stop();
    } catch {
      /* noop */
    }
  }

  function cancelListening() {
    autoSendRef.current = false;
    try {
      recogRef.current?.abort();
    } catch {
      /* noop */
    }
    setListening(false);
    setInterim("");
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
      <style>{`
        @keyframes medpage-pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(1.3); }
        }
        @media (prefers-reduced-motion: reduce) {
          @keyframes medpage-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
          }
        }
      `}</style>
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
        <div style={{ display: "flex", alignItems: "stretch" }}>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            style={{
              flex: 1,
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
          {voiceSupported ? (
            <button
              type="button"
              onClick={() => (listening ? stopListening() : startListening(true))}
              title={listening ? "Stop and send" : "Voice page (auto-send on stop)"}
              aria-pressed={listening}
              style={{
                borderLeft: HAIRLINE,
                padding: "0 14px",
                fontSize: 13,
                fontWeight: 500,
                background: listening ? "var(--color-text-danger, #c0392b)" : "transparent",
                color: listening ? "#fff" : "var(--color-text-primary)",
                border: "none",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 6,
                transition: "background 200ms ease, color 200ms ease",
              }}
            >
              <span
                aria-hidden
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: listening ? "#fff" : "var(--color-text-danger, #c0392b)",
                  animation: listening ? "medpage-pulse 1s ease-in-out infinite" : "none",
                  display: "inline-block",
                }}
              />
              {listening ? "Listening… tap to send" : "Voice page"}
            </button>
          ) : null}
        </div>

        {open ? (
          <form onSubmit={submit} style={{ padding: 14, borderTop: HAIRLINE, display: "flex", flexDirection: "column", gap: 10 }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                <label style={{ ...labelStyle, marginBottom: 0 }} htmlFor="page-text">Describe the situation</label>
                {voiceSupported ? (
                  <button
                    type="button"
                    onClick={() => (listening ? cancelListening() : startListening(false))}
                    title={listening ? "Stop dictating" : "Dictate into field"}
                    style={{
                      fontSize: 11,
                      padding: "4px 8px",
                      borderRadius: 6,
                      border: HAIRLINE,
                      background: listening ? "var(--color-text-danger, #c0392b)" : "transparent",
                      color: listening ? "#fff" : "var(--color-text-secondary)",
                      cursor: "pointer",
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      transition: "background 200ms ease, color 200ms ease",
                    }}
                  >
                    <span
                      aria-hidden
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: "50%",
                        background: listening ? "#fff" : "var(--color-text-danger, #c0392b)",
                        animation: listening ? "medpage-pulse 1s ease-in-out infinite" : "none",
                      }}
                    />
                    {listening ? "Stop" : "Mic"}
                  </button>
                ) : null}
              </div>
              <textarea
                id="page-text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={
                  listening
                    ? "Listening… speak the patient, room, and symptoms"
                    : "e.g. Chest pain in room 412, patient diaphoretic"
                }
                rows={3}
                style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
              />
              {listening && interim ? (
                <div style={{ marginTop: 4, fontSize: 11, color: "var(--color-text-tertiary)", fontStyle: "italic" }}>
                  …{interim}
                </div>
              ) : null}
              {voiceError ? (
                <div style={{ marginTop: 4, fontSize: 11, color: "var(--color-text-danger)" }}>
                  {voiceError}
                </div>
              ) : null}
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

            <div>
              <label style={labelStyle} htmlFor="page-patient-id">Patient ID</label>
              <input
                id="page-patient-id"
                type="text"
                value={patientId}
                onChange={(e) => setPatientId(e.target.value)}
                placeholder="e.g. P-1042"
                style={inputStyle}
              />
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
              {(() => {
                const hasAny = !!(text.trim() || room || specialty || patientId.trim());
                return (
              <button
                type="submit"
                disabled={submitting || !hasAny}
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
                  opacity: !hasAny ? 0.5 : 1,
                }}
              >
                {submitting ? "Sending…" : "Send page"}
              </button>
                );
              })()}
            </div>
          </form>
        ) : null}
      </div>
    </div>
  );
}
