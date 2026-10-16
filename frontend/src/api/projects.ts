/**
 * Source Intelligence API: projects, evidence, requirements, drafting, browser sessions.
 */

import { JobResponse } from '../types';

const BASE = '/api/projects';

export interface ProjectSummary {
  project_id: string;
  name: string;
  root: string;
  sources: number;
  sources_by_category: Record<string, number>;
  sources_by_status: Record<string, number>;
  evidence: number;
  evidence_by_status: Record<string, number>;
  requirements: number;
  requirements_by_status: Record<string, number>;
  browser_actions: number;
  remote_inference_authorized: boolean;
  scan_state: { status?: string; started_at?: string; finished_at?: string };
  last_scan: Record<string, unknown>;
  validation: { at?: string; verdict?: string; issue_counts?: Record<string, number> };
}

export interface SourceRow {
  source_id: string;
  path: string;
  category: string;
  category_source: string;
  category_reason: string;
  status: string;
  status_reason: string;
  evidence_count: number;
  adapter: string;
  warnings: string[];
}

export interface EvidenceRow {
  evidence_id: string;
  citation: string;
  status: string;
  category: string;
  kind: string;
  excerpt: string;
  method?: string;
  limitations?: string[];
  score?: number;
  why?: string;
}

export interface RequirementRow {
  requirement_id: string;
  kind: string;
  text: string;
  location: string;
  status: string;
  reason: string;
  evidence_ids: string[];
}

export interface Coverage {
  total: number;
  unmet: number;
  by_status: Record<string, number>;
  rows: RequirementRow[];
}

export interface BrowserAction {
  action_id: string;
  mode: string;
  kind: string;
  url: string;
  target: string;
  decision: string;
  outcome: string;
  changed_state: boolean;
  requested_at: string;
  error: string;
  evidence_ids: string[];
}

export interface BrowserStatus {
  state: string;
  policy?: { mode: string; allowed_origins: string[]; interactive_origins: string[] };
  url?: string;
  pending?: BrowserAction[];
  blocked?: Array<{ at: string; url: string; method: string; reason: string }>;
  recent_actions?: BrowserAction[];
}

export interface Validation {
  verdict: string;
  citations: number;
  sentences_with_claims: number;
  issue_counts: Record<string, number>;
  issues: Array<{ type: string; sentence: string }>;
  missing_placeholders: string[];
  requirements: Coverage;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
  });
  if (!res.ok) {
    let detail = `Request failed with status ${res.status}`;
    try {
      const body = await res.json();
      detail = body.error || body.detail || detail;
    } catch {
      // ignore
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return res.json();
}

const post = <T>(path: string, body: unknown = {}) => call<T>(path, { method: 'POST', body: JSON.stringify(body) });
const id = (projectId: string) => encodeURIComponent(projectId);

export const projectsApi = {
  list: () => call<ProjectSummary[]>(''),
  open: (folder: string, name?: string) => post<ProjectSummary>('', { folder, name: name || null }),
  get: (p: string) => call<ProjectSummary>(`/${id(p)}`),
  scan: (p: string, options: { transcribe: boolean; frames: boolean; ocr: boolean; force?: boolean }) =>
    post<JobResponse>(`/${id(p)}/scan`, options),
  sources: (p: string) => call<SourceRow[]>(`/${id(p)}/sources`),
  setCategory: (p: string, sourceId: string, category: string) =>
    post<SourceRow>(`/${id(p)}/sources/${encodeURIComponent(sourceId)}/category`, { category }),
  evidence: (p: string, source?: string) =>
    call<EvidenceRow[]>(`/${id(p)}/evidence?limit=200${source ? `&source=${encodeURIComponent(source)}` : ''}`),
  search: (p: string, q: string, purpose: string) =>
    call<EvidenceRow[]>(`/${id(p)}/search?q=${encodeURIComponent(q)}&purpose=${purpose}`),
  requirements: (p: string) => call<Coverage>(`/${id(p)}/requirements`),
  addRequirement: (p: string, text: string) => post(`/${id(p)}/requirements`, { text }),
  setRequirementStatus: (p: string, rid: string, status: string, note = '') =>
    post(`/${id(p)}/requirements/${encodeURIComponent(rid)}/status`, { status, note }),
  skeleton: (p: string) => post<{ text: string; path: string; summary: Record<string, number> }>(`/${id(p)}/draft/skeleton`),
  draft: (p: string, body: Record<string, unknown>) => post<JobResponse>(`/${id(p)}/draft`, body),
  validate: (p: string, text: string) => post<Validation>(`/${id(p)}/validate`, { text }),
  browser: (p: string) => call<BrowserStatus>(`/${id(p)}/browser`),
  browserStart: (p: string, body: { mode: string; allowed_origins: string[]; interactive_origins: string[] }) =>
    post<BrowserStatus>(`/${id(p)}/browser/start`, body),
  browserStop: (p: string) => post(`/${id(p)}/browser/stop`),
  browserVerb: (p: string, verb: 'pause' | 'resume' | 'read-only' | 'read') => post(`/${id(p)}/browser/${verb}`),
  browserNavigate: (p: string, url: string) => post<BrowserAction>(`/${id(p)}/browser/navigate`, { url }),
  browserScreenshot: (p: string, label: string) => post(`/${id(p)}/browser/screenshot`, { label }),
  browserRequest: (p: string, kind: string, selector: string, value?: string) =>
    post(`/${id(p)}/browser/request`, { kind, selector, value: value || null }),
  browserDecide: (p: string, actionId: string, decision: 'approve' | 'deny') =>
    post<BrowserAction>(`/${id(p)}/browser/actions/${encodeURIComponent(actionId)}/${decision}`),
  job: async (jobId: string): Promise<JobResponse> => {
    const res = await fetch(`/api/jobs/${jobId}`);
    return res.json();
  },
};
