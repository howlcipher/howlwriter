import React from 'react';
import { Edit3, CheckCircle } from 'lucide-react';
import { RedPenResponse } from '../../types';

interface RedPenPanelProps {
  redPenResult: RedPenResponse | null;
  onClear: () => void;
}

export const RedPenPanel: React.FC<RedPenPanelProps> = ({ redPenResult, onClear }) => {
  if (!redPenResult) {
    return (
      <div className="tech-panel" style={{ height: '100%' }}>
        <div className="tech-header">
          <h3><Edit3 size={15} /> RED PEN CRITIQUE</h3>
          <span className="sec-id">SYS.02</span>
        </div>
        <div className="tech-body" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-dim)', textAlign: 'center', fontSize: '0.85rem' }}>
          Click [RED PEN] to receive detailed editorial critique on tone, vagueness, and structural flow.
        </div>
      </div>
    );
  }

  return (
    <div className="tech-panel" style={{ height: '100%' }}>
      <div className="tech-header">
        <h3>
          <Edit3 size={15} />
          RED PEN CRITIQUES ({redPenResult.total_count})
        </h3>
        <button type="button" className="btn-tech" onClick={onClear} style={{ padding: '0.2rem 0.4rem', fontSize: '0.7rem' }}>
          [CLEAR]
        </button>
      </div>

      <div className="tech-body">
        {redPenResult.findings.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '1.5rem', color: 'var(--color-cyan)' }}>
            <CheckCircle size={24} style={{ margin: '0 auto 0.5rem', display: 'block' }} />
            <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>NO CRITICAL DEFECTS</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Prose exhibits strong clarity, directness, and precision.</div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
            {redPenResult.findings.map((f, idx) => (
              <div
                key={idx}
                style={{
                  background: 'var(--bg-surface)',
                  border: '1px solid var(--border-subtle)',
                  borderLeft: '3px solid var(--color-red)',
                  padding: '0.75rem',
                  fontSize: '0.82rem',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
                  <span className="chip chip-red" style={{ fontSize: '0.65rem' }}>
                    {f.category}
                  </span>
                  {f.location && (
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-dim)' }}>
                      {f.location}
                    </span>
                  )}
                </div>

                <div style={{ fontWeight: 700, color: 'var(--text-primary)', marginBottom: '0.25rem' }}>
                  {f.finding}
                </div>

                {f.snippet && (
                  <div style={{ fontFamily: 'var(--font-mono)', background: 'var(--bg-sunken)', padding: '0.25rem 0.45rem', marginBottom: '0.35rem', color: 'var(--color-red)' }}>
                    "{f.snippet}"
                  </div>
                )}

                <div style={{ color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                  <strong>Reason:</strong> {f.reason}
                </div>

                <div style={{ background: 'var(--bg-panel)', padding: '0.35rem 0.5rem', border: '1px solid var(--border-subtle)', color: 'var(--color-blue)' }}>
                  <strong>Fix:</strong> {f.recommendation}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
