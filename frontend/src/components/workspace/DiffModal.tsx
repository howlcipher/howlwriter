import React from 'react';
import { X, Check, Copy, ArrowRight, Columns, AlignJustify } from 'lucide-react';
import { HumanizeResponse } from '../../types';

interface DiffModalProps {
  isOpen: boolean;
  onClose: () => void;
  humanizeResult: HumanizeResponse | null;
  onAccept: (transformedText: string) => void;
}

export const DiffModal: React.FC<DiffModalProps> = ({
  isOpen,
  onClose,
  humanizeResult,
  onAccept,
}) => {
  const [viewMode, setViewMode] = React.useState<'split' | 'unified'>('split');
  const [copied, setCopied] = React.useState(false);

  if (!isOpen || !humanizeResult) return null;

  const copyTransformed = () => {
    navigator.clipboard.writeText(humanizeResult.transformed_text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const isReady = humanizeResult.status === 'READY';
  const meaningPass = humanizeResult.meaning_preservation_status === 'PASS';

  return (
    <div className="modal-overlay">
      <div className="modal-card" style={{ width: '920px' }}>
        <div className="modal-header">
          <div className="modal-title">
            HUMANIZE REVIEW // DIFF & MEANING VERIFICATION
          </div>
          <button type="button" className="btn-drawer-close" onClick={onClose}>
            <X size={14} /> [CLOSE]
          </button>
        </div>

        {/* Verification Summary Banner */}
        <div style={{ padding: '0.65rem 1.25rem', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <span className={`chip ${isReady ? 'chip-pass' : 'chip-require'}`} style={{ fontSize: '0.8rem' }}>
              STATUS: {humanizeResult.status}
            </span>
            <span className={`chip ${meaningPass ? 'chip-pass' : 'chip-fail'}`}>
              MEANING: {humanizeResult.meaning_preservation_status}
            </span>
            <span className={`chip ${humanizeResult.independence_status === 'INDEPENDENT' ? 'chip-pass' : 'chip-amber'}`}>
              REVIEWER: {humanizeResult.independence_status}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <button
              type="button"
              className={`btn-tech ${viewMode === 'split' ? 'active' : ''}`}
              onClick={() => setViewMode('split')}
              style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
            >
              <Columns size={12} /> SPLIT
            </button>
            <button
              type="button"
              className={`btn-tech ${viewMode === 'unified' ? 'active' : ''}`}
              onClick={() => setViewMode('unified')}
              style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
            >
              <AlignJustify size={12} /> UNIFIED
            </button>
          </div>
        </div>

        <div className="modal-body">
          {/* Lint Improvement Comparison */}
          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', padding: '0.65rem 0.85rem', marginBottom: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
            <div style={{ fontSize: '0.8rem', fontFamily: 'var(--font-mono)' }}>
              <strong>LINT BEFORE:</strong> {humanizeResult.lint_before.length} warnings
            </div>
            <ArrowRight size={14} color="var(--color-cyan)" />
            <div style={{ fontSize: '0.8rem', fontFamily: 'var(--font-mono)', color: 'var(--color-cyan)' }}>
              <strong>LINT AFTER:</strong> {humanizeResult.lint_after.length} warnings
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
              RUN ID: {humanizeResult.run_id} ({humanizeResult.duration_seconds.toFixed(2)}s)
            </div>
          </div>

          {/* Rationale / Changes Description */}
          {humanizeResult.rationale && (
            <div style={{ marginBottom: '1rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              <strong>Transformation Strategy:</strong> {humanizeResult.rationale}
            </div>
          )}

          {/* Diff View Area */}
          <div className="diff-container">
            {viewMode === 'split' ? (
              <div className="diff-split">
                <div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', fontWeight: 700, padding: '0.3rem 0.5rem', background: 'var(--bg-header-band)', color: 'var(--text-on-dark)' }}>
                    ORIGINAL DRAFT
                  </div>
                  <div className="diff-pane" style={{ borderTop: 'none' }}>
                    {humanizeResult.original_text}
                  </div>
                </div>

                <div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', fontWeight: 700, padding: '0.3rem 0.5rem', background: 'var(--bg-header-band)', color: 'var(--howl-cyan)' }}>
                    HUMANIZED PROSE
                  </div>
                  <div className="diff-pane" style={{ borderTop: 'none', borderLeft: '2px solid var(--color-cyan)' }}>
                    {humanizeResult.transformed_text}
                  </div>
                </div>
              </div>
            ) : (
              <div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', fontWeight: 700, padding: '0.3rem 0.5rem', background: 'var(--bg-header-band)', color: 'var(--text-on-dark)' }}>
                  TRANSFORMED RESULT
                </div>
                <div className="diff-pane" style={{ borderTop: 'none' }}>
                  {humanizeResult.transformed_text}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="modal-footer">
          <button
            type="button"
            className="btn-tech"
            onClick={copyTransformed}
          >
            {copied ? <Check size={14} color="var(--color-cyan)" /> : <Copy size={14} />}
            <span>{copied ? 'COPIED' : '[COPY TRANSFORMED]'}</span>
          </button>
          <button
            type="button"
            className="btn-tech"
            onClick={onClose}
          >
            [KEEP ORIGINAL]
          </button>
          <button
            type="button"
            className="btn-tech btn-tech-success"
            onClick={() => {
              onAccept(humanizeResult.transformed_text);
              onClose();
            }}
          >
            <Check size={14} />
            <span>[ACCEPT CHANGES]</span>
          </button>
        </div>
      </div>
    </div>
  );
};
