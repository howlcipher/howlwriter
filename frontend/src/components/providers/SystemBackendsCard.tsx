import React from 'react';
import { Cpu } from 'lucide-react';
import { ProviderStatus } from '../../types';

interface SystemBackendsCardProps {
  providers: ProviderStatus[];
}

export const SystemBackendsCard: React.FC<SystemBackendsCardProps> = ({ providers }) => {
  return (
    <div className="tech-panel">
      <div className="tech-header">
        <h3><Cpu size={15} /> LOCAL CLI PROVIDER BACKENDS</h3>
        <span className="sec-id">SYSTEM PATH DISCOVERY</span>
      </div>

      <div className="tech-body" style={{ padding: '0.75rem' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '0.65rem' }}>
          {providers.map((p) => (
            <div
              key={p.id}
              style={{
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                padding: '0.65rem 0.75rem',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.35rem',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.85rem', color: 'var(--text-primary)' }}>
                  {p.name}
                </span>
                <span className={`chip ${p.is_installed ? 'chip-pass' : 'chip-neutral'}`} style={{ fontSize: '0.65rem' }}>
                  {p.is_installed ? 'INSTALLED' : 'NOT FOUND'}
                </span>
              </div>

              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                {p.description}
              </div>

              {p.command_path && (
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-dim)', background: 'var(--bg-sunken)', padding: '0.15rem 0.35rem', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {p.command_path}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
