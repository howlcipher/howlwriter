/**
 * Which model runs a writing step, chosen by the person each time.
 *
 * When the server answers 409 `model_choice_required`, nothing has been sent
 * to any model. `apiFetch` asks (through the ModelPickerModal), then retries
 * the same request once with the choice in headers. The choice is not
 * remembered: the next run asks again.
 */

export interface ModelOption {
  provider: string;
  label: string;
  local: boolean;
  available: boolean;
  detail: string;
  disclosure: string;
}

/** `provider` is a model id, or 'none' to continue without a model. */
export interface ModelDecision {
  provider: string;
  confirmed: boolean;
}

export interface ModelChoiceRequest {
  role: string;
  detail: string;
  resolve: (decision: ModelDecision | null) => void;
}

type Listener = (request: ModelChoiceRequest) => void;
let listener: Listener | null = null;

/** The picker registers here; only one picker is mounted. */
export function onModelChoiceRequest(next: Listener | null): void {
  listener = next;
}

function askForModel(role: string, detail: string): Promise<ModelDecision | null> {
  if (!listener) return Promise.resolve(null);
  return new Promise((resolve) => listener?.({ role, detail, resolve }));
}

function withChoice(init: RequestInit | undefined, decision: ModelDecision): RequestInit {
  const headers = new Headers(init?.headers);
  headers.set('X-HowlWriter-Provider', decision.provider);
  if (decision.confirmed) headers.set('X-HowlWriter-Send-Confirmed', '1');
  return { ...init, headers };
}

export async function fetchModelChoices(): Promise<ModelOption[]> {
  const res = await fetch('/api/providers/choices');
  if (!res.ok) throw new Error(`Could not list models (status ${res.status})`);
  const body = await res.json();
  return body.choices as ModelOption[];
}

/** fetch() that asks which model to use when the server needs one. */
export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(input, init);
  if (res.status !== 409) return res;
  let body: { code?: string; role?: string; detail?: string } | null = null;
  try {
    body = await res.clone().json();
  } catch {
    return res;
  }
  if (body?.code !== 'model_choice_required') return res;
  const decision = await askForModel(body.role || 'writer', body.detail || '');
  if (!decision) return res; // cancelled: the original "no model chosen" error surfaces
  return fetch(input, withChoice(init, decision));
}
