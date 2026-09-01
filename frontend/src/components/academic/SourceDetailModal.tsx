import React from 'react';
import { X, ExternalLink } from 'lucide-react';
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

  return (
    <div className="modal-overlay">
      <div className="modal-card" style={{ width: '740px' }}>
        <div className="modal-header">
          <div className="modal-title">
            SOURCE PROVENANCE DETAIL // {source.id}
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
              <strong>Authors:</strong> {source.authors.join(', ') || 'Unknown Author'}
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
            <span className="chip chip-blue">CLAIMS CITED: {source.claims_count}</span>
            <span className="chip chip-cyan">IN-TEXT CITED: {source.in_text_citations_count}</span>
            <span className="chip chip-amber">ORIGIN: {source.evidence_origin || 'METADATA'}</span>
          </div>

          {source.retrieved_text && (
            <div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                RETRIEVED EXCERPT / ABSTRACT:
              </div>
              <div
                style={{
                  background: 'var(--bg-sunken)',
                  border: '1px solid var(--border-medium)',
                  padding: '0.75rem',
                  fontSize: '0.85rem',
                  color: 'var(--text-primary)',
                  maxHeight: '220px',
                  overflowY: 'auto',
                  lineHeight: 1.5,
                  whiteSpace: 'pre-wrap',
                }}
              >
                {source.retrieved_text}
              </div>
            </div>
          )}

          {source.url && (
            <div style={{ marginTop: '0.5rem' }}>
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-tech btn-tech-primary"
                style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}
              >
                <span>OPEN EXTERNAL SOURCE URL</span>
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
