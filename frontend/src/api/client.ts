/**
 * Typed API Client for HowlWriter local backend.
 */

import {
  
  AssignmentSpec,
  DocumentData,
  HowlPipelineResponse,
  HumanizeResponse,
  JobResponse,
  LintResponse,
  ProvidersResponse,
  RedPenResponse,
  RunRecord,
  ValidateSpecResponse,
  VoiceDetail,
  VoiceSummary,
} from '../types';

const API_BASE = '/api';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorDetail = `Request failed with status ${res.status}`;
    try {
      const errJson = await res.json();
      if (errJson.error) {
        errorDetail = typeof errJson.error === 'string' ? errJson.error : JSON.stringify(errJson.error);
      } else if (errJson.detail) {
        errorDetail = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
      }
    } catch {
      // ignore
    }
    throw new Error(errorDetail);
  }
  return res.json();
}

export const api = {
  async openDocument(path: string): Promise<DocumentData> {
    const res = await fetch(`${API_BASE}/documents/open`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    return handleResponse<DocumentData>(res);
  },

  async saveDocument(path: string, content: string): Promise<DocumentData> {
    const res = await fetch(`${API_BASE}/documents/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, content }),
    });
    return handleResponse<DocumentData>(res);
  },

  async runLint(text: string, title?: string): Promise<LintResponse> {
    const res = await fetch(`${API_BASE}/lint`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, title }),
    });
    return handleResponse<LintResponse>(res);
  },

  async runRedPen(text: string, title?: string, claims: any[] = []): Promise<RedPenResponse> {
    const res = await fetch(`${API_BASE}/redpen`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, title, claims }),
    });
    return handleResponse<RedPenResponse>(res);
  },

  async runHumanize(params: {
    text: string;
    title?: string;
    mode?: string;
    deterministic_only?: boolean;
    apply_safe_rewrites?: boolean;
    voice_profile?: string;
  }): Promise<HumanizeResponse> {
    const res = await fetch(`${API_BASE}/humanize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    return handleResponse<HumanizeResponse>(res);
  },

  async runHowl(params: {
    text: string;
    title?: string;
    mode?: string;
    deterministic_only?: boolean;
    apply_safe_rewrites?: boolean;
    voice_profile?: string;
  }): Promise<HowlPipelineResponse> {
    const res = await fetch(`${API_BASE}/howl`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    return handleResponse<HowlPipelineResponse>(res);
  },

  async validateSpec(spec: AssignmentSpec): Promise<ValidateSpecResponse> {
    const res = await fetch(`${API_BASE}/academic/validate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ spec }),
    });
    return handleResponse<ValidateSpecResponse>(res);
  },

  async generatePaper(spec: AssignmentSpec, deterministic_only = false): Promise<JobResponse> {
    const res = await fetch(`${API_BASE}/academic/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ spec, deterministic_only }),
    });
    return handleResponse<JobResponse>(res);
  },

  async getJobStatus(jobId: string): Promise<JobResponse> {
    const res = await fetch(`${API_BASE}/jobs/${jobId}`);
    return handleResponse<JobResponse>(res);
  },

  subscribeToJobEvents(
    jobId: string,
    onEvent: (event: any) => void,
    onError: (err: any) => void
  ): () => void {
    const eventSource = new EventSource(`${API_BASE}/jobs/${jobId}/events`);

    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        onEvent(data);
      } catch (err) {
        // ping or comment
      }
    };

    eventSource.addEventListener('snapshot', (e: any) => {
      try {
        const data = JSON.parse(e.data);
        onEvent({ event: 'snapshot', data });
      } catch {}
    });

    eventSource.addEventListener('stage_update', (e: any) => {
      try {
        const data = JSON.parse(e.data);
        onEvent(data);
      } catch {}
    });

    eventSource.addEventListener('completed', (e: any) => {
      try {
        const data = JSON.parse(e.data);
        onEvent(data);
        eventSource.close();
      } catch {}
    });

    eventSource.addEventListener('failed', (e: any) => {
      try {
        const data = JSON.parse(e.data);
        onEvent(data);
        eventSource.close();
      } catch {}
    });

    eventSource.onerror = (e) => {
      onError(e);
    };

    return () => {
      eventSource.close();
    };
  },

  async listRuns(limit = 30): Promise<RunRecord[]> {
    const res = await fetch(`${API_BASE}/runs?limit=${limit}`);
    return handleResponse<RunRecord[]>(res);
  },

  async getRun(runId: string): Promise<RunRecord> {
    const res = await fetch(`${API_BASE}/runs/${runId}`);
    return handleResponse<RunRecord>(res);
  },

  async getProviders(): Promise<ProvidersResponse> {
    const res = await fetch(`${API_BASE}/providers`);
    return handleResponse<ProvidersResponse>(res);
  },

  // --- Personal voices ---

  async listVoices(): Promise<VoiceSummary[]> {
    const res = await fetch(`${API_BASE}/voices`);
    return handleResponse<VoiceSummary[]>(res);
  },

  async getVoice(name: string): Promise<VoiceDetail> {
    const res = await fetch(`${API_BASE}/voices/${encodeURIComponent(name)}`);
    return handleResponse<VoiceDetail>(res);
  },

  async rebuildVoice(
    name: string,
    params: { deterministic?: boolean; reuse_cache?: boolean } = {},
  ): Promise<JobResponse> {
    const res = await fetch(`${API_BASE}/voices/${encodeURIComponent(name)}/rebuild`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ deterministic: false, reuse_cache: true, ...params }),
    });
    return handleResponse<JobResponse>(res);
  },

};
