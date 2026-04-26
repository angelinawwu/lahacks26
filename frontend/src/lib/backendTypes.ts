import type { PriorityLevel } from "./types";

export type QueueStatus = "paging" | "pending" | "pending_approval" | "escalated" | "accepted" | "declined" | "expired" | "cancelled" | "resolved" | "rejected";

export interface EscalationEntry {
  from_doctor: string | null;
  to_doctor: string;
  timestamp: string;
  reason?: string;
}

export interface QueueDoctor {
  name?: string;
  specialty?: string[];
  zone?: string;
  status?: string;
}

export interface QueuePage {
  id: string;
  doctor_id: string | null;
  patient_id?: string | null;
  message?: string;
  priority: PriorityLevel | string;
  room?: string | null;
  requested_by?: string | null;
  backup_doctors?: string[];
  status: QueueStatus | string;
  created_at: string;
  responded_at?: string | null;
  outcome?: string | null;
  escalation_history?: EscalationEntry[];
  escalation_count?: number;
  time_remaining_seconds?: number;
  timeout_seconds?: number;
  elapsed_seconds?: number;
  doctor?: QueueDoctor;
  escalated_at?: string;
  cancelled_at?: string;
  rejected_at?: string;
  approved_at?: string;
  // Dispatch-specific fields (set when source === "dispatch")
  title?: string;
  assigned_clinician_name?: string;
  specialty?: string[];
  reasoning?: string;
  guardrail_flags?: string[];
  needs_operator_review?: boolean;
  source?: "dispatch" | string;
}

export interface QueueResponse {
  pages: QueuePage[];
  total: number;
  by_priority: Record<"P1" | "P2" | "P3" | "P4", number>;
}

// --------------------------------------------------------------------------- //
// Proactive recommendations (Sentinel)                                         //
// --------------------------------------------------------------------------- //

export type PatternType =
  | "alert_concentration"
  | "ack_gap"
  | "coverage_hole"
  | "caseload_concentration";

export type Severity = "low" | "medium" | "high" | "critical";

export interface ProactiveRecommendation {
  id: string;
  pattern_type: PatternType | string;
  severity: Severity | string;
  recommendation: string;
  rationale: string;
  suggested_actions?: string[];
  requires_ack: boolean;
  created_at?: string;
  zone?: string;
  specialty?: string;
}

export interface ProactiveAcked {
  id: string;
  outcome: "approve" | "reject";
  operator_id?: string;
}

// --------------------------------------------------------------------------- //
// SBAR briefs                                                                  //
// --------------------------------------------------------------------------- //

export interface SbarSections {
  situation?: string;
  background?: string;
  assessment?: string;
  request?: string;
}

export interface SbarBrief {
  page_id: string;
  alert_id?: string;
  brief_text: string;
  word_count: number;
  sections?: SbarSections;
  created_at?: string;
}

// --------------------------------------------------------------------------- //
// Pattern detection (operator decoration)                                      //
// --------------------------------------------------------------------------- //

export interface AppSettings {
  max_pages_per_hour: number;
  require_on_call: boolean;
  allow_off_shift: boolean;
  default_operator_view: "map" | "feed";
  global_mode: "automated" | "manual";
}

export interface PagingModeEntry {
  mode: "automated" | "manual";
  set_by?: string | null;
  set_at?: string | null;
  reason?: string;
}

export interface PagingModesState {
  global_mode: "automated" | "manual";
  global_set_by?: string | null;
  global_set_at?: string | null;
  global_reason?: string;
  zones: Record<string, PagingModeEntry>;
  page_overrides: Record<string, PagingModeEntry>;
}

export interface PatternSignal {
  id?: string;
  pattern_type: PatternType | string;
  severity?: Severity | string;
  zone?: string;
  specialty?: string;
  rooms?: string[];
  message?: string;
  created_at?: string;
}
