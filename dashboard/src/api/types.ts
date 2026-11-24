/**
 * Response shapes for engine endpoints that return plain dicts.
 * Typed request bodies and path params come from the generated OpenAPI schema (schema.d.ts).
 */
import type { components } from "./schema";

export type RequestOut = components["schemas"]["RequestOut"];
export type HardLineIn = components["schemas"]["HardLineIn"];

export type RiskBand = "low" | "medium" | "high";
export type RequestStatus =
  | "pending" | "approved" | "denied" | "auto_approved" | "auto_denied" | "flagged" | "expired";
export type RuleStatus = "proposed" | "active" | "paused" | "expired";
export type Op = "eq" | "ne" | "lte" | "gte" | "in" | "contains";

export interface Condition { field: string; op: Op; value: unknown }

export interface RequestSummary {
  id: string;
  agent: string;
  platform: string;
  action: string;
  status: RequestStatus;
  risk: number;
  risk_band: RiskBand;
  client: string | null;
  amount: number | null;
  reason: string;
  rule_id: string | null;
  created_at: string;
  expires_at: string;
}

export interface Payload {
  agent: string;
  platform: string;
  action: string;
  environment: string;
  reversible: boolean;
  amount?: { value: number; currency: string } | null;
  recipient?: { id: string; known: boolean } | null;
  target?: { type?: string } | null;
  context?: { command?: string; summary?: string; [k: string]: unknown } | null;
  client?: string | null;
}

export interface Decision {
  by: string;
  approved: boolean;
  human: boolean;
  channel: string | null;
  note: string | null;
  latency_ms: number | null;
  at: string;
}

export interface RequestDetail extends RequestSummary {
  payload: Payload;
  risk_reasons: [string, number][];
  receipt: Record<string, unknown> | null;
  approvals_needed: number;
  decisions: Decision[];
}

export interface Evidence {
  approvals?: number;
  denials?: number;
  days?: number;
  wilson_lower_bound?: number;
}

export interface Rule {
  id: string;
  description: string;
  status: RuleStatus;
  effect: "approve" | "deny";
  conditions: Condition[];
  evidence: Evidence | null;
  fire_count: number;
  accepted_by: string | null;
}

export interface Backtest {
  rule: string;
  history_size: number;
  would_auto_approve: number;
  matched_past_denials: number;
  passed: boolean;
}

export interface HardLine { id: string; description: string; conditions: Condition[] }

export interface AuditVerify { ok: boolean; first_bad_seq: number | null; entries: number }
export interface AuditEntry { seq: number; event: string; data: Record<string, unknown>; at: string; hash: string }

export interface Insights {
  total_requests: number;
  by_status: Record<string, number>;
  automation_rate: number;
  human_decisions: number;
  median_response_ms: number | null;
  minutes_saved_estimate: number;
  agents: Record<string, { requests: number; denied: number; auto: number }>;
  rules: { active: number; proposed: number; paused: number };
}

export interface FlagResult { id: string; rule: string | null; rule_paused: boolean }
