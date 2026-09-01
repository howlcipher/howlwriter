import React from 'react';
import { CheckCircle, ShieldAlert } from 'lucide-react';
import { ReviewReason } from '../../types';

interface ReviewReasonsPanelProps {
  reasons: ReviewReason[];
}

export const ReviewReasonsPanel: React.FC<ReviewReasonsPanelProps> = ({ reasons }) => {
  if (!reasons || reasons.length === 0) {
    return (
      <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', padding: '0.75rem 1rem', marginBottom: '0.75rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--color-cyan)', fontWeight: 700, fontSize: '0.85rem' }}>
          <CheckCircle size={15} /> ALL AUDIT GATES PASSED
        </div>
        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
          Research sufficiency, claim verification, semantic preservation, outline conformance, and citation formats all meet publication readiness criteria.
        </div>
      </div>
    );
  }

  const getCategoryBadge = (category: string) => {
    switch (category) {
      case 'RESEARCH_SUFFICIENCY':
        return { label: 'RESEARCH SUFFICIENCY', chipClass: 'chip-fail' };
      case 'SOURCE_CLAIM_SUPPORT':
        return { label: 'SOURCE / CLAIM SUPPORT', chipClass: 'chip-amber' };
      case 'SEMANTIC_REVIEW':
        return { label: 'SEMANTIC REVIEW (ADVERSARIAL)', chipClass: 'chip-blue' };
      case 'WORD_COUNT':
        return { label: 'WORD COUNT', chipClass: 'chip-neutral' };
      case 'OUTLINE':
        return { label: 'OUTLINE CONFORMANCE', chipClass: 'chip-require' };
      case 'CITATIONS':
        return { label: 'CITATIONS / METADATA', chipClass: 'chip-neutral' };
      default:
        return { label: 'OTHER', chipClass: 'chip-neutral' };
    }
  };

  return (
    <div className="tech-panel" style={{ marginBottom: '0.75rem' }}>
      <div className="tech-header" style={{ background: 'var(--bg-surface)', color: 'var(--text-primary)', borderBottom: '1px solid var(--border-medium)' }}>
        <h4 style={{ fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--color-amber)' }}>
          <ShieldAlert size={15} />
          CATEGORIZED REVIEW REASONS & AUDIT FINDINGS ({reasons.length})
        </h4>
        <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
          INDIVIDUAL QUALITY GATES
        </span>
      </div>

      <div className="tech-body" style={{ padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.5rem', maxHeight: '240px', overflowY: 'auto' }}>
        {reasons.map((r, idx) => {
          const badge = getCategoryBadge(r.category);
          const isCritical = r.severity === 'critical';

          return (
            <div
              key={idx}
              style={{
                background: 'var(--bg-panel)',
                border: '1px solid var(--border-subtle)',
                borderLeft: `3px solid ${isCritical ? 'var(--color-red)' : 'var(--color-amber)'}`,
                padding: '0.6rem 0.8rem',
                fontSize: '0.8rem',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
                <span className={`chip ${badge.chipClass}`} style={{ fontSize: '0.65rem' }}>
                  {badge.label}
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: isCritical ? 'var(--color-red)' : 'var(--text-dim)' }}>
                  SEVERITY: {r.severity.toUpperCase()}
                </span>
              </div>

              <div style={{ fontWeight: 700, color: 'var(--text-primary)', marginBottom: '0.2rem' }}>
                {r.title}
              </div>

              <div style={{ color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                {r.explanation}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
