import React from 'react';
import { AcademicResult } from '../../types';

interface AcademicStatsBarProps {
  result: AcademicResult;
  onReset: () => void;
}

export const AcademicStatsBar: React.FC<AcademicStatsBarProps> = ({ result, onReset }) => {
  const isReady = result.status === 'READY';
  const wordPass = result.word_count_status === 'PASS';
  const outlinePass = result.outline_status === 'PASS';

  return (
    <div
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-medium)',
        padding: '0.75rem 1rem',
        marginBottom: '0.75rem',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: '1rem',
        boxShadow: 'var(--shadow-tech)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <span className={`chip ${isReady ? 'chip-pass' : 'chip-require'}`} style={{ fontSize: '0.85rem' }}>
            STATUS: {result.status}
          </span>
          <span className={`chip ${result.meaning_preservation === 'PASS' ? 'chip-pass' : 'chip-fail'}`}>
            MEANING: {result.meaning_preservation}
          </span>
          <span className={`chip ${result.reviewer_independence === 'INDEPENDENT' ? 'chip-pass' : 'chip-amber'}`}>
            INDEPENDENCE: {result.reviewer_independence || 'NOT_REVIEWED'}
          </span>
        </div>

        <div style={{ display: 'flex', gap: '0.85rem', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
          <span>
            <strong>BODY:</strong> {result.actual_body_words} / {result.target_words} words ({wordPass ? 'PASS' : 'WARN'})
          </span>
          <span>•</span>
          <span>
            <strong>OUTLINE:</strong> {result.present_outline_topics}/{result.required_outline_topics} ({outlinePass ? '100%' : 'DEFICIENT'})
          </span>
          <span>•</span>
          <span>
            <strong>SOURCES:</strong> {result.sources_used} cited ({result.sources_retrieved} gathered)
          </span>
          <span>•</span>
          <span>
            <strong>CLAIMS:</strong> {result.supported_claims} verified ({result.unsupported_claims} unsupported)
          </span>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button type="button" className="btn-tech" onClick={onReset} style={{ fontSize: '0.75rem' }}>
          [NEW SPEC]
        </button>
      </div>
    </div>
  );
};
