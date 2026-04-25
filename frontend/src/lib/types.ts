export type PriorityLevel = "P1" | "P2" | "P3" | "P4";

export interface PriorityResult {
  priority: string;
  guardrail_flags: string[];
  reasoning: string;
  fallback_used: boolean;
}

export interface Candidate {
  id: string;
  name: string;
  score: number;
  reasoning: string;
  specialty: string[];
  zone?: string | null;
  on_call: boolean;
  page_count_1hr: number;
  eta_minutes?: number | null;
}

export interface CaseResult {
  candidates: Candidate[];
  specialty_query: string[];
  total_available: number;
  reasoning: string;
  fallback_used: boolean;
}

export interface DispatchResult {
  alert_id?: string;
  priority: PriorityResult;
  case: CaseResult;
}

export type ClinicianStatus =
  | "available"
  | "in_procedure"
  | "off_shift"
  | "on_case"
  | "paging";

export type ClinicianRecord = {
  id: string;
  name: string;
  specialty: string[];
  status: ClinicianStatus | string;
  on_call: boolean;
  zone: string;
  page_count_1hr: number;
  active_cases: number;
  lat?: number;
  lng?: number;
};

// --------------------------------------------------------------------------- //
// Socket.IO event payloads (mirrors api/main.py)                               //
// --------------------------------------------------------------------------- //
export type AlertStatus =
  | "paging"
  | "accepted"
  | "en_route"
  | "escalating"
  | "declined"
  | "resolved"
  | "queued";

export interface AlertEvent {
  alert_id: string;
  title: string;
  room?: string | null;
  priority: PriorityLevel | string;
  assigned_clinician_id?: string | null;
  assigned_clinician_name?: string | null;
  specialty?: string[];
  status: AlertStatus | string;
  created_at: string;
  ack_deadline_seconds: number;
  reasoning?: string;
  guardrail_flags?: string[];
  responded_at?: string;
}

export interface IncomingPagePayload {
  alert_id: string;
  title: string;
  room?: string | null;
  priority: PriorityLevel | string;
  reasoning: string;
  created_at: string;
  ack_deadline_seconds: number;
}

export interface PageResolvedPayload {
  alert_id: string;
  outcome: "accepted" | "declined" | "escalated" | "resolved";
}

export interface ClinicianStatusChanged {
  clinician_id: string;
  status: ClinicianStatus | string;
  zone?: string;
}

export interface OperatorSnapshot {
  active_cases: AlertEvent[];
  clinicians: ClinicianRecord[];
}

export interface PageResponsePayload {
  alert_id: string;
  clinician_id: string;
  response: "accept" | "decline";
}

export interface StatusUpdatePayload {
  clinician_id: string;
  status: ClinicianStatus;
}
