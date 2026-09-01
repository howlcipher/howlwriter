import React from 'react';
import { AcademicResult } from '../../types';
import { AlertTriangle } from 'lucide-react';

interface AcademicStatsBarProps {
  result: AcademicResult;
  onReset: () => void;
  onToggleReasons?: () => void;
  showReasons?: boolean;
}

export const AcademicStatsBar: React.FC<AcademicStatsBarProps> = ({
  result,
  onReset,
  onToggleReasons,
  showReasons,
}) => {
  const isReady = result.status === 'READY';
  const wordPass = result.word_count_status === 'PASS';
  const outlinePass = result.outline_status === 'PASS';
  const isSourceDeficient = result.sources_retrieved < result.sources_required;

  return (
    <div
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-medium)',
        padding: '0.75rem 1rem',
        marginBottom: '0.75rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.65rem',
        boxShadow: 'var(--shadow-tech)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <span className={`chip ${isReady ? 'chip-pass' : 'chip-require'}`} style={{ fontSize: '0.85rem' }}>
            STATUS: {result.status}
          </span>
          <span className={`chip ${result.meaning_preservation === 'PASS' ? 'chip-pass' : 'chip-fail'}`}>
            MEANING: {result.meaning_preservation}
          </span>
          <span className={`chip ${isSourceDeficient ? 'chip-fail' : 'chip-pass'}`}>
            SOURCES: {result.sources_retrieved} GATHERED / {result.sources_required} REQ ({isSourceDeficient ? 'DEFICIENT' : 'SUFFICIENT'})
          </span>
          <span className={`chip ${result.reviewer_independence === 'INDEPENDENT' ? 'chip-pass' : 'chip-amber'}`}>
            INDEPENDENCE: {result.reviewer_independence || 'NOT_REVIEWED'}
          </span>
        </div>

        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {result.review_reasons && result.review_reasons.length > 0 && onToggleReasons && (
            <button
              type="button"
              className={`btn-tech ${showReasons ? 'btn-tech-primary' : ''}`}
              onClick={onToggleReasons}
              style={{ fontSize: '0.75rem' }}
            >
              <AlertTriangle size={12} />
              <span>[QUALITY BREAKDOWN ({result.review_reasons.length})]</span>
            </button>
          )}
          <button type="button" className="btn-tech" onClick={onReset} style={{ fontSize: '0.75rem' }}>
            [NEW SPEC]
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem', fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: 'var(--text-secondary)', borderTop: '1px solid var(--border-subtle)', paddingTop: '0.45rem' }}>
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <span>
            <strong>BODY:</strong> {result.actual_body_words} / {result.target_words} words ({wordPass ? 'PASS' : 'WARN'})
          </span>
          <span>•</span>
          <span>
            <strong>OUTLINE:</strong> {result.present_outline_topics}/{result.required_outline_topics} ({outlinePass ? '100%' : 'DEFICIENT'})
          </span>
          <span>•</span>
          <span>
            <strong>CITED:</strong> {result.sources_used} sources cited in text
          </span>
          <span>•</span>
          <span>
            <strong>CLAIMS:</strong> {result.supported_claims} verified ({result.unsupported_claims} unsupported)
          </span>
        </div>

        {result.meaning_reviewer_provider && (
          <div style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>
            Reviewer: <strong>{result.meaning_reviewer_provider}</strong> (Adversarial Scrutiny)
          </div>
        )}
      </div>
    </div>
  );
};
