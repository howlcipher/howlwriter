import React from 'react';
import { PenLine, Shuffle } from 'lucide-react';
import { api } from '../../api/client';
import { WorkshopCoverage, WorkshopPrompt, WorkshopSample } from '../../types';

/**
 * Voice Workshop: answer a short prompt, save it privately, come back later.
 *
 * Prompts come from a local template bank (no model call). Answers are kept
 * exactly as typed -- browser autocorrect and autocapitalisation are turned
 * off -- and reach a profile only after explicit approval. The prompt text is
 * never treated as the person's writing, and an optional "how I'd prefer it
 * to read" revision is stored separately and never used as evidence.
 */

const CONTEXTS = ['academic', 'professional', 'technical', 'casual'];

function words(text: string): string {
  return text.replace(/_/g, ' ');
}

export const VoiceWorkshop: React.FC<{ identity: string }> = ({ identity }) => {
  const [coverage, setCoverage] = React.useState<WorkshopCoverage | null>(null);
  const [samples, setSamples] = React.useState<WorkshopSample[]>([]);
  const [showText, setShowText] = React.useState(false);
  const [context, setContext] = React.useState('');
  const [subject, setSubject] = React.useState('');
  const [prompt, setPrompt] = React.useState<WorkshopPrompt | null>(null);
  const [answer, setAnswer] = React.useState('');
  const [selfWritten, setSelfWritten] = React.useState(false);
  const [approve, setApprove] = React.useState(false);
  const [lastSample, setLastSample] = React.useState<string | null>(null);
  const [revision, setRevision] = React.useState<Record<string, string>>({});
  const [message, setMessage] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    const data = await api.getWorkshop(identity, showText);
    setCoverage(data.coverage);
    setSamples(data.samples);
  }, [identity, showText]);

  React.useEffect(() => {
    load().catch((err) => setMessage(err instanceof Error ? err.message : 'Failed to load workshop'));
  }, [load]);

  const fail = (err: unknown) => setMessage(err instanceof Error ? err.message : 'Something went wrong');

  const nextPrompt = async (followUp = false) => {
    setMessage(null);
    try {
      setPrompt(
        await api.workshopPrompt(identity, {
          context: context || null,
          subject: subject.trim() || null,
          follow_up_of: followUp ? lastSample : null,
        }),
      );
      setAnswer('');
    } catch (err) {
      fail(err);
    }
  };

  const save = async () => {
    if (!prompt || !answer.trim()) return;
    setBusy(true);
    try {
      const sample = await api.workshopAnswer(identity, {
        prompt_id: prompt.prompt_id,
        subject: prompt.subject,
        text: answer,
        self_written: selfWritten,
        approve: approve && selfWritten,
      });
      setLastSample(sample.sample_id);
      setMessage(
        `Saved privately (${sample.words} words, ${sample.status}${sample.side ? `, ${sample.side}` : ''}).` +
          (sample.counts || sample.status !== 'approved' ? '' : ' It repeats an earlier answer and will not count twice.'),
      );
      setPrompt(null);
      setAnswer('');
      setApprove(false);
      await load();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const act = async (sample: WorkshopSample, action: 'approve' | 'exclude' | 'remove') => {
    if (action === 'remove' && !window.confirm('Delete this answer permanently?')) return;
    try {
      await api.workshopAction(identity, sample.sample_id, action);
      await load();
    } catch (err) {
      fail(err);
    }
  };

  return (
    <div>
      <p style={{ fontSize: 12, opacity: 0.8, marginTop: 0 }}>
        Answer short prompts to add samples of how you write. Everything stays on this machine; prompts are generated
        locally and no model is called. Your documents remain the main evidence; samples fill gaps.
      </p>

      {coverage && (
        <section style={{ marginBottom: 12 }} aria-label="Profile coverage">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 8 }}>
            {Object.entries(coverage.profiles).map(([name, entry]) => (
              <div key={name} style={{ border: '1px solid var(--border-medium, #ccc)', padding: 8, fontSize: 12 }}>
                <strong>{name}</strong>
                <div>
                  {entry.documents} attested documents ({entry.document_words.toLocaleString()} words)
                </div>
                <div>
                  {entry.workshop_samples} workshop samples ({entry.workshop_words} words; {entry.workshop_train} training /{' '}
                  {entry.workshop_calibration} calibration)
                </div>
                <div style={{ marginTop: 4 }}>
                  <em>{entry.sufficiency}</em>
                </div>
                {entry.gaps.length > 0 && (
                  <ul style={{ margin: '4px 0 0 16px' }}>
                    {entry.gaps.map((gap) => (
                      <li key={gap}>{gap}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      <section style={{ border: '1px solid var(--border-medium, #ccc)', padding: 10, marginBottom: 12 }} aria-label="Prompt">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
          <label style={{ fontSize: 12 }}>
            Context{' '}
            <select
              className="form-select"
              style={{ width: 'auto', display: 'inline-block' }}
              value={context}
              onChange={(e) => setContext(e.target.value)}
            >
              <option value="">Largest gap first</option>
              {CONTEXTS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: 12 }}>
            Your subject (optional){' '}
            <input
              className="form-input"
              style={{ width: 220, display: 'inline-block' }}
              value={subject}
              maxLength={120}
              onChange={(e) => setSubject(e.target.value)}
            />
          </label>
          <button type="button" className="btn-tech" onClick={() => nextPrompt(false)}>
            <Shuffle size={14} /> New prompt
          </button>
          {lastSample && (
            <button type="button" className="btn-tech" onClick={() => nextPrompt(true)}>
              Follow-up on my last answer
            </button>
          )}
        </div>
        {prompt ? (
          <>
            <p style={{ fontSize: 14, margin: '6px 0' }}>
              <PenLine size={14} style={{ verticalAlign: 'middle' }} /> {prompt.text}
            </p>
            <p style={{ fontSize: 11, opacity: 0.7, margin: '0 0 6px' }}>
              {prompt.context} · {prompt.kind === 'short' ? '1–3 sentences' : 'a paragraph'} · {prompt.reason}
            </p>
            <textarea
              className="form-textarea"
              rows={prompt.kind === 'short' ? 4 : 8}
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              aria-label="Your answer"
              autoCorrect="off"
              autoCapitalize="off"
              spellCheck={false}
            />
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', marginTop: 6, fontSize: 12 }}>
              <label>
                <input type="checkbox" checked={selfWritten} onChange={(e) => setSelfWritten(e.target.checked)} /> I wrote
                this myself, without AI help
              </label>
              <label style={{ opacity: selfWritten ? 1 : 0.5 }}>
                <input
                  type="checkbox"
                  checked={approve && selfWritten}
                  disabled={!selfWritten}
                  onChange={(e) => setApprove(e.target.checked)}
                />{' '}
                Include in my profiles
              </label>
              <button type="button" className="btn-tech btn-tech-primary" onClick={save} disabled={busy || !answer.trim()}>
                Save privately
              </button>
            </div>
            <p style={{ fontSize: 11, opacity: 0.7 }}>Saved exactly as typed. Nothing is corrected.</p>
          </>
        ) : (
          <p style={{ fontSize: 12 }}>Press “New prompt” to start. You can stop any time and resume later.</p>
        )}
      </section>

      <div aria-live="polite" style={{ fontSize: 12, minHeight: 18 }}>
        {message}
      </div>

      <section aria-label="Your samples">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h4 style={{ margin: '6px 0' }}>Your samples ({samples.filter((s) => s.status !== 'removed').length})</h4>
          <label style={{ fontSize: 12 }}>
            <input type="checkbox" checked={showText} onChange={(e) => setShowText(e.target.checked)} /> Show my text
          </label>
        </div>
        {samples
          .filter((s) => s.status !== 'removed')
          .map((sample) => (
            <article key={sample.sample_id} style={{ borderTop: '1px solid var(--border-medium, #ccc)', padding: '6px 0', fontSize: 12 }}>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'space-between' }}>
                <span>
                  <strong>{sample.context}</strong> · {sample.words} words · {sample.status}
                  {sample.side && ` · ${sample.side}`} · {sample.counts ? 'counts' : 'not counted'}
                  {sample.classified_context && sample.classified_context !== 'unknown' && sample.classified_context !== sample.context && (
                    <span style={{ opacity: 0.7 }}> · reads as {words(sample.classified_context)}</span>
                  )}
                </span>
                <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {sample.status !== 'approved' && sample.self_written && (
                    <button type="button" className="btn-tech" onClick={() => act(sample, 'approve')}>
                      Approve
                    </button>
                  )}
                  {sample.status !== 'excluded' && (
                    <button type="button" className="btn-tech" onClick={() => act(sample, 'exclude')}>
                      Exclude
                    </button>
                  )}
                  <select
                    className="form-select"
                    aria-label="Reclassify context"
                    style={{ width: 'auto' }}
                    value={sample.context}
                    onChange={(e) =>
                      api.workshopReclassify(identity, sample.sample_id, e.target.value).then(load).catch(fail)
                    }
                  >
                    {CONTEXTS.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                  <button type="button" className="btn-tech btn-tech-danger" onClick={() => act(sample, 'remove')}>
                    Remove
                  </button>
                </span>
              </div>
              <div style={{ opacity: 0.75 }}>{sample.prompt_text}</div>
              {showText && sample.text && <p style={{ margin: '4px 0', whiteSpace: 'pre-wrap' }}>{sample.text}</p>}
              {showText && (
                <label style={{ display: 'block' }}>
                  How I'd prefer it to read (kept separately, never used as evidence):
                  <textarea
                    className="form-textarea"
                    rows={2}
                    value={revision[sample.sample_id] ?? sample.preferred_revision ?? ''}
                    onChange={(e) => setRevision((prev) => ({ ...prev, [sample.sample_id]: e.target.value }))}
                    onBlur={() =>
                      revision[sample.sample_id] !== undefined &&
                      api.workshopRevision(identity, sample.sample_id, revision[sample.sample_id]).catch(fail)
                    }
                  />
                </label>
              )}
            </article>
          ))}
      </section>
      {coverage && <p style={{ fontSize: 11, opacity: 0.7 }}>{coverage.notes.join(' ')}</p>}
    </div>
  );
};
