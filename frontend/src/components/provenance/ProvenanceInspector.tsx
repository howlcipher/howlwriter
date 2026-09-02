import React from 'react';
import { Activity, AlertTriangle, Eye, EyeOff, GitBranch, Hash, ShieldCheck } from 'lucide-react';
import { GenerationProvenance, ModelCallRecord } from '../../types';
import { api } from '../../api/client';

/**
 * Read-only inspection of one run's generation provenance.
 *
 * Read-only on purpose. This surfaces evidence about a run that already
 * happened; a panel that could edit one would make every other record worth
 * less. It also computes nothing: every figure below is rendered from what the
 * backend recorded, because a UI that recalculates a number is a second place
 * for that number to be wrong.
 *
 * Prompts are withheld until asked for. They contain the user's own sentences,
 * which is the same reason the voices endpoint withholds source paths.
 */

const dim = { color: 'var(--text-dim)' };

const modelLabel = (call: ModelCallRecord): string => {
  // A provider that reported nothing must not be rendered as though it
  // reported its own name.
  if (call.model) return call.model;
  return 'not reported by provider';
};

export const ProvenanceInspector: React.FC<{ runId: string | null }> = ({ runId }) => {
  const [record, setRecord] = React.useState<GenerationProvenance | null>(null);
  const [showPrompts, setShowPrompts] = React.useState(false);
  const [expanded, setExpanded] = React.useState<number | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [isLoading, setIsLoading] = React.useState(false);

  const load = React.useCallback(async (withPrompts: boolean) => {
    if (!runId) return;
    setIsLoading(true);
    setError(null);
    try {
      setRecord(await api.getProvenance(runId, withPrompts));
    } catch (err) {
      setRecord(null);
      setError(err instanceof Error ? err.message : 'Failed to load provenance.');
    } finally {
      setIsLoading(false);
    }
  }, [runId]);

  React.useEffect(() => {
    setShowPrompts(false);
    load(false);
  }, [runId, load]);

  const togglePrompts = async () => {
    const next = !showPrompts;
    setShowPrompts(next);
    await load(next);
  };

  if (!runId) {
    return (
      <div className="tech-panel">
        <div className="tech-header"><h3><GitBranch size={16} /> GENERATION PROVENANCE</h3></div>
        <div className="tech-body" style={{ ...dim, padding: '2rem', textAlign: 'center' }}>
          Select a run to inspect what ran, what it was told, and what it added.
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="tech-panel">
        <div className="tech-header"><h3><GitBranch size={16} /> GENERATION PROVENANCE</h3></div>
        <div className="tech-body" style={{ padding: '1.5rem' }}>
          <div style={{ color: 'var(--warn, #d08770)' }}>
            <AlertTriangle size={14} /> {error}
          </div>
          <p style={{ ...dim, fontSize: '0.8rem', marginTop: '0.75rem' }}>
            Runs record provenance only when they generate. Older runs, and runs
            that only linted, have none.
          </p>
        </div>
      </div>
    );
  }

  if (!record) {
    return (
      <div className="tech-panel">
        <div className="tech-header"><h3><GitBranch size={16} /> GENERATION PROVENANCE</h3></div>
        <div className="tech-body" style={{ ...dim, padding: '2rem' }}>
          {isLoading ? 'Loading…' : 'No record.'}
        </div>
      </div>
    );
  }

  const c = record.contribution;

  return (
    <div className="tech-panel">
      <div className="tech-header">
        <h3><GitBranch size={16} /> GENERATION PROVENANCE — {record.run_id}</h3>
        <button type="button" className="btn-tech" onClick={togglePrompts} style={{ fontSize: '0.75rem' }}>
          {showPrompts ? <EyeOff size={12} /> : <Eye size={12} />}
          <span>{showPrompts ? '[HIDE PROMPTS]' : '[SHOW EXACT PROMPTS]'}</span>
        </button>
      </div>

      <div className="tech-body" style={{ padding: '1rem', display: 'grid', gap: '1.25rem' }}>
        {!record.complete && (
          <div style={{ color: 'var(--warn, #d08770)', fontSize: '0.85rem' }}>
            <AlertTriangle size={14} /> This run did not finish every stage. The
            record below is incomplete.
          </div>
        )}

        <section>
          <h4 style={{ margin: '0 0 0.5rem' }}>RUN</h4>
          <div style={{ fontSize: '0.85rem', display: 'grid', gap: '0.2rem' }}>
            <div>workflow: {record.workflow}</div>
            {record.writing_mode && <div>mode: {record.writing_mode}</div>}
            {record.generation_freedom && (
              <div>generation freedom: <strong>{record.generation_freedom}</strong></div>
            )}
            <div>recorded at level: {record.provenance_level}</div>
          </div>
        </section>

        <section>
          <h4 style={{ margin: '0 0 0.5rem' }}><Activity size={14} /> TIMELINE</h4>
          <div style={{ display: 'grid', gap: '0.35rem' }}>
            {record.timeline.map((node) => (
              <div
                key={node.sequence}
                style={{
                  fontSize: '0.82rem',
                  padding: '0.4rem 0.6rem',
                  border: '1px solid var(--border, #333)',
                  borderLeft: `3px solid ${node.model_backed ? 'var(--accent, #88c0d0)' : 'var(--border, #444)'}`,
                }}
              >
                <strong>{node.name}</strong>
                {node.model_backed && <span style={dim}> · model-backed</span>}
                {node.duration_seconds != null && <span style={dim}> · {node.duration_seconds.toFixed(2)}s</span>}
                <span style={dim}> · {node.status}</span>
                {node.detail && <div style={{ ...dim, fontSize: '0.78rem' }}>{node.detail}</div>}
              </div>
            ))}
          </div>
        </section>

        <section>
          <h4 style={{ margin: '0 0 0.5rem' }}>MODEL CALLS</h4>
          {record.calls.length === 0 ? (
            <p style={{ ...dim, fontSize: '0.85rem' }}>
              No model-backed stage ran. Nothing here was generated or rewritten by a model.
            </p>
          ) : (
            <div style={{ display: 'grid', gap: '0.4rem' }}>
              {record.calls.map((call) => (
                <div key={call.sequence} style={{ border: '1px solid var(--border, #333)', padding: '0.5rem 0.6rem' }}>
                  <div style={{ fontSize: '0.85rem' }}>
                    <strong>{call.sequence}. {call.role}</strong>
                    {!call.success && <span style={{ color: 'var(--warn, #d08770)' }}> · FAILED</span>}
                    {call.retry_of != null && <span style={dim}> · retry of call {call.retry_of}</span>}
                  </div>
                  <div style={{ ...dim, fontSize: '0.8rem' }}>
                    provider: {call.provider || 'unknown'} · model: {modelLabel(call)}
                    {call.independence_status && ` · independence: ${call.independence_status}`}
                  </div>
                  <div style={{ ...dim, fontSize: '0.78rem' }}>
                    <Hash size={11} /> prompt {call.user_prompt_chars} chars · sha256:{call.user_prompt_sha256.slice(0, 16)}…
                    {' · '}token usage: {call.token_usage ? JSON.stringify(call.token_usage) : 'not reported by provider'}
                  </div>
                  {showPrompts && (call.user_prompt || call.system_instruction) && (
                    <div style={{ marginTop: '0.4rem' }}>
                      <button
                        type="button"
                        className="btn-tech"
                        style={{ fontSize: '0.72rem' }}
                        onClick={() => setExpanded(expanded === call.sequence ? null : call.sequence)}
                      >
                        {expanded === call.sequence ? '[COLLAPSE]' : '[VIEW EXACT PROMPT SENT]'}
                      </button>
                      {expanded === call.sequence && (
                        <pre
                          style={{
                            whiteSpace: 'pre-wrap',
                            fontSize: '0.72rem',
                            maxHeight: '22rem',
                            overflow: 'auto',
                            background: 'var(--bg-alt, #1a1a1a)',
                            padding: '0.6rem',
                            marginTop: '0.4rem',
                          }}
                        >
                          {call.system_instruction && `--- SYSTEM ---\n${call.system_instruction}\n\n`}
                          {`--- USER ---\n${call.user_prompt}`}
                        </pre>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          {record.prompt_note && (
            <p style={{ ...dim, fontSize: '0.78rem', marginTop: '0.5rem' }}>{record.prompt_note}</p>
          )}
          {record.unknown_model_calls > 0 && (
            <p style={{ ...dim, fontSize: '0.78rem', marginTop: '0.5rem' }}>
              {record.unknown_model_calls} of {record.calls.length} call(s) ran on a
              provider that did not report a model name. The name is omitted rather
              than inferred.
            </p>
          )}
          {record.reviewer_independence && (
            <p style={{ fontSize: '0.8rem', marginTop: '0.4rem' }}>
              <ShieldCheck size={13} /> Reviewer independence: <strong>{record.reviewer_independence}</strong>
            </p>
          )}
        </section>

        {record.outline_present && (
          <section>
            <h4 style={{ margin: '0 0 0.5rem' }}>USER CONTRIBUTION AND COVERAGE</h4>
            <div style={{ fontSize: '0.85rem', display: 'grid', gap: '0.2rem' }}>
              <div>claims supplied: {c.claims_supplied} · represented: {c.claims_represented}</div>
              <div>required points: {c.required_points_represented}/{c.required_points_supplied}</div>
              <div>preserved sentences: {c.preserved_retained}/{c.preserved_supplied}</div>
              <div>examples: {c.examples_represented}/{c.examples_supplied}</div>
              <div>words of user prose supplied: {c.user_words_supplied}</div>
              <div>model-added factual claims: {c.model_added_claims}</div>
              {c.gaps_reported > 0 && <div>gaps the writer refused to invent: {c.gaps_reported}</div>}
            </div>
            <p style={{ ...dim, fontSize: '0.78rem', marginTop: '0.5rem' }}>
              Counts only. HowlWriter cannot establish what share of the finished
              text is human-authored and does not estimate one.
            </p>
          </section>
        )}

        <section>
          <h4 style={{ margin: '0 0 0.5rem' }}>ARTIFACT INTEGRITY</h4>
          <div style={{ ...dim, fontSize: '0.78rem', display: 'grid', gap: '0.15rem' }}>
            {record.outline_sha256 && <div>outline sha256:{record.outline_sha256.slice(0, 24)}…</div>}
            {record.draft_sha256 && <div>draft sha256:{record.draft_sha256.slice(0, 24)}…</div>}
            {record.artifact_sha256 && <div>final sha256:{record.artifact_sha256.slice(0, 24)}…</div>}
          </div>
          <p style={{ ...dim, fontSize: '0.78rem', marginTop: '0.4rem' }}>
            These hashes establish that the recorded artifact is the one this
            record describes. They are not evidence of human authorship.
          </p>
        </section>
      </div>
    </div>
  );
};
