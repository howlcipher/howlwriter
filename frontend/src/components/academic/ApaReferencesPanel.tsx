import React from 'react';
import { Quote, Copy, Check } from 'lucide-react';

interface ApaReferencesPanelProps {
  referencesText: string;
  citationWarnings?: string[];
}

export const ApaReferencesPanel: React.FC<ApaReferencesPanelProps> = ({
  referencesText,
  citationWarnings = [],
}) => {
  const [copied, setCopied] = React.useState(false);

  const copyReferences = () => {
    navigator.clipboard.writeText(referencesText);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="tech-panel" style={{ height: '100%' }}>
      <div className="tech-header">
        <h3><Quote size={16} /> APA 7 REFERENCES</h3>
        <button type="button" className="btn-tech" onClick={copyReferences} style={{ fontSize: '0.75rem' }}>
          {copied ? <Check size={12} color="var(--color-cyan)" /> : <Copy size={12} />}
          <span>{copied ? 'COPIED' : '[COPY REFERENCES]'}</span>
        </button>
      </div>

      <div className="tech-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {citationWarnings.length > 0 && (
          <div style={{ background: 'rgba(242, 169, 27, 0.1)', border: '1px solid var(--color-amber)', padding: '0.6rem 0.8rem', fontSize: '0.75rem', color: 'var(--color-amber)' }}>
            <strong>Citation Metadata Notices:</strong>
            <ul style={{ margin: '0.2rem 0 0 1.25rem' }}>
              {citationWarnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </div>
        )}

        <pre
          style={{
            background: 'var(--bg-panel)',
            border: '1px solid var(--border-medium)',
            padding: '1.25rem',
            fontFamily: 'var(--font-sans)',
            fontSize: '0.9rem',
            lineHeight: 1.7,
            whiteSpace: 'pre-wrap',
            color: 'var(--text-primary)',
          }}
        >
          {referencesText || 'No references generated yet.'}
        </pre>
      </div>
    </div>
  );
};
