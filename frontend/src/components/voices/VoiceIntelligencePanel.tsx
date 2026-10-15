import React from 'react';
import { Fingerprint, Gauge, HardDrive, ListChecks, RefreshCw, ShieldCheck, UserCheck } from 'lucide-react';
import { api } from '../../api/client';
import {
  JobResponse,
  NaturalnessReport,
  PersonalComparison,
  PersonalEvaluation,
  VoiceIntelReviewItem,
  VoiceIntelStatus,
  VoiceMatchReport,
} from '../../types';

/**
 * Voice Intelligence: corpus status, authorship review, context profiles,
 * and the two calibrated scores.
 *
 * What this panel will not do, by design:
 *  - choose new folders to read (that stays at the command line);
 *  - show a number the evidence does not support (an unavailable score is
 *    shown as unavailable, with the reason);
 *  - show document text unless the person asks for one document's preview.
 */

type View = 'corpus' | 'review' | 'profiles' | 'evaluate';

const AUTHORSHIP_CHOICES: Array<{ value: string; label: string; hint: string }> = [
  { value: 'CONFIRMED_HUMAN_AUTHORED', label: 'My writing', hint: 'Written by me without substantial AI drafting' },
  { value: 'HUMAN_AUTHORED_LIGHT_AI_EDITING', label: 'Mine, light AI edits', hint: 'My writing; AI only polished wording (half weight)' },
  { value: 'MIXED_AUTHORSHIP', label: 'Mixed', hint: 'Partly mine: choose my paragraphs' },
  { value: 'SUBSTANTIALLY_AI_GENERATED', label: 'Mostly AI', hint: 'Mostly AI-drafted; never used as my voice' },
  { value: 'THIRD_PARTY', label: "Someone else's", hint: 'Written by another person' },
  { value: 'UNKNOWN_AUTHORSHIP', label: 'Not sure', hint: 'Keep it out of the profiles' },
];

const STATUS_CHIP: Record<string, string> = {
  VALIDATED: 'chip-pass',
  CALIBRATED_UNVALIDATED: 'chip-warn',
  UNVALIDATED: 'chip-warn',
  INSUFFICIENT: 'chip-neutral',
  NOT_CALIBRATED: 'chip-neutral',
  WITHIN_RANGE: 'chip-pass',
  EDGE_OF_RANGE: 'chip-warn',
  ATYPICAL: 'chip-fail',
  SUBSTANCE_PRESERVED: 'chip-pass',
  REVISION_CHANGES_SUBSTANCE: 'chip-fail',
  PASS: 'chip-pass',
  FLAGGED: 'chip-fail',
  FACTUALLY_PRESERVED: 'chip-pass',
  PRESERVED: 'chip-pass',
  CHANGED: 'chip-fail',
};

function words(text: string): string {
  return text.replace(/_/g, ' ');
}

function Chip({ value }: { value: string }) {
  return <span className={`chip ${STATUS_CHIP[value] || 'chip-neutral'}`}>{words(value)}</span>;
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ border: '1px solid var(--border-medium, #ccc)', padding: '8px 10px', minWidth: 0 }}>
      <div style={{ fontSize: '11px', opacity: 0.7 }}>{label}</div>
      <div style={{ fontSize: '18px', fontWeight: 600 }}>{value}</div>
    </div>
  );
}

const GRID: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
  gap: '8px',
  marginBottom: '14px',
};

async function waitForJob(job: JobResponse): Promise<JobResponse> {
  let current = job;
  while (current.status === 'QUEUED' || current.status === 'RUNNING') {
    await new Promise((resolve) => setTimeout(resolve, 800));
    current = await api.getJobStatus(current.job_id);
  }
  return current;
}

// --- Corpus ----------------------------------------------------------------

const CorpusView: React.FC<{ status: VoiceIntelStatus; onRescan: () => void; busy: boolean }> = ({
  status,
  onRescan,
  busy,
}) => {
  const scan = status.scan || {};
  const mount = status.mounts[0];
  const coverage = scan.coverage || {};
  return (
    <div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
        <span>
          <HardDrive size={14} style={{ verticalAlign: 'middle' }} /> Drive:{' '}
          {mount ? (mount.root_exists && mount.listable ? <Chip value="PASS" /> : <span className="chip chip-fail">unavailable</span>) : 'not configured'}
          {mount?.filesystem && <span style={{ fontSize: 11, opacity: 0.7, marginLeft: 6 }}>{mount.filesystem}</span>}
        </span>
        <button type="button" className="btn-tech" onClick={onRescan} disabled={busy}>
          <RefreshCw size={14} /> {busy ? 'Scanning…' : 'Rescan configured sources'}
        </button>
      </div>
      {mount?.error && <p style={{ color: 'var(--color-red)', fontSize: 12 }}>{mount.error}</p>}
      <p style={{ fontSize: 12, opacity: 0.8 }}>
        Never entered: {status.exclusions.length ? status.exclusions.join(', ') : 'no exclusions configured'}
        {scan.walk ? ` (${scan.walk.excluded_directories_skipped} directories skipped)` : ''}
      </p>
      {scan.files_inventoried === undefined ? (
        <p style={{ fontSize: 12 }}>Not scanned yet.</p>
      ) : (
        <>
          <div style={GRID}>
            <Stat label="Files discovered" value={scan.files_inventoried} />
            <Stat label="Eligible prose files" value={scan.eligible_prose_files} />
            <Stat label="Read successfully" value={scan.readable_documents} />
            <Stat label="Academic candidates" value={scan.academic_candidates} />
            <Stat label="Professional candidates" value={scan.professional_candidates} />
            <Stat label="Pending reviews" value={scan.pending_reviews} />
            <Stat label="Native docs not readable" value={scan.native_cloud_unavailable} />
            <Stat label="Unreadable / failed" value={scan.unreadable_or_failed} />
          </div>
          <p style={{ fontSize: 12 }}>
            Content coverage: <strong>{Math.round((coverage.content_read_share_of_eligible || 0) * 100)}%</strong> of eligible
            files{coverage.complete ? '' : ' (incomplete)'}. {coverage.note}
          </p>
          <p style={{ fontSize: 11, opacity: 0.7 }}>Last scan: {scan.scanned_at}</p>
          {scan.categories && (
            <details>
              <summary style={{ fontSize: 12, cursor: 'pointer' }}>Document categories</summary>
              <ul style={{ fontSize: 12 }}>
                {Object.entries(scan.categories as Record<string, number>).map(([k, v]) => (
                  <li key={k}>
                    {words(k)}: {v}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
};

// --- Review ----------------------------------------------------------------

const ReviewView: React.FC<{ identity: string; onChanged: () => void }> = ({ identity, onChanged }) => {
  const [items, setItems] = React.useState<VoiceIntelReviewItem[]>([]);
  const [preview, setPreview] = React.useState<Record<string, string[]>>({});
  const [paragraphs, setParagraphs] = React.useState<Record<string, string>>({});
  const [message, setMessage] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    const data = await api.getReviewQueue(identity);
    setItems(data.pending);
  }, [identity]);

  React.useEffect(() => {
    load().catch((err) => setMessage(err instanceof Error ? err.message : 'Failed to load review queue'));
  }, [load]);

  const decide = async (item: VoiceIntelReviewItem, authorship: string) => {
    try {
      await api.attest(identity, item.doc_id, {
        authorship,
        include_paragraphs: authorship === 'MIXED_AUTHORSHIP' ? paragraphs[item.doc_id] || '' : '',
      });
      setMessage(`Recorded: ${item.title} → ${words(authorship)}`);
      await load();
      onChanged();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Could not record decision');
    }
  };

  const showPreview = async (item: VoiceIntelReviewItem) => {
    const data = await api.previewDocument(identity, item.doc_id);
    setPreview((prev) => ({ ...prev, [item.doc_id]: data.paragraphs }));
  };

  return (
    <div>
      <p style={{ fontSize: 12, opacity: 0.85 }}>
        Only documents that would shape a profile are listed. Nothing here becomes part of a profile until you
        decide. A proposal is a guess from metadata and content; only you can confirm authorship.
      </p>
      <div aria-live="polite" style={{ fontSize: 12, minHeight: 18 }}>
        {message}
      </div>
      {items.length === 0 && <p style={{ fontSize: 12 }}>Nothing awaits review.</p>}
      {items.map((item) => (
        <article
          key={item.doc_id}
          style={{ border: '1px solid var(--border-medium, #ccc)', padding: 10, marginBottom: 10 }}
          aria-label={`Review ${item.title}`}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
            <strong style={{ wordBreak: 'break-word' }}>{item.title}</strong>
            <span style={{ fontSize: 11, opacity: 0.75 }}>
              {words(item.category)} · {item.words} words · {item.paragraphs} paragraphs
              {item.reopened && <span className="chip chip-warn" style={{ marginLeft: 6 }}>reopened</span>}
            </span>
          </div>
          <div style={{ fontSize: 12, margin: '6px 0' }}>
            Proposed: <Chip value={item.proposed} />
          </div>
          <ul style={{ fontSize: 12, margin: '4px 0 8px 16px' }}>
            {item.reasons.slice(0, 4).map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
            {item.style_signals.map((signal) => (
              <li key={signal} style={{ opacity: 0.75 }}>
                {signal}
              </li>
            ))}
          </ul>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }} role="group" aria-label="Authorship decision">
            {AUTHORSHIP_CHOICES.map((choice) => (
              <button
                key={choice.value}
                type="button"
                className="btn-tech"
                title={choice.hint}
                onClick={() => decide(item, choice.value)}
              >
                {choice.label}
              </button>
            ))}
            <button type="button" className="btn-tech" onClick={() => showPreview(item)}>
              Preview
            </button>
          </div>
          <label style={{ display: 'block', fontSize: 11, marginTop: 6 }}>
            Your paragraphs, if mixed (e.g. 1-4,7):{' '}
            <input
              className="form-input"
              style={{ width: 120, display: 'inline-block' }}
              value={paragraphs[item.doc_id] || ''}
              onChange={(event) => setParagraphs((prev) => ({ ...prev, [item.doc_id]: event.target.value }))}
            />
          </label>
          {preview[item.doc_id] && (
            <div
              style={{ fontSize: 11, maxHeight: 220, overflowY: 'auto', marginTop: 8, background: 'var(--bg-sunken)', padding: 8 }}
            >
              {preview[item.doc_id].map((line) => (
                <p key={line.slice(0, 40)} style={{ margin: '0 0 6px' }}>
                  {line}
                </p>
              ))}
            </div>
          )}
        </article>
      ))}
    </div>
  );
};

// --- Profiles --------------------------------------------------------------

const ProfilesView: React.FC<{ status: VoiceIntelStatus; onBuild: () => void; busy: boolean }> = ({
  status,
  onBuild,
  busy,
}) => (
  <div>
    <button type="button" className="btn-tech" onClick={onBuild} disabled={busy} style={{ marginBottom: 10 }}>
      <RefreshCw size={14} /> {busy ? 'Building…' : 'Build profiles from attested documents'}
    </button>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
      {status.profiles.map((profile) => (
        <section key={profile.voice} style={{ border: '1px solid var(--border-medium, #ccc)', padding: 10 }}>
          <h4 style={{ margin: '0 0 6px' }}>
            {status.display_name || status.identity} — {words(profile.profile)}
          </h4>
          <div style={{ fontSize: 11, opacity: 0.7, marginBottom: 6 }}>{profile.voice}</div>
          {profile.state !== 'BUILT' ? (
            <p style={{ fontSize: 12 }}>
              Not built yet. Attest documents in Review, then build. A profile needs at least three of your own
              documents.
            </p>
          ) : (
            <>
              <table style={{ fontSize: 12, width: '100%' }}>
                <tbody>
                  <tr><td>Training / holdout</td><td>{profile.training_documents} / {profile.holdout_documents}</td></tr>
                  <tr><td>Words</td><td>{(profile.training_words || 0).toLocaleString()}</td></tr>
                  <tr><td>Sufficiency</td><td>{(profile.sufficiency || '').toUpperCase()}</td></tr>
                  <tr><td>Profile confidence</td><td>{profile.confidence}</td></tr>
                  <tr><td>Voice Match</td><td><Chip value={profile.voice_match?.status || 'NOT_CALIBRATED'} /> ({profile.voice_match?.genuine_documents} calibration docs)</td></tr>
                  <tr><td>Discrimination</td><td>{profile.voice_match?.auc != null ? `AUC ${profile.voice_match.auc} (${profile.voice_match.controls} comparison docs)` : 'not tested'}</td></tr>
                  <tr><td>Drift baseline</td><td>{profile.drift_windows} passages</td></tr>
                  <tr><td>Last build</td><td>{profile.built_at}</td></tr>
                </tbody>
              </table>
              {profile.characteristics && profile.characteristics.length > 0 && (
                <>
                  <div style={{ fontSize: 12, marginTop: 8, fontWeight: 600 }}>Characteristics</div>
                  <ul style={{ fontSize: 12, margin: '4px 0 0 16px' }}>
                    {profile.characteristics.map((c) => (
                      <li key={c.name}>
                        {words(c.name)}: <strong>{words(c.value)}</strong>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </section>
      ))}
    </div>
  </div>
);

// --- Evaluate --------------------------------------------------------------

const ScoreCard: React.FC<{ title: string; report: NaturalnessReport | VoiceMatchReport; band?: string }> = ({
  title,
  report,
  band,
}) => (
  <section
    style={{ border: '1px solid var(--border-medium, #ccc)', padding: 12, minWidth: 0 }}
    aria-label={title}
  >
    <div style={{ fontSize: 12, opacity: 0.75 }}>{title}</div>
    {report.status === 'SCORED' && report.score !== null ? (
      <>
        <div style={{ fontSize: 32, fontWeight: 700 }}>
          {report.score.toFixed(0)}
          <span style={{ fontSize: 14, opacity: 0.6 }}> / 100</span>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {band && <Chip value={band} />}
          <Chip value={report.confidence} />
        </div>
        <p style={{ fontSize: 11, opacity: 0.8 }}>{report.confidence_basis}</p>
      </>
    ) : (
      <>
        <div style={{ fontSize: 20, fontWeight: 600, opacity: 0.6 }}>Unavailable</div>
        <p style={{ fontSize: 12 }}>{report.reason}</p>
      </>
    )}
    <p style={{ fontSize: 10, opacity: 0.65 }}>{report.disclaimer}</p>
  </section>
);

const EvaluationResult: React.FC<{ result: PersonalEvaluation; name: string }> = ({ result, name }) => (
  <div>
    <p style={{ fontSize: 12 }}>
      Profile: <strong>{result.profile_selection.voice || 'none'}</strong> — {result.profile_selection.reason}
    </p>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10 }}>
      <ScoreCard title="Human Naturalness" report={result.naturalness} />
      <ScoreCard title={`${name} Voice Match`} report={result.voice_match} band={result.voice_match.band} />
    </div>
    <p style={{ fontSize: 11, opacity: 0.75 }}>{result.independence_note}</p>
    {result.naturalness.dimensions.length > 0 && (
      <details open>
        <summary style={{ fontSize: 12, cursor: 'pointer' }}>Naturalness by dimension</summary>
        <table style={{ fontSize: 12, width: '100%' }}>
          <tbody>
            {result.naturalness.dimensions.map((d) => (
              <tr key={d.name}>
                <td>{d.label}</td>
                <td style={{ width: '45%' }}>
                  {d.score === null ? (
                    'n/a'
                  ) : (
                    <div
                      role="meter"
                      aria-valuenow={Math.round(d.score)}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-label={d.label}
                      style={{ background: 'var(--bg-sunken)', height: 8 }}
                    >
                      <div style={{ width: `${d.score}%`, height: 8, background: 'var(--color-cyan)' }} />
                    </div>
                  )}
                </td>
                <td style={{ textAlign: 'right' }}>{d.score === null ? '' : d.score.toFixed(0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    )}
    {result.naturalness.weaknesses.length > 0 && (
      <>
        <h4 style={{ marginBottom: 4 }}>What reads mechanical</h4>
        <ul style={{ fontSize: 12 }}>
          {result.naturalness.weaknesses.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
        <h4 style={{ marginBottom: 4 }}>Suggestions (nothing was rewritten)</h4>
        <ul style={{ fontSize: 12 }}>
          {Array.from(new Set(result.naturalness.suggestions)).map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      </>
    )}
    {result.voice_match.differences.length > 0 && (
      <>
        <h4 style={{ marginBottom: 4 }}>Differences from {name}'s profile</h4>
        <ul style={{ fontSize: 12 }}>
          {result.voice_match.differences.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      </>
    )}
    <h4 style={{ marginBottom: 4 }}>Voice drift</h4>
    {result.drift.findings.length === 0 ? (
      <p style={{ fontSize: 12 }}>{result.drift.status === 'UNAVAILABLE' ? `Unavailable: ${result.drift.reason}` : 'No passages stand out.'}</p>
    ) : (
      <ul style={{ fontSize: 12 }}>
        {result.drift.findings.map((f) => (
          <li key={`${f.span}-${f.metric}`}>
            <strong>{f.span}</strong> {f.message} <span style={{ opacity: 0.7 }}>({f.severity}, {f.confidence} confidence)</span>
            {f.suggestion && <div style={{ opacity: 0.8 }}>{f.suggestion}</div>}
          </li>
        ))}
      </ul>
    )}
    {result.drift.note && <p style={{ fontSize: 11, opacity: 0.7 }}>{result.drift.note}</p>}
  </div>
);

const ComparisonResult: React.FC<{ result: PersonalComparison; name: string }> = ({ result, name }) => {
  const fmt = (v: number | null) => (v === null ? 'n/a' : v.toFixed(0));
  const delta = (v: number | null) => (v === null ? '' : `${v > 0 ? '+' : ''}${v.toFixed(0)}`);
  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        Verdict: <Chip value={result.verdict} />
      </div>
      <table style={{ fontSize: 13, width: '100%', marginBottom: 10 }}>
        <thead>
          <tr><th style={{ textAlign: 'left' }}>Score</th><th>Original</th><th>Revised</th><th>Change</th></tr>
        </thead>
        <tbody>
          <tr><td>Human Naturalness</td><td>{fmt(result.naturalness.original)}</td><td>{fmt(result.naturalness.revised)}</td><td>{delta(result.naturalness.delta)}</td></tr>
          <tr><td>{name} Voice Match</td><td>{fmt(result.voice_match.original)}</td><td>{fmt(result.voice_match.revised)}</td><td>{delta(result.voice_match.delta)}</td></tr>
        </tbody>
      </table>
      <table style={{ fontSize: 12, width: '100%' }}>
        <tbody>
          <tr><td>Meaning preservation</td><td><Chip value={result.meaning_preservation.status} /></td></tr>
          <tr><td>Factual integrity</td><td><Chip value={result.factual_integrity.status} /></td></tr>
          <tr><td>Citations</td><td><Chip value={result.citations.status} /></td></tr>
          <tr><td>Requirements</td><td>{words(result.requirements.status)}</td></tr>
        </tbody>
      </table>
      {result.integrity_problems.length > 0 && (
        <ul style={{ fontSize: 12, color: 'var(--color-red)' }}>
          {result.integrity_problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      {result.changed_dimensions.length > 0 && (
        <>
          <h4 style={{ marginBottom: 4 }}>Changed dimensions</h4>
          <ul style={{ fontSize: 12 }}>
            {result.changed_dimensions.map((c) => (
              <li key={`${c.family}-${c.dimension}`}>
                {c.label} ({words(c.family)}): {c.delta !== undefined ? delta(c.delta) : c.direction}
              </li>
            ))}
          </ul>
        </>
      )}
      <p style={{ fontSize: 11, opacity: 0.75 }}>{result.policy}</p>
    </div>
  );
};

const EvaluateView: React.FC<{ identity: string; name: string }> = ({ identity, name }) => {
  const [text, setText] = React.useState('');
  const [revised, setRevised] = React.useState('');
  const [mode, setMode] = React.useState('');
  const [compare, setCompare] = React.useState(false);
  const [result, setResult] = React.useState<PersonalEvaluation | null>(null);
  const [comparison, setComparison] = React.useState<PersonalComparison | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const options = { mode: mode || null, identity, auto_voice: !mode };
      if (compare) {
        setResult(null);
        setComparison(await api.comparePersonal({ original: text, revised, ...options }));
      } else {
        setComparison(null);
        setResult(await api.evaluatePersonal({ text, ...options }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Evaluation failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
        <label style={{ fontSize: 12 }}>
          Mode{' '}
          <select className="form-select" value={mode} onChange={(e) => setMode(e.target.value)} style={{ width: 'auto', display: 'inline-block' }}>
            <option value="">Automatic (from content)</option>
            <option value="academic">Academic</option>
            <option value="professional">Professional</option>
            <option value="linkedin">LinkedIn</option>
            <option value="technical">Technical</option>
            <option value="documentation">Documentation</option>
          </select>
        </label>
        <label style={{ fontSize: 12 }}>
          <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} /> Compare with a revision
        </label>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: compare ? 'repeat(auto-fit, minmax(260px, 1fr))' : '1fr', gap: 8 }}>
        <label style={{ fontSize: 12 }}>
          {compare ? 'Original' : 'Document'}
          <textarea className="form-textarea" rows={10} value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        {compare && (
          <label style={{ fontSize: 12 }}>
            Revision
            <textarea className="form-textarea" rows={10} value={revised} onChange={(e) => setRevised(e.target.value)} />
          </label>
        )}
      </div>
      <button
        type="button"
        className="btn-tech btn-tech-primary"
        onClick={run}
        disabled={busy || !text.trim() || (compare && !revised.trim())}
        style={{ margin: '8px 0' }}
      >
        <Gauge size={14} /> {busy ? 'Evaluating…' : compare ? 'Compare' : 'Evaluate'}
      </button>
      <p style={{ fontSize: 11, opacity: 0.7 }}>Runs locally and deterministically. No model is called and nothing is rewritten.</p>
      {error && <p style={{ color: 'var(--color-red)', fontSize: 12 }}>{error}</p>}
      <div aria-live="polite">
        {result && <EvaluationResult result={result} name={name} />}
        {comparison && <ComparisonResult result={comparison} name={name} />}
      </div>
    </div>
  );
};

// --- Panel -----------------------------------------------------------------

export const VoiceIntelligencePanel: React.FC = () => {
  const [identities, setIdentities] = React.useState<string[]>([]);
  const [identity, setIdentity] = React.useState<string | null>(null);
  const [status, setStatus] = React.useState<VoiceIntelStatus | null>(null);
  const [view, setView] = React.useState<View>('corpus');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    api
      .listIdentities()
      .then((data) => {
        setIdentities(data.identities);
        setIdentity(data.preferred_identity && data.identities.includes(data.preferred_identity) ? data.preferred_identity : data.identities[0] || null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load identities'));
  }, []);

  const refresh = React.useCallback(async () => {
    if (!identity) return;
    try {
      setStatus(await api.getIdentityStatus(identity));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load status');
    }
  }, [identity]);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const runJob = async (kind: 'scan' | 'build') => {
    if (!identity) return;
    setBusy(true);
    setError(null);
    try {
      const done = await waitForJob(await api.startIdentityJob(identity, kind));
      if (done.status === 'FAILED') setError(done.error_message || `${kind} failed`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : `${kind} failed`);
    } finally {
      setBusy(false);
    }
  };

  const name = status?.display_name ? status.display_name.split(' ')[0] : identity || 'Personal';
  const tabs: Array<{ id: View; label: string; icon: React.ReactNode }> = [
    { id: 'corpus', label: 'Corpus', icon: <HardDrive size={14} /> },
    { id: 'review', label: `Review${status ? ` (${status.review.pending})` : ''}`, icon: <ListChecks size={14} /> },
    { id: 'profiles', label: 'Profiles', icon: <UserCheck size={14} /> },
    { id: 'evaluate', label: 'Evaluate', icon: <Gauge size={14} /> },
  ];

  return (
    <div className="tech-panel" style={{ height: '100%', overflowY: 'auto' }}>
      <div className="tech-header">
        <h3>
          <Fingerprint size={16} /> VOICE INTELLIGENCE
        </h3>
        {identities.length > 1 && (
          <select className="form-select" value={identity || ''} onChange={(e) => setIdentity(e.target.value)} aria-label="Identity" style={{ width: 'auto' }}>
            {identities.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        )}
      </div>
      <div style={{ padding: 12 }}>
        <p style={{ fontSize: 12, opacity: 0.75, marginTop: 0 }}>
          <ShieldCheck size={12} style={{ verticalAlign: 'middle' }} /> Private local data. Scores are calibrated against
          your own attested writing and are withheld when the evidence cannot support a number.
        </p>
        {error && <p style={{ color: 'var(--color-red)', fontSize: 12 }}>{error}</p>}
        {!identity ? (
          <p style={{ fontSize: 12 }}>
            No identity has been scanned yet. Start from the command line:{' '}
            <code>howlwriter voice scan --identity NAME --source /path/to/drive</code>
          </p>
        ) : (
          <>
            <nav style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }} aria-label="Voice Intelligence sections">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  className={`nav-tab ${view === tab.id ? 'active' : ''}`}
                  aria-pressed={view === tab.id}
                  onClick={() => setView(tab.id)}
                >
                  {tab.icon} <span>{tab.label}</span>
                </button>
              ))}
            </nav>
            {status && view === 'corpus' && <CorpusView status={status} onRescan={() => runJob('scan')} busy={busy} />}
            {view === 'review' && <ReviewView identity={identity} onChanged={refresh} />}
            {status && view === 'profiles' && <ProfilesView status={status} onBuild={() => runJob('build')} busy={busy} />}
            {view === 'evaluate' && <EvaluateView identity={identity} name={name} />}
          </>
        )}
      </div>
    </div>
  );
};
