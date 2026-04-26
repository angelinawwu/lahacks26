import type { ClinicianRecord, DispatchResult } from "./types";

const base = () =>
  process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "") ||
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ||
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
  const r = await fetch(`${base()}/clinicians`, { cache: "no-store" });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return r.json() as Promise<ClinicianRecord[]>;
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
