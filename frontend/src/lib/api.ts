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
  // Flask backend exposes the AI dispatch flow at /api/voice/urgent
  // (transcribe → parse → classify → page). We pass the alert text as
  // `transcript` so the server skips audio decoding.
  const r = await fetch(`${base()}/api/voice/urgent`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      transcript: (body.raw_text || "").trim() || "help",
      room: body.room || undefined,
      specialty_hint: body.specialty_hint || undefined,
      patient_id: body.patient_id || undefined,
    }),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  const page = (await r.json()) as Record<string, unknown>;
  const parsed = (page.parsed_fields as Record<string, unknown> | undefined) ?? {};
  const specialtyHint = parsed.specialty_hint as string | undefined;
  const specialtyQuery = specialtyHint ? [specialtyHint] : [];

  let candidateName = (page.doctor_id as string | undefined) ?? "";
  const doctorId = page.doctor_id as string | undefined;
  if (doctorId) {
    try {
      const docRes = await fetch(`${base()}/api/doctors/${doctorId}`, {
        cache: "no-store",
      });
      if (docRes.ok) {
        const doc = (await docRes.json()) as { name?: string };
        if (doc.name) candidateName = doc.name;
      }
    } catch {
      // Non-fatal — fall back to the doctor id.
    }
  }

  return {
    alert_id: (page.id as string) ?? undefined,
    priority: {
      priority: (page.priority as string) ?? "P3",
      guardrail_flags: [],
      reasoning: (page.voice_summary as string) ?? "",
      fallback_used: false,
    },
    case: {
      candidates: doctorId
        ? [
            {
              id: doctorId,
              name: candidateName || doctorId,
              score: 1,
              reasoning: "Selected by Flask voice/urgent pipeline",
              specialty: specialtyQuery,
              on_call: false,
              page_count_1hr: 0,
            },
          ]
        : [],
      specialty_query: specialtyQuery,
      total_available: doctorId ? 1 : 0,
      reasoning: (page.voice_summary as string) ?? "",
      fallback_used: false,
    },
  };
}

export async function getClinicians(): Promise<ClinicianRecord[]> {
  const r = await fetch(`${base()}/api/doctors`, { cache: "no-store" });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return (await r.json()) as ClinicianRecord[];
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
  // Flask backend's status endpoint only accepts status / zone / on_call.
  const body: Record<string, unknown> = {};
  if (patch.status !== undefined) body.status = patch.status;
  if (patch.zone !== undefined) body.zone = patch.zone;
  if (patch.on_call !== undefined) body.on_call = patch.on_call;

  const r = await fetch(`${base()}/api/doctors/${id}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return r.json() as Promise<ClinicianRecord>;
}
