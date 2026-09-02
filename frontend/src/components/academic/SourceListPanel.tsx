import React from 'react';
import { BookOpen, ExternalLink, Info } from 'lucide-react';
import { Source } from '../../types';

interface SourceListPanelProps {
  sources: Source[];
  onSelectSource: (source: Source) => void;
}

export const SourceListPanel: React.FC<SourceListPanelProps> = ({
  sources,
  onSelectSource,
}) => {
  return (
    <div className="tech-panel" style={{ height: '100%' }}>
      <div className="tech-header">
        <h3><BookOpen size={16} /> RESEARCH SOURCES ({sources.length})</h3>
        <span className="sec-id">PROVENANCE REGISTRY</span>
      </div>

      <div className="tech-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
        {sources.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '1.5rem', color: 'var(--text-dim)', fontSize: '0.85rem' }}>
            No sources gathered yet. Run the academic pipeline to discover research sources.
          </div>
        ) : (
          sources.map((s) => (
            <div
              key={s.id}
              style={{
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                padding: '0.75rem',
                fontSize: '0.82rem',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.35rem',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '0.5rem' }}>
                <div style={{ fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.3 }}>
                  <span className="chip chip-blue" style={{ fontSize: '0.65rem', marginRight: '0.4rem' }}>{s.id}</span>
                  {s.title}
                </div>
                <button
                  type="button"
                  className="btn-tech"
                  onClick={() => onSelectSource(s)}
                  style={{ padding: '0.2rem 0.4rem', fontSize: '0.68rem', whiteSpace: 'nowrap' }}
                >
                  <Info size={11} /> [DETAILS]
                </button>
              </div>

              <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                {s.authors.join(', ') || 'No author listed'} ({s.publication_date?.substring(0, 4) || 'n.d.'})
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '0.2rem' }}>
                <div style={{ display: 'flex', gap: '0.35rem' }}>
                  <span className={`chip ${s.relevance === 'DIRECT' || s.relevance === 'SUPPORTING' ? 'chip-pass' : s.relevance === 'TANGENTIAL' || s.relevance === 'IRRELEVANT' ? 'chip-fail' : 'chip-amber'}`} style={{ fontSize: '0.65rem' }}>
                    {s.relevance || 'DIRECT'}
                  </span>
                  <span className="chip chip-cyan" style={{ fontSize: '0.65rem' }}>
                    {s.evidence_origin || 'METADATA'}
                  </span>
                  <span className="chip chip-neutral" style={{ fontSize: '0.65rem' }}>
                    {s.claims_count} CLAIMS
                  </span>
                </div>

                {s.url && (
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: 'var(--color-cyan)', fontSize: '0.72rem', display: 'inline-flex', alignItems: 'center', gap: '0.2rem', textDecoration: 'none' }}
                  >
                    <span>OPEN LINK</span> <ExternalLink size={11} />
                  </a>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
