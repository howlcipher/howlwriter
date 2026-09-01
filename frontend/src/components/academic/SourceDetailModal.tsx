import React from 'react';
import { X, ExternalLink, Database } from 'lucide-react';
import { Source } from '../../types';

interface SourceDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  source: Source | null;
}

export const SourceDetailModal: React.FC<SourceDetailModalProps> = ({
  isOpen,
  onClose,
  source,
}) => {
  if (!isOpen || !source) return null;

  const origin = source.evidence_origin || 'METADATA_ONLY';
  const getOriginBadge = () => {
    switch (origin) {
      case 'FULL_TEXT':
        return { label: 'FULL_TEXT', chipClass: 'chip-pass', desc: 'Full paper body text was retrieved and inspected.' };
      case 'ABSTRACT':
        return { label: 'ABSTRACT', chipClass: 'chip-blue', desc: 'Abstract only — full paper body was not retrieved.' };
      case 'METADATA_ONLY':
        return { label: 'METADATA_ONLY', chipClass: 'chip-amber', desc: 'Metadata only — no body or abstract text was retrieved.' };
      default:
        return { label: 'OTHER', chipClass: 'chip-neutral', desc: 'Retrieved excerpt / external reference.' };
    }
  };

  const badge = getOriginBadge();

  return (
    <div className="modal-overlay">
      <div className="modal-card" style={{ width: '780px' }}>
        <div className="modal-header">
          <div className="modal-title">
            SOURCE PROVENANCE DETAIL & UPSTREAM METADATA // {source.id}
          </div>
          <button type="button" className="btn-drawer-close" onClick={onClose}>
            <X size={14} /> [CLOSE]
          </button>
        </div>

        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '0.35rem' }}>
              {source.title}
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
              <strong>Authors:</strong> {source.authors.join(', ') || 'No author listed in upstream record'}
            </div>
            {source.publisher && (
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                <strong>Publisher / Journal:</strong> {source.publisher}
              </div>
            )}
            {source.publication_date && (
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                <strong>Publication Date:</strong> {source.publication_date}
              </div>
            )}
            {source.doi && (
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                <strong>DOI:</strong> {source.doi}
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            <span className={`chip ${badge.chipClass}`}>EVIDENCE ORIGIN: {badge.label}</span>
            <span className="chip chip-blue">CLAIMS CITED: {source.claims_count}</span>
            <span className="chip chip-cyan">IN-TEXT CITED: {source.in_text_citations_count}</span>
          </div>

          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', padding: '0.65rem 0.85rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
            <strong>Origin Assessment:</strong> {badge.desc}
          </div>

          {source.retrieved_text && (
            <div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                RETRIEVED ABSTRACT / EXCERPT ({source.retrieved_text.length} chars):
              </div>
              <div
                style={{
                  background: 'var(--bg-sunken)',
                  border: '1px solid var(--border-medium)',
                  padding: '0.75rem',
                  fontSize: '0.85rem',
                  color: 'var(--text-primary)',
                  maxHeight: '200px',
                  overflowY: 'auto',
                  lineHeight: 1.5,
                  whiteSpace: 'pre-wrap',
                }}
              >
                {source.retrieved_text}
              </div>
            </div>
          )}

          {/* Upstream Raw Metadata Transparency */}
          <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border-medium)', padding: '0.85rem' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', fontWeight: 700, color: 'var(--color-cyan)', display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.4rem' }}>
              <Database size={13} /> RAW UPSTREAM METADATA (CROSSREF / SCHOLARLY API)
            </div>

            <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '0.5rem' }}>
              Transparency Note: Citation formatting oddities (such as "n.d.", title-first positioning, or organizational authors) stem from missing upstream metadata fields, not citation-generation logic.
            </div>

            <pre
              style={{
                background: 'var(--bg-code)',
                color: 'var(--text-code)',
                padding: '0.65rem',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.75rem',
                overflowX: 'auto',
                maxHeight: '140px',
                border: '1px solid var(--border-subtle)',
              }}
            >
              {JSON.stringify(source.raw_metadata || {
                authors: source.authors,
                title: source.title,
                date: source.publication_date,
                publisher: source.publisher,
                doi: source.doi,
                url: source.url,
              }, null, 2)}
            </pre>
          </div>

          {source.url && (
            <div>
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-tech btn-tech-primary"
                style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}
              >
                <span>OPEN EXTERNAL SOURCE URL (DOI)</span>
                <ExternalLink size={13} />
              </a>
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button type="button" className="btn-tech" onClick={onClose}>
            [CLOSE]
          </button>
        </div>
      </div>
    </div>
  );
};
