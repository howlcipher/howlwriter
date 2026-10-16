/**
 * Source Intelligence: open a folder of materials, see what each file is and what was
 * extracted, track requirements, write from evidence, and (optionally) run a controlled
 * browser session. Browser automation is one tab among five and never required.
 */

import React from 'react';
import { BookOpen, CheckSquare, FolderOpen, Globe, Library, PenLine, Search } from 'lucide-react';
import {
  BrowserStatus,
  Coverage,
  EvidenceRow,
  ProjectSummary,
  SourceRow,
  Validation,
  projectsApi,
} from '../../api/projects';
import { JobResponse } from '../../types';

type View = 'sources' | 'evidence' | 'requirements' | 'write' | 'browser';

const CATEGORIES = [
  'assignment_instructions', 'rubric', 'supporting_reference', 'experimental_evidence', 'screenshot',
  'packet_capture', 'multimedia', 'user_draft', 'output_document', 'unknown',
];

const STATUS_CLASS: Record<string, string> = {
  satisfied_with_evidence: 'chip-pass',
  partially_satisfied: 'chip-warn',
  pending_user_work: 'chip-warn',
  blocked: 'chip-fail',
  not_applicable: '',
  extracted: 'chip-pass',
  partial: 'chip-warn',
  failed: 'chip-fail',
  unavailable: 'chip-fail',
  duplicate: '',
  skipped: '',
};

const Chip: React.FC<{ value: string }> = ({ value }) => (
  <span className={`chip ${STATUS_CLASS[value] ?? ''}`} style={{ fontSize: 10 }}>
    {value.replace(/_/g, ' ')}
  </span>
);

async function waitForJob(job: JobResponse): Promise<JobResponse> {
  let current = job;
  while (current.status === 'QUEUED' || current.status === 'RUNNING') {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    current = await projectsApi.job(current.job_id);
  }
  return current;
}

const ROW: React.CSSProperties = { borderBottom: '1px solid var(--border-color, #333)', padding: '6px 0', fontSize: 12 };
const MUTED: React.CSSProperties = { fontSize: 11, opacity: 0.7 };

// --- open -----------------------------------------------------------------------

const OpenProject: React.FC<{ onOpened: (p: ProjectSummary) => void }> = ({ onOpened }) => {
  const [folder, setFolder] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const submit = async () => {
    setError(null);
    try {
      onOpened(await projectsApi.open(folder.trim()));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not open the folder');
    }
  };
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
      <input className="form-input" style={{ flex: 1, minWidth: 260 }} placeholder="/path/to/assignment folder"
        value={folder} onChange={(e) => setFolder(e.target.value)} aria-label="Project folder" />
      <button type="button" className="btn-tech btn-tech-primary" disabled={!folder.trim()} onClick={submit}>
        <FolderOpen size={14} /> Open folder
      </button>
      {error && <div className="chip chip-fail">{error}</div>}
      <div style={{ ...MUTED, width: '100%' }}>
        Only this folder is read, never modified. Everything extracted stays in your private workspace.
      </div>
    </div>
  );
};

// --- sources --------------------------------------------------------------------

const SourcesView: React.FC<{ project: string; onChanged: () => void }> = ({ project, onChanged }) => {
  const [rows, setRows] = React.useState<SourceRow[]>([]);
  const load = React.useCallback(() => projectsApi.sources(project).then(setRows), [project]);
  React.useEffect(() => { load(); }, [load]);
  const correct = async (sourceId: string, category: string) => {
    await projectsApi.setCategory(project, sourceId, category);
    await load();
    onChanged();
  };
  return (
    <div>
      {rows.map((s) => (
        <div key={s.source_id} style={ROW}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <Chip value={s.status} />
            <span style={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>{s.path}</span>
            <span style={MUTED}>{s.evidence_count} evidence · {s.adapter || 'no adapter'}</span>
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4 }}>
            <select className="form-select" style={{ width: 'auto', fontSize: 11 }} value={s.category}
              onChange={(e) => correct(s.source_id, e.target.value)} aria-label={`Category for ${s.path}`}>
              {CATEGORIES.map((c) => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}
            </select>
            <span style={MUTED}>{s.category_source === 'user' ? 'set by you' : s.category_reason}</span>
          </div>
          {(s.status_reason || s.warnings.length > 0) && (
            <div style={MUTED}>{[s.status_reason, ...s.warnings.slice(0, 3)].filter(Boolean).join(' · ')}</div>
          )}
        </div>
      ))}
    </div>
  );
};

// --- evidence -------------------------------------------------------------------

const EvidenceList: React.FC<{ rows: EvidenceRow[] }> = ({ rows }) => (
  <div>
    {rows.map((e) => (
      <div key={e.evidence_id} style={ROW}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <code>[{e.evidence_id}]</code> <strong>{e.citation}</strong> <Chip value={e.status} />
          <span style={MUTED}>{e.category.replace(/_/g, ' ')}</span>
        </div>
        <div style={{ marginTop: 3 }}>{e.excerpt.slice(0, 400)}</div>
        {e.why && <div style={MUTED}>why: {e.why}</div>}
        {e.limitations && e.limitations.length > 0 && <div style={MUTED}>limits: {e.limitations.join('; ')}</div>}
      </div>
    ))}
    {rows.length === 0 && <div style={MUTED}>No evidence to show.</div>}
  </div>
);

const EvidenceView: React.FC<{ project: string }> = ({ project }) => {
  const [query, setQuery] = React.useState('');
  const [purpose, setPurpose] = React.useState('facts');
  const [rows, setRows] = React.useState<EvidenceRow[]>([]);
  React.useEffect(() => { projectsApi.evidence(project).then(setRows); }, [project]);
  const search = async () => setRows(query.trim() ? await projectsApi.search(project, query, purpose) : await projectsApi.evidence(project));
  return (
    <div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
        <input className="form-input" style={{ flex: 1 }} value={query} placeholder="What evidence do you need?"
          onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && search()} aria-label="Search evidence" />
        <select className="form-select" style={{ width: 'auto' }} value={purpose} onChange={(e) => setPurpose(e.target.value)} aria-label="Purpose">
          <option value="facts">facts</option>
          <option value="observations">observations only</option>
          <option value="requirements">requirements</option>
        </select>
        <button type="button" className="btn-tech" onClick={search}><Search size={14} /> Search</button>
      </div>
      <EvidenceList rows={rows} />
    </div>
  );
};

// --- requirements ---------------------------------------------------------------

const RequirementsView: React.FC<{ project: string; coverage: Coverage | null; reload: () => void }> = ({ project, coverage, reload }) => {
  const [text, setText] = React.useState('');
  if (!coverage) return <div style={MUTED}>Loading…</div>;
  return (
    <div>
      <div style={MUTED}>
        {coverage.total} requirements · {Object.entries(coverage.by_status).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(' · ')}.
        Instructions say what to do; only your captures, screenshots, data, or lab observations count as proof it was done.
      </div>
      {coverage.rows.map((r) => (
        <div key={r.requirement_id} style={ROW}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <Chip value={r.status} /> <span style={MUTED}>{r.kind}</span> {r.text}
          </div>
          <div style={MUTED}>from {r.location} · {r.reason}</div>
          <div style={{ display: 'flex', gap: 4, marginTop: 3 }}>
            {['not_applicable', 'blocked', 'clear'].map((s) => (
              <button key={s} type="button" className="btn-tech" style={{ fontSize: 10, padding: '1px 6px' }}
                onClick={async () => { await projectsApi.setRequirementStatus(project, r.requirement_id, s); reload(); }}>
                {s === 'clear' ? 'reset' : s.replace(/_/g, ' ')}
              </button>
            ))}
          </div>
        </div>
      ))}
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <input className="form-input" style={{ flex: 1 }} value={text} placeholder="Add a requirement by hand"
          onChange={(e) => setText(e.target.value)} aria-label="New requirement" />
        <button type="button" className="btn-tech" disabled={!text.trim()}
          onClick={async () => { await projectsApi.addRequirement(project, text); setText(''); reload(); }}>Add</button>
      </div>
    </div>
  );
};

// --- write ----------------------------------------------------------------------

const WriteView: React.FC<{ project: string; summary: ProjectSummary }> = ({ project, summary }) => {
  const [text, setText] = React.useState('');
  const [validation, setValidation] = React.useState<Validation | null>(null);
  const [identity, setIdentity] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [note, setNote] = React.useState<string | null>(null);

  const skeleton = async () => {
    setBusy(true);
    try {
      const result = await projectsApi.skeleton(project);
      setText(result.text);
      setNote(`Evidence skeleton saved privately as ${result.path}. No model was used.`);
    } finally {
      setBusy(false);
    }
  };
  const draft = async (allowRemote: boolean) => {
    setBusy(true);
    setNote(null);
    try {
      const job = await waitForJob(await projectsApi.draft(project, {
        mode: 'academic', identity: identity || null, allow_remote: allowRemote,
      }));
      const payload = (job.result as { payload?: Record<string, unknown> } | undefined)?.payload || {};
      if (job.status === 'FAILED') setNote(job.error_message || 'Drafting failed');
      else if (payload.needs_authorization) setNote(String(payload.error));
      else { setText(String(payload.text || '')); setNote(`Draft saved privately as ${payload.path}.`); }
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
        <button type="button" className="btn-tech" onClick={skeleton} disabled={busy}><BookOpen size={14} /> Evidence skeleton (no model)</button>
        <input className="form-input" style={{ width: 140 }} placeholder="identity (e.g. william)" value={identity}
          onChange={(e) => setIdentity(e.target.value)} aria-label="Voice identity" />
        <button type="button" className="btn-tech btn-tech-primary" onClick={() => draft(false)} disabled={busy}><PenLine size={14} /> Draft with voice</button>
        {!summary.remote_inference_authorized && (
          <button type="button" className="btn-tech" onClick={() => draft(true)} disabled={busy}
            title="Sends the selected evidence excerpts to the configured writer model this once">Draft (allow remote once)</button>
        )}
      </div>
      {note && <div style={{ ...MUTED, marginBottom: 6 }}>{note}</div>}
      <textarea className="form-textarea" rows={16} value={text} onChange={(e) => setText(e.target.value)} aria-label="Draft" />
      <button type="button" className="btn-tech" style={{ marginTop: 6 }} disabled={!text.trim()}
        onClick={async () => setValidation(await projectsApi.validate(project, text))}>
        <CheckSquare size={14} /> Validate citations and coverage
      </button>
      {validation && (
        <div style={{ marginTop: 8 }}>
          <Chip value={validation.verdict} /> {validation.citations} citations · {validation.sentences_with_claims} claim sentences ·{' '}
          {validation.requirements.unmet} unmet requirements
          {validation.issues.slice(0, 20).map((i, n) => (
            <div key={n} style={ROW}><strong>{i.type.replace(/_/g, ' ')}</strong>: {i.sentence}</div>
          ))}
          {validation.missing_placeholders.map((m, n) => <div key={`m${n}`} style={MUTED}>missing: {m}</div>)}
        </div>
      )}
    </div>
  );
};

// --- browser --------------------------------------------------------------------

const BrowserView: React.FC<{ project: string }> = ({ project }) => {
  const [status, setStatus] = React.useState<BrowserStatus>({ state: 'stopped' });
  const [mode, setMode] = React.useState('research');
  const [origins, setOrigins] = React.useState('');
  const [url, setUrl] = React.useState('');
  const [selector, setSelector] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const refresh = React.useCallback(() => projectsApi.browser(project).then(setStatus).catch(() => undefined), [project]);
  React.useEffect(() => { refresh(); }, [refresh]);
  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try { await fn(); } catch (err) { setError(err instanceof Error ? err.message : 'Browser action failed'); }
    await refresh();
  };
  const list = origins.split(/[\s,]+/).filter(Boolean);
  const running = status.state !== 'stopped';
  return (
    <div>
      <div style={MUTED}>
        Optional. A separate, visible browser profile; never your everyday browser. Research and observe modes are
        read-only (other requests are blocked in the network layer). Interactive mode asks before every change and
        never submits graded work.
      </div>
      {!running ? (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
          <select className="form-select" style={{ width: 'auto' }} value={mode} onChange={(e) => setMode(e.target.value)} aria-label="Browser mode">
            <option value="research">Research (read-only)</option>
            <option value="observe">Observe lab (read-only)</option>
            <option value="interactive">Interactive lab (approve each change)</option>
          </select>
          <input className="form-input" style={{ flex: 1, minWidth: 220 }} value={origins} onChange={(e) => setOrigins(e.target.value)}
            placeholder="approved origins, e.g. https://docs.suricata.io" aria-label="Approved origins" />
          <button type="button" className="btn-tech btn-tech-primary" disabled={!list.length}
            onClick={() => run(() => projectsApi.browserStart(project, {
              mode, allowed_origins: mode === 'interactive' ? [] : list, interactive_origins: mode === 'interactive' ? list : [],
            }))}>
            <Globe size={14} /> Start
          </button>
        </div>
      ) : (
        <div style={{ marginTop: 8 }}>
          <div>
            <Chip value={status.state} /> <strong>{status.policy?.mode}</strong> on{' '}
            {[...(status.policy?.allowed_origins || []), ...(status.policy?.interactive_origins || [])].join(', ')}
            {status.url && <span style={MUTED}> · at {status.url}</span>}
          </div>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 6 }}>
            <button type="button" className="btn-tech" onClick={() => run(() => projectsApi.browserVerb(project, status.state === 'paused' ? 'resume' : 'pause'))}>
              {status.state === 'paused' ? 'Resume' : 'Pause'}
            </button>
            {status.policy?.mode === 'interactive' && (
              <button type="button" className="btn-tech" onClick={() => run(() => projectsApi.browserVerb(project, 'read-only'))}>Switch to read-only</button>
            )}
            <button type="button" className="btn-tech" onClick={() => run(() => projectsApi.browserStop(project))}>Stop</button>
          </div>
          <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            <input className="form-input" style={{ flex: 1 }} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" aria-label="URL" />
            <button type="button" className="btn-tech" onClick={() => run(() => projectsApi.browserNavigate(project, url))}>Go</button>
            <button type="button" className="btn-tech" onClick={() => run(() => projectsApi.browserVerb(project, 'read'))}>Capture page text</button>
            <button type="button" className="btn-tech" onClick={() => run(() => projectsApi.browserScreenshot(project, 'page'))}>Screenshot</button>
          </div>
          {status.policy?.mode === 'interactive' && (
            <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
              <input className="form-input" style={{ flex: 1 }} value={selector} onChange={(e) => setSelector(e.target.value)}
                placeholder="CSS selector of a control, e.g. #run" aria-label="Selector" />
              <button type="button" className="btn-tech" onClick={() => run(() => projectsApi.browserRequest(project, 'click', selector))}>Request click</button>
            </div>
          )}
          {(status.pending || []).map((a) => (
            <div key={a.action_id} style={{ ...ROW, background: 'rgba(255,200,0,0.08)' }}>
              Pending: <strong>{a.kind}</strong> {a.target} on {a.url}
              <button type="button" className="btn-tech btn-tech-primary" style={{ marginLeft: 6 }}
                onClick={() => run(() => projectsApi.browserDecide(project, a.action_id, 'approve'))}>Approve</button>
              <button type="button" className="btn-tech" style={{ marginLeft: 4 }}
                onClick={() => run(() => projectsApi.browserDecide(project, a.action_id, 'deny'))}>Deny</button>
            </div>
          ))}
        </div>
      )}
      {error && <div className="chip chip-fail" style={{ marginTop: 6 }}>{error}</div>}
      {(status.blocked || []).slice(-5).map((b, n) => (
        <div key={n} style={MUTED}>blocked {b.method} {b.url} ({b.reason})</div>
      ))}
      <h4 style={{ fontSize: 12, marginBottom: 4 }}>Recent actions</h4>
      {(status.recent_actions || []).slice().reverse().map((a) => (
        <div key={a.action_id + a.requested_at} style={ROW}>
          {a.requested_at.slice(11, 19)} <Chip value={a.outcome || a.decision} /> {a.mode} {a.kind} {a.target} {a.url}
          {a.changed_state && <span className="chip chip-warn" style={{ marginLeft: 4 }}>changed state</span>}
          {a.error && <span style={MUTED}> · {a.error}</span>}
        </div>
      ))}
    </div>
  );
};

// --- panel ----------------------------------------------------------------------

export const ProjectsPanel: React.FC = () => {
  const [projects, setProjects] = React.useState<ProjectSummary[]>([]);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [view, setView] = React.useState<View>('sources');
  const [coverage, setCoverage] = React.useState<Coverage | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [scanOptions, setScanOptions] = React.useState({ transcribe: true, frames: true, ocr: true });

  const load = React.useCallback(async () => {
    try {
      const list = await projectsApi.list();
      setProjects(list);
      setSelected((current) => current || list[0]?.project_id || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load projects');
    }
  }, []);
  React.useEffect(() => { load(); }, [load]);
  const reloadCoverage = React.useCallback(() => {
    if (selected) projectsApi.requirements(selected).then(setCoverage).catch(() => undefined);
  }, [selected]);
  React.useEffect(() => { reloadCoverage(); }, [reloadCoverage]);

  const summary = projects.find((p) => p.project_id === selected) || null;
  const scan = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const done = await waitForJob(await projectsApi.scan(selected, scanOptions));
      if (done.status === 'FAILED') setError(done.error_message || 'Scan failed');
      await load();
      reloadCoverage();
    } finally {
      setBusy(false);
    }
  };

  const tabs: Array<{ id: View; label: string; icon: React.ReactNode }> = [
    { id: 'sources', label: `Sources${summary ? ` (${summary.sources})` : ''}`, icon: <FolderOpen size={14} /> },
    { id: 'evidence', label: `Evidence${summary ? ` (${summary.evidence})` : ''}`, icon: <Library size={14} /> },
    { id: 'requirements', label: `Requirements${coverage ? ` (${coverage.unmet} open)` : ''}`, icon: <CheckSquare size={14} /> },
    { id: 'write', label: 'Write', icon: <PenLine size={14} /> },
    { id: 'browser', label: 'Browser', icon: <Globe size={14} /> },
  ];

  return (
    <div className="tech-panel" style={{ height: '100%', overflowY: 'auto' }}>
      <div className="tech-header">
        <h3><Library size={16} /> PROJECTS</h3>
        {projects.length > 0 && (
          <select className="form-select" style={{ width: 'auto' }} value={selected || ''} onChange={(e) => setSelected(e.target.value)} aria-label="Project">
            {projects.map((p) => <option key={p.project_id} value={p.project_id}>{p.name}</option>)}
          </select>
        )}
      </div>
      <div style={{ padding: 12 }}>
        <OpenProject onOpened={(p) => { setSelected(p.project_id); load(); }} />
        {error && <div className="chip chip-fail" style={{ marginTop: 6 }}>{error}</div>}
        {summary && (
          <>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', margin: '10px 0' }}>
              <span style={MUTED}>{summary.root}</span>
              <span style={MUTED}>scan: {summary.scan_state.status || 'never'}</span>
              {(['ocr', 'frames', 'transcribe'] as const).map((k) => (
                <label key={k} style={{ fontSize: 11 }}>
                  <input type="checkbox" checked={scanOptions[k]} onChange={(e) => setScanOptions({ ...scanOptions, [k]: e.target.checked })} /> {k}
                </label>
              ))}
              <button type="button" className="btn-tech" onClick={scan} disabled={busy}>{busy ? 'Scanning…' : 'Scan / rescan'}</button>
            </div>
            <div className="nav-tabs" style={{ display: 'flex', gap: 4, marginBottom: 8, flexWrap: 'wrap' }}>
              {tabs.map((t) => (
                <button key={t.id} type="button" className={`nav-tab ${view === t.id ? 'active' : ''}`} onClick={() => setView(t.id)}>
                  {t.icon} <span>{t.label}</span>
                </button>
              ))}
            </div>
            {view === 'sources' && <SourcesView project={summary.project_id} onChanged={() => { load(); reloadCoverage(); }} />}
            {view === 'evidence' && <EvidenceView project={summary.project_id} />}
            {view === 'requirements' && <RequirementsView project={summary.project_id} coverage={coverage} reload={reloadCoverage} />}
            {view === 'write' && <WriteView project={summary.project_id} summary={summary} />}
            {view === 'browser' && <BrowserView project={summary.project_id} />}
          </>
        )}
      </div>
    </div>
  );
};
