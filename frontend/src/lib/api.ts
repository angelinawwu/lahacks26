import type { ClinicianRecord, DispatchResult } from "./types";

const base = () =>
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ||
  "http://127.0.0.1:8000";

export async function postDispatch(body: {
  raw_text: string;
  room?: string | null;
  specialty_hint?: string | null;
}): Promise<DispatchResult> {
  const r = await fetch(`${base()}/dispatch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      raw_text: body.raw_text,
      room: body.room || undefined,
      specialty_hint: body.specialty_hint || undefined,
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
