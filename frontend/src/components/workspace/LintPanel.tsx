import React from 'react';
import { CheckCircle } from 'lucide-react';
import { LintResponse } from '../../types';

interface LintPanelProps {
  lintResult: LintResponse | null;
  onClear: () => void;
}

export const LintPanel: React.FC<LintPanelProps> = ({ lintResult, onClear }) => {
  const [filter, setFilter] = React.useState<'all' | 'banned' | 'style'>('all');

  if (!lintResult) {
    return (
      <div className="tech-panel" style={{ height: '100%' }}>
        <div className="tech-header">
          <h3><CheckCircle size={15} /> DETERMINISTIC LINT</h3>
          <span className="sec-id">SYS.01</span>
        </div>
        <div className="tech-body" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-dim)', textAlign: 'center', fontSize: '0.85rem' }}>
          Click [LINT] to analyze text against deterministic AI style & banned word rules.
        </div>
      </div>
    );
  }

  const matches = lintResult.matches.filter((m) => {
    if (filter === 'banned') return m.rule_code.includes('BANNED');
    if (filter === 'style') return !m.rule_code.includes('BANNED');
    return true;
  });

  return (
    <div className="tech-panel" style={{ height: '100%' }}>
      <div className="tech-header">
        <h3>
          <CheckCircle size={15} />
          LINT FINDINGS ({lintResult.total_count})
        </h3>
        <div style={{ display: 'flex', gap: '0.4rem' }}>
          <button type="button" className="btn-tech" onClick={onClear} style={{ padding: '0.2rem 0.4rem', fontSize: '0.7rem' }}>
            [CLEAR]
          </button>
        </div>
      </div>

      <div style={{ padding: '0.5rem 0.75rem', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <button
          type="button"
          className={`chip ${filter === 'all' ? 'chip-blue' : 'chip-neutral'}`}
          onClick={() => setFilter('all')}
          style={{ cursor: 'pointer' }}
        >
          ALL: {lintResult.total_count}
        </button>
        <button
          type="button"
          className={`chip ${filter === 'banned' ? 'chip-red' : 'chip-neutral'}`}
          onClick={() => setFilter('banned')}
          style={{ cursor: 'pointer' }}
        >
          BANNED WORDS: {lintResult.banned_words_count}
        </button>
        <button
          type="button"
          className={`chip ${filter === 'style' ? 'chip-amber' : 'chip-neutral'}`}
          onClick={() => setFilter('style')}
          style={{ cursor: 'pointer' }}
        >
          AI STYLE: {lintResult.ai_style_warnings_count}
        </button>
      </div>

      <div className="tech-body">
        {matches.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '1.5rem', color: 'var(--color-cyan)' }}>
            <CheckCircle size={24} style={{ margin: '0 auto 0.5rem', display: 'block' }} />
            <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>CLEAN // NO RULE MATCHES</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Prose passes all deterministic style and vocabulary filters.</div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
            {matches.map((m, idx) => {
              const isBanned = m.rule_code.includes('BANNED');
              return (
                <div
                  key={idx}
                  style={{
                    background: 'var(--bg-surface)',
                    border: '1px solid var(--border-subtle)',
                    borderLeft: `3px solid ${isBanned ? 'var(--color-red)' : 'var(--color-amber)'}`,
                    padding: '0.6rem 0.75rem',
                    fontSize: '0.8rem',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
                    <span className={`chip ${isBanned ? 'chip-red' : 'chip-amber'}`} style={{ fontSize: '0.65rem' }}>
                      {m.rule_code}
                    </span>
                    {m.paragraph_index !== null && m.paragraph_index !== undefined && (
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-dim)' }}>
                        P.{m.paragraph_index + 1}
                      </span>
                    )}
                  </div>
                  {m.matched_text && (
                    <div style={{ fontFamily: 'var(--font-mono)', background: 'var(--bg-sunken)', padding: '0.25rem 0.45rem', marginBottom: '0.35rem', color: 'var(--text-primary)' }}>
                      "{m.matched_text}"
                    </div>
                  )}
                  <div style={{ color: 'var(--text-secondary)', lineHeight: 1.4 }}>{m.message}</div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
