import React from 'react';
import { ShieldCheck, Copy, Check } from 'lucide-react';

interface SiteFooterProps {
  currentRunId?: string | null;
  activeFilePath?: string | null;
  wordCount: number;
}

export const SiteFooter: React.FC<SiteFooterProps> = ({
  currentRunId,
  activeFilePath,
  wordCount,
}) => {
  const [copied, setCopied] = React.useState(false);

  const copyRunId = () => {
    if (currentRunId) {
      navigator.clipboard.writeText(currentRunId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <footer className="site-footer">
      <div className="status-indicator">
        <span className="status-dot" />
        <span>HOWLWRITER LOCAL // 127.0.0.1:8765</span>
        <span style={{ color: 'var(--howl-cyan)' }}>•</span>
        <span>WORDS: {wordCount}</span>
        {activeFilePath && (
          <>
            <span style={{ color: 'var(--howl-cyan)' }}>•</span>
            <span style={{ color: 'var(--howl-shell)', opacity: 0.85 }}>FILE: {activeFilePath}</span>
          </>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        {currentRunId && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <span style={{ color: 'var(--howl-cyan)', fontWeight: 700 }}>RUN:</span>
            <code style={{ background: 'var(--howl-navy)', color: 'var(--howl-shell)', border: '1px solid var(--border-subtle)', padding: '0.1rem 0.35rem' }}>
              {currentRunId}
            </code>
            <button
              type="button"
              className="btn-copy"
              onClick={copyRunId}
              title="Copy active Run ID"
              style={{ display: 'inline-flex', alignItems: 'center', gap: '0.2rem' }}
            >
              {copied ? <Check size={11} color="var(--color-cyan)" /> : <Copy size={11} />}
              {copied ? 'COPIED' : 'COPY'}
            </button>
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--text-dim)', fontSize: '0.72rem' }}>
          <ShieldCheck size={13} color="var(--howl-cyan)" />
          <span>LOCAL & PRIVACY PRESERVED (NO CLOUD SYNC)</span>
        </div>
      </div>
    </footer>
  );
};
