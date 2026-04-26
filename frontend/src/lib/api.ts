import type { ClinicianRecord, DispatchResult } from "./types";

const base = () =>
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001";

// The clinician roster lives on the Flask backend at /api/doctors. Earlier
// versions assumed a separate FastAPI service at /clinicians, which 404s when
// only Flask is running.
const backendBase = () =>
  process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001";

export async function postDispatch(body: {
  raw_text?: string | null;
  room?: string | null;
  specialty_hint?: string | null;
  patient_id?: string | null;
}): Promise<DispatchResult> {
  const r = await fetch(`${base()}/dispatch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      raw_text: body.raw_text || "",
      room: body.room || undefined,
      specialty_hint: body.specialty_hint || undefined,
      patient_id: body.patient_id || undefined,
    }),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return r.json() as Promise<DispatchResult>;
}

export async function getClinicians(): Promise<ClinicianRecord[]> {
  // Try FastAPI's /clinicians first (legacy), fall back to Flask /api/doctors.
  // Either way we end up with the full doctor roster used by the directory and
  // the floor map.
  try {
    const r = await fetch(`${base()}/clinicians`, { cache: "no-store" });
    if (r.ok) return (await r.json()) as ClinicianRecord[];
  } catch {
    // network error — try the Flask backend below
  }
  const r2 = await fetch(`${backendBase()}/api/doctors`, { cache: "no-store" });
  if (!r2.ok) {
    const t = await r2.text();
    throw new Error(t || r2.statusText);
  }
  return (await r2.json()) as ClinicianRecord[];
}

export interface ClinicianPatch {
  on_call?: boolean;
  shift_start?: string | null;
  shift_end?: string | null;
  status?: string;
  zone?: string;
}

export async function patchClinician(
  id: string,
  patch: ClinicianPatch,
): Promise<ClinicianRecord> {
  const r = await fetch(`${base()}/clinicians/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return r.json() as Promise<ClinicianRecord>;
}
