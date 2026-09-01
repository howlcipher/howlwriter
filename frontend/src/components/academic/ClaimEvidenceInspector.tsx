import React from 'react';
import { ShieldCheck, ExternalLink } from 'lucide-react';
import { Claim, Source } from '../../types';

interface ClaimEvidenceInspectorProps {
  claims: Claim[];
  sources: Source[];
  onOpenSourceModal: (source: Source) => void;
}

export const ClaimEvidenceInspector: React.FC<ClaimEvidenceInspectorProps> = ({
  claims,
  sources,
  onOpenSourceModal,
}) => {
  const [selectedClaimId, setSelectedClaimId] = React.useState<string | null>(
    claims.length > 0 ? claims[0].id : null
  );
  const [verdictFilter, setVerdictFilter] = React.useState<string>('ALL');

  const sourceMap = React.useMemo(() => {
    const map = new Map<string, Source>();
    sources.forEach((s) => map.set(s.id, s));
    return map;
  }, [sources]);

  const filteredClaims = claims.filter((c) => {
    if (verdictFilter === 'ALL') return true;
    return c.verdict === verdictFilter;
  });

  const selectedClaim = claims.find((c) => c.id === selectedClaimId) || (claims.length > 0 ? claims[0] : null);

  const getVerdictChipClass = (verdict: string) => {
    switch (verdict) {
      case 'SUPPORTED':
        return 'chip-pass';
      case 'PARTIALLY_SUPPORTED':
        return 'chip-require';
      case 'UNSUPPORTED':
      case 'CONTRADICTED':
        return 'chip-fail';
      default:
        return 'chip-neutral';
    }
  };

  const getOriginBadge = (origin: string) => {
    switch (origin) {
      case 'FULL_TEXT':
        return { label: 'FULL_TEXT', chipClass: 'chip-pass', desc: 'Full paper body text retrieved & inspected' };
      case 'ABSTRACT':
        return { label: 'ABSTRACT', chipClass: 'chip-blue', desc: 'Abstract only — full text was not retrieved' };
      case 'METADATA_ONLY':
        return { label: 'METADATA_ONLY', chipClass: 'chip-amber', desc: 'Metadata only — no body or abstract text' };
      default:
        return { label: 'OTHER', chipClass: 'chip-neutral', desc: 'Excerpt / other origin' };
    }
  };

  return (
    <div className="tech-panel" style={{ height: '100%' }}>
      <div className="tech-header">
        <h3><ShieldCheck size={16} /> CLAIM ↔ EVIDENCE ↔ SOURCE INSPECTOR</h3>
        <span className="sec-id">{claims.length} CLAIMS AUDITED</span>
      </div>

      {/* Filter Toolbar */}
      <div style={{ padding: '0.45rem 0.75rem', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)', display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
        {['ALL', 'SUPPORTED', 'PARTIALLY_SUPPORTED', 'UNSUPPORTED'].map((v) => (
          <button
            key={v}
            type="button"
            className={`chip ${verdictFilter === v ? 'chip-blue' : 'chip-neutral'}`}
            onClick={() => setVerdictFilter(v)}
            style={{ cursor: 'pointer', fontSize: '0.7rem' }}
          >
            {v.replace('_', ' ')}: {v === 'ALL' ? claims.length : claims.filter((c) => c.verdict === v).length}
          </button>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', flex: 1, overflow: 'hidden' }}>
        {/* Claims Master List */}
        <div style={{ borderRight: '1px solid var(--border-subtle)', overflowY: 'auto', padding: '0.65rem' }}>
          {filteredClaims.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '1rem', color: 'var(--text-dim)', fontSize: '0.8rem' }}>
              No claims match current filter.
            </div>
          ) : (
            filteredClaims.map((c) => {
              const isSelected = selectedClaim?.id === c.id;
              return (
                <div
                  key={c.id}
                  className={`claim-card ${isSelected ? 'selected' : ''}`}
                  onClick={() => setSelectedClaimId(c.id)}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
                    <span className={`chip ${getVerdictChipClass(c.verdict)}`} style={{ fontSize: '0.65rem' }}>
                      {c.verdict}
                    </span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-dim)' }}>
                      {c.evidence.length} EV
                    </span>
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-primary)', lineClamp: 2, overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                    {c.claim_text}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Claim Detail & Provenance Inspector */}
        <div style={{ padding: '1rem', overflowY: 'auto' }}>
          {selectedClaim ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {/* Claim Statement Box */}
              <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-medium)', padding: '0.85rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <span className="chip chip-blue" style={{ fontSize: '0.7rem' }}>CLAIM STATEMENT</span>
                  <span className={`chip ${getVerdictChipClass(selectedClaim.verdict)}`} style={{ fontSize: '0.75rem' }}>
                    VERDICT: {selectedClaim.verdict}
                  </span>
                </div>
                <div style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.5 }}>
                  "{selectedClaim.claim_text}"
                </div>
                {selectedClaim.reasoning && (
                  <div style={{ marginTop: '0.5rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    <strong>Verifier Reasoning:</strong> {selectedClaim.reasoning}
                  </div>
                )}
              </div>

              {/* Attached Evidence & Origin */}
              <div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                  ATTACHED EVIDENCE PASSAGES ({selectedClaim.evidence.length})
                </div>

                {selectedClaim.evidence.length === 0 ? (
                  <div style={{ background: 'rgba(217, 71, 50, 0.08)', border: '1px solid var(--color-red)', padding: '0.75rem', fontSize: '0.8rem', color: 'var(--color-red)' }}>
                    No supporting evidence extracted. Claim marked {selectedClaim.verdict}.
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    {selectedClaim.evidence.map((ev, i) => {
                      const src = sourceMap.get(ev.source_id);
                      const originMeta = getOriginBadge(ev.origin_type);

                      return (
                        <div
                          key={ev.id || i}
                          style={{
                            background: 'var(--bg-panel)',
                            border: '1px solid var(--border-medium)',
                            padding: '0.85rem',
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                              <span className="chip chip-blue" style={{ fontSize: '0.65rem' }}>{ev.source_id}</span>
                              <span className={`chip ${originMeta.chipClass}`} style={{ fontSize: '0.65rem' }}>
                                ORIGIN: {originMeta.label}
                              </span>
                            </div>
                            {src && (
                              <button
                                type="button"
                                className="btn-tech"
                                onClick={() => onOpenSourceModal(src)}
                                style={{ padding: '0.2rem 0.45rem', fontSize: '0.7rem' }}
                              >
                                [VIEW SOURCE & METADATA]
                              </button>
                            )}
                          </div>

                          <div className="evidence-box">
                            "{ev.excerpt}"
                          </div>

                          <div style={{ fontSize: '0.72rem', color: 'var(--text-dim)', marginBottom: '0.35rem' }}>
                            {originMeta.desc}
                          </div>

                          {src && (
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '0.4rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                              <span>{src.authors.join(', ') || 'No author listed'} ({src.publication_date?.substring(0, 4) || 'n.d.'})</span>
                              {src.url && (
                                <a
                                  href={src.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  style={{ color: 'var(--color-cyan)', display: 'inline-flex', alignItems: 'center', gap: '0.2rem', textDecoration: 'none', fontWeight: 600 }}
                                >
                                  <span>OPEN SOURCE LINK</span> <ExternalLink size={11} />
                                </a>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Truthful Evidence Origin Notice */}
              <div style={{ background: 'var(--bg-sunken)', border: '1px solid var(--border-subtle)', padding: '0.65rem 0.85rem', fontSize: '0.75rem', color: 'var(--text-dim)', lineHeight: 1.4 }}>
                <strong>Truthful Evidence Grounding:</strong> Evidence origins (FULL_TEXT, ABSTRACT, METADATA_ONLY) reflect what HowlWriter actually inspected. Papers with ABSTRACT or METADATA_ONLY origins are not represented as full-text verified.
              </div>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-dim)' }}>
              Select a claim to inspect its attached evidence and source provenance.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
