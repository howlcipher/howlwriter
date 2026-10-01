import React from 'react';
import { Mic, RefreshCw, ShieldCheck } from 'lucide-react';
import { JobResponse, VoiceDetail, VoiceSummary } from '../../types';
import { api } from '../../api/client';

/**
 * Local personal voices, shown as summaries.
 *
 * Deliberately read-only apart from rebuild. Building a voice means choosing
 * which directories on this machine to read, which is a decision that belongs
 * at the command line where the user can see exactly what they are pointing
 * at -- not behind a button in a browser tab.
 *
 * Nothing here renders a corpus passage or a file path. The API will not send
 * either to this endpoint, and this panel does not ask for the separate,
 * explicitly-confirmed source listing.
 */

const BAND_COLORS: Record<string, string> = {
  HIGH: 'var(--status-ok, #2e7d32)',
  MEDIUM: 'var(--status-warn, #ed6c02)',
  LOW: 'var(--status-muted, #757575)',
  VERY_LOW: 'var(--status-muted, #757575)',
  UNKNOWN: 'var(--status-muted, #757575)',
};

const ALIGNMENT_COLORS: Record<string, string> = {
  STRONG: 'var(--status-ok, #2e7d32)',
  MODERATE: 'var(--status-warn, #ed6c02)',
  WEAK: 'var(--status-error, #c62828)',
  NOT_EVALUATED: 'var(--status-muted, #757575)',
};

function humanize(text: string): string {
  return text.replace(/_/g, ' ');
}

export const VoicesPanel: React.FC = () => {
  const [voices, setVoices] = React.useState<VoiceSummary[]>([]);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [detail, setDetail] = React.useState<VoiceDetail | null>(null);
  const [isLoading, setIsLoading] = React.useState(false);
  const [job, setJob] = React.useState<JobResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const fetchVoices = React.useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.listVoices();
      setVoices(data);
      if (data.length > 0 && selected === null) {
        setSelected(data[0].name);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load voices');
    } finally {
      setIsLoading(false);
    }
  }, [selected]);

  React.useEffect(() => {
    fetchVoices();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    api
      .getVoice(selected)
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load voice');
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  // Rebuild runs on the same background-job machinery the academic pipeline
  // uses, so progress is reported through the existing stage rail rather than
  // a second progress mechanism.
  const rebuild = async () => {
    if (!selected) return;
    setError(null);
    try {
      let current = await api.rebuildVoice(selected, { reuse_cache: true });
      setJob(current);
      while (current.status === 'QUEUED' || current.status === 'RUNNING') {
        await new Promise((resolve) => setTimeout(resolve, 500));
        current = await api.getJobStatus(current.job_id);
        setJob(current);
      }
      if (current.status === 'FAILED') {
        setError(current.error_message || 'Rebuild failed');
      } else {
        await fetchVoices();
        setDetail(await api.getVoice(selected));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Rebuild failed');
    }
  };

  const isRunning = job?.status === 'QUEUED' || job?.status === 'RUNNING';

  return (
    <div className="tech-panel" style={{ height: '100%', overflowY: 'auto' }}>
      <div className="tech-header">
        <h3>
          <Mic size={16} /> PERSONAL VOICES (~/.howlwriter/voices/)
        </h3>
        <button type="button" className="btn-tech" onClick={fetchVoices} disabled={isLoading}>
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      <div style={{ padding: '12px' }}>
        <p style={{ fontSize: '12px', opacity: 0.75, marginTop: 0 }}>
          <ShieldCheck size={12} style={{ verticalAlign: 'middle' }} /> These profiles are
          private local data derived from your own writing. They hold tendencies and
          distributions, never passages from your documents, and they are not tracked by Git.
        </p>

        {error && (
          <p style={{ color: 'var(--status-error, #c62828)', fontSize: '12px' }}>{error}</p>
        )}

        {voices.length === 0 && !isLoading && (
          <p style={{ fontSize: '12px' }}>
            No local voices yet. Build one from the command line:{' '}
            <code>howlwriter voice build --name jane --source /path/to/writing</code>
          </p>
        )}

        {voices.length > 0 && (
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '14px' }}>
            {voices.map((voice) => (
              <button
                key={voice.name}
                type="button"
                className={`nav-tab ${selected === voice.name ? 'active' : ''}`}
                onClick={() => setSelected(voice.name)}
              >
                {voice.name}
                <span style={{ opacity: 0.6, marginLeft: 6, fontSize: '11px' }}>
                  {voice.profile_type === 'shared_style' ? 'shared style' : 'personal'}
                </span>
              </button>
            ))}
          </div>
        )}

        {detail && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: 10 }}>
              <strong>{detail.name}</strong>
              <span style={{ fontSize: '11px', opacity: 0.7 }}>
                built {detail.built_at || 'unknown'}
              </span>
              <button type="button" className="btn-tech" onClick={rebuild} disabled={isRunning}>
                <RefreshCw size={14} /> {isRunning ? 'Rebuilding…' : 'Rebuild'}
              </button>
            </div>

            {job && isRunning && (
              <div style={{ fontSize: '12px', marginBottom: 10 }}>
                {job.stages.map((stage) => (
                  <div key={stage.id} style={{ opacity: stage.status === 'PENDING' ? 0.45 : 1 }}>
                    {stage.status === 'DONE' ? '✓' : stage.status === 'RUNNING' ? '…' : '·'}{' '}
                    {stage.label}
                  </div>
                ))}
              </div>
            )}

            <section style={{ marginBottom: 14 }}>
              <h4 style={{ marginBottom: 4 }}>Corpus</h4>
              <table style={{ fontSize: '12px', width: '100%' }}>
                <tbody>
                  <tr>
                    <td>Included for profile</td>
                    <td>{detail.corpus.included_documents}</td>
                    <td>Holdout</td>
                    <td>{detail.corpus.holdout_documents}</td>
                  </tr>
                  <tr>
                    <td>Excluded</td>
                    <td>{detail.corpus.excluded_documents}</td>
                    <td>Held for review</td>
                    <td>{detail.corpus.held_for_review_documents}</td>
                  </tr>
                  <tr>
                    <td>Duplicate / revision groups</td>
                    <td>{detail.corpus.revision_groups}</td>
                    <td>Candidate prose files</td>
                    <td>{detail.corpus.candidate_prose_files}</td>
                  </tr>
                  <tr>
                    <td>Training words</td>
                    <td>{detail.corpus.training_words.toLocaleString()}</td>
                    <td>Holdout words</td>
                    <td>{detail.corpus.holdout_words.toLocaleString()}</td>
                  </tr>
                  <tr>
                    <td>Corpus sufficiency</td>
                    <td colSpan={3}>{detail.corpus.sufficiency.toUpperCase()}</td>
                  </tr>
                </tbody>
              </table>
              {detail.corpus.sufficiency_warnings.length > 0 && (
                <ul style={{ fontSize: '11px', opacity: 0.8 }}>
                  {detail.corpus.sufficiency_warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              )}
            </section>

            {detail.traits.length > 0 && (
              <section style={{ marginBottom: 14 }}>
                <h4 style={{ marginBottom: 4 }}>Global tendencies</h4>
                <ul style={{ fontSize: '12px', listStyle: 'none', paddingLeft: 0 }}>
                  {detail.traits.map((trait) => (
                    <li key={trait.name}>
                      {humanize(trait.name)}: <strong>{humanize(trait.value)}</strong>{' '}
                      <span style={{ color: BAND_COLORS[trait.confidence_band], fontSize: '11px' }}>
                        {trait.confidence_band}
                      </span>
                      {trait.source === 'user' && (
                        <span style={{ fontSize: '11px', opacity: 0.7 }}> (your override)</span>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {detail.contexts.map((context) => (
              <section key={context.name} style={{ marginBottom: 14 }}>
                <h4 style={{ marginBottom: 4 }}>
                  {humanize(context.name)} context
                  <span style={{ fontWeight: 'normal', fontSize: '11px', opacity: 0.7 }}>
                    {' '}
                    — {context.document_count} docs, {context.word_count.toLocaleString()} words,{' '}
                    {context.sufficiency}
                  </span>
                </h4>
                <ul style={{ fontSize: '12px', listStyle: 'none', paddingLeft: 0 }}>
                  {context.traits.map((trait) => (
                    <li key={trait.name}>
                      {humanize(trait.name)}: <strong>{humanize(trait.value)}</strong>{' '}
                      <span style={{ color: BAND_COLORS[trait.confidence_band], fontSize: '11px' }}>
                        {trait.confidence_band}
                      </span>
                    </li>
                  ))}
                </ul>
                <p style={{ fontSize: '11px', opacity: 0.7, margin: 0 }}>
                  These adjust the global tendencies for this context. They do not replace them.
                </p>
              </section>
            ))}

            <section style={{ marginBottom: 14 }}>
              <h4 style={{ marginBottom: 4 }}>Validation</h4>
              {Object.keys(detail.validation.alignment).length === 0 ? (
                <p style={{ fontSize: '12px' }}>
                  Not performed — the corpus was too small to hold documents back.
                </p>
              ) : (
                <ul style={{ fontSize: '12px', listStyle: 'none', paddingLeft: 0 }}>
                  {Object.entries(detail.validation.alignment).map(([dimension, band]) => (
                    <li key={dimension}>
                      {humanize(dimension)}:{' '}
                      <strong style={{ color: ALIGNMENT_COLORS[band] }}>{band}</strong>
                    </li>
                  ))}
                </ul>
              )}
              <p style={{ fontSize: '12px' }}>
                Overall profile confidence:{' '}
                <strong>{detail.validation.overall_confidence}</strong>
                <br />
                Voice diversity preservation:{' '}
                <strong>{detail.validation.diversity_preservation}</strong>
              </p>
              <p style={{ fontSize: '11px', opacity: 0.75 }}>
                These are alignment bands, not an authorship probability. They describe how well
                the profile predicts unseen writing from the same corpus, and say nothing about
                who wrote anything.
              </p>
            </section>

            {(detail.overrides.preserve.length > 0 ||
              detail.overrides.avoid.length > 0 ||
              Object.keys(detail.overrides.traits).length > 0) && (
              <section style={{ marginBottom: 14 }}>
                <h4 style={{ marginBottom: 4 }}>Your overrides</h4>
                <ul style={{ fontSize: '12px' }}>
                  {detail.overrides.preserve.map((item) => (
                    <li key={`p-${item}`}>preserve: {item}</li>
                  ))}
                  {detail.overrides.avoid.map((item) => (
                    <li key={`a-${item}`}>avoid: {item}</li>
                  ))}
                  {Object.entries(detail.overrides.traits).map(([name, value]) => (
                    <li key={`t-${name}`}>
                      {humanize(name)}: {value}
                    </li>
                  ))}
                </ul>
                <p style={{ fontSize: '11px', opacity: 0.75, margin: 0 }}>
                  Edit <code>overrides.yaml</code> in the voice directory. Overrides outrank the
                  generated traits and survive every rebuild.
                </p>
              </section>
            )}

            {detail.warnings.length > 0 && (
              <section>
                <h4 style={{ marginBottom: 4 }}>Notes</h4>
                <ul style={{ fontSize: '11px', opacity: 0.85 }}>
                  {detail.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
};
