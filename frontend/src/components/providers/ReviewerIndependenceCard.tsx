import React from 'react';
import { ShieldCheck, ShieldAlert } from 'lucide-react';

interface ReviewerIndependenceCardProps {
  status: string;
  reason: string;
}

export const ReviewerIndependenceCard: React.FC<ReviewerIndependenceCardProps> = ({
  status,
  reason,
}) => {
  const isIndependent = status === 'INDEPENDENT';
  const isSame = status === 'SAME_PROVIDER';

  return (
    <div
      style={{
        background: 'var(--bg-panel)',
        border: `1px solid ${isIndependent ? 'var(--color-cyan)' : 'var(--color-amber)'}`,
        borderLeft: `4px solid ${isIndependent ? 'var(--color-cyan)' : isSame ? 'var(--color-red)' : 'var(--color-amber)'}`,
        padding: '1rem',
        boxShadow: 'var(--shadow-tech)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          {isIndependent ? (
            <ShieldCheck size={18} color="var(--color-cyan)" />
          ) : (
            <ShieldAlert size={18} color={isSame ? 'var(--color-red)' : 'var(--color-amber)'} />
          )}
          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.9rem', color: isIndependent ? 'var(--color-cyan)' : isSame ? 'var(--color-red)' : 'var(--color-amber)' }}>
            REVIEWER INDEPENDENCE GUARANTEE: {status}
          </span>
        </div>
      </div>

      <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.5, marginBottom: '0.75rem' }}>
        {reason}
      </div>

      <div style={{ background: 'var(--bg-sunken)', padding: '0.5rem 0.75rem', fontSize: '0.75rem', color: 'var(--text-dim)', border: '1px solid var(--border-subtle)' }}>
        <strong>Architectural Guardrail:</strong> HowlWriter enforces that the Humanizer and Final Reviewer roles are executed by distinct AI providers to avoid self-verification rubber-stamping and guarantee honest falsification of semantic drift.
      </div>
    </div>
  );
};
