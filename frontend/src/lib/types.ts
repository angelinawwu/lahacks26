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
  priority: PriorityResult;
  case: CaseResult;
}

export type ClinicianRecord = {
  id: string;
  name: string;
  specialty: string[];
  status: string;
  on_call: boolean;
  zone: string;
  page_count_1hr: number;
  active_cases: number;
  lat?: number;
  lng?: number;
};
