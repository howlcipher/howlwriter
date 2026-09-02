import React from 'react';
import { ShieldAlert, ShieldCheck } from 'lucide-react';

interface ReadinessExplanationProps {
  status: string;
  meaningPreservation: string;
  bannedWordsCount: number;
  aiStyleCount: number;
  redPenFindingsCount?: number;
}

export const ReadinessExplanation: React.FC<ReadinessExplanationProps> = ({
  status,
  meaningPreservation,
  bannedWordsCount,
  aiStyleCount,
  redPenFindingsCount = 0,
}) => {
  const isReady = status === 'READY';

  return (
    <div
      style={{
        background: 'var(--bg-surface)',
        border: `1px solid ${isReady ? 'var(--color-cyan)' : 'var(--color-amber)'}`,
        borderLeft: `4px solid ${isReady ? 'var(--color-cyan)' : 'var(--color-amber)'}`,
        padding: '0.75rem 1rem',
        fontSize: '0.82rem',
        marginBottom: '0.75rem',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
        {isReady ? (
          <ShieldCheck size={16} color="var(--color-cyan)" />
        ) : (
          <ShieldAlert size={16} color="var(--color-amber)" />
        )}
        <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.85rem', color: isReady ? 'var(--color-cyan)' : 'var(--color-amber)' }}>
          DOCUMENT READINESS: {status}
        </span>
      </div>

      <div style={{ color: 'var(--text-secondary)', lineHeight: 1.4 }}>
        {isReady ? (
          <span>
            This document meets HowlWriter publication standards: semantic meaning is verified preserved, banned vocabulary is eliminated, and style matches target voice profiles.
          </span>
        ) : (
          <div>
            <strong>Why NEEDS_REVIEW:</strong>
            <ul style={{ margin: '0.25rem 0 0 1.25rem' }}>
              {meaningPreservation !== 'PASS' && <li>Semantic meaning review flagged unresolved discrepancies or unverified transformations.</li>}
              {bannedWordsCount > 0 && <li>Contains {bannedWordsCount} banned AI words/cliches that must be resolved.</li>}
              {aiStyleCount > 3 && <li>Excessive synthetic AI style patterns detected ({aiStyleCount} instances).</li>}
              {redPenFindingsCount > 0 && <li>Unaddressed Red Pen critique findings remaining.</li>}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
};
