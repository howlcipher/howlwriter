import React from 'react';
import { Shield, RefreshCw } from 'lucide-react';
import { ProvidersResponse } from '../../types';
import { ReviewerIndependenceCard } from './ReviewerIndependenceCard';
import { SystemBackendsCard } from './SystemBackendsCard';
import { api } from '../../api/client';

export const ProviderMatrix: React.FC = () => {
  const [data, setData] = React.useState<ProvidersResponse | null>(null);
  const [isLoading, setIsLoading] = React.useState(false);

  const fetchProviders = async () => {
    setIsLoading(true);
    try {
      const res = await api.getProviders();
      setData(res);
    } catch (err) {
      console.error('Failed to fetch providers:', err);
    } finally {
      setIsLoading(false);
    }
  };

  React.useEffect(() => {
    fetchProviders();
  }, []);

  if (!data) {
    return (
      <div className="tech-panel" style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <RefreshCw size={24} className="spin" style={{ animation: 'spin 1s linear infinite' }} />
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', height: '100%', overflowY: 'auto' }}>
      <ReviewerIndependenceCard
        status={data.reviewer_independence}
        reason={data.reviewer_independence_reason}
      />

      {/* Role Bindings Table */}
      <div className="tech-panel">
        <div className="tech-header">
          <h3><Shield size={16} /> HOWLPLANE WRITING ROLE BINDINGS</h3>
          <button
            type="button"
            className="btn-tech"
            onClick={fetchProviders}
            disabled={isLoading}
            style={{ fontSize: '0.75rem' }}
          >
            <RefreshCw size={12} className={isLoading ? 'spin' : ''} style={{ animation: isLoading ? 'spin 1s linear infinite' : 'none' }} />
            <span>[REFRESH]</span>
          </button>
        </div>

        <div className="tech-body" style={{ padding: 0 }}>
          <div className="table-wrap" style={{ margin: 0, border: 'none' }}>
            <table>
              <thead>
                <tr>
                  <th>ROLE</th>
                  <th>BOUND PROVIDER</th>
                  <th>MODEL TARGET</th>
                  <th>TIMEOUT</th>
                  <th>STATUS</th>
                  <th>ROLE DESCRIPTION</th>
                </tr>
              </thead>
              <tbody>
                {data.role_bindings.map((rb) => (
                  <tr key={rb.role}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--text-primary)' }}>
                      {rb.role_label}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-cyan)', fontWeight: 600 }}>
                      {rb.provider || 'default (deterministic)'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>
                      {rb.model || 'default'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>
                      {rb.timeout_seconds}s
                    </td>
                    <td>
                      <span className={`chip ${rb.is_configured ? 'chip-pass' : 'chip-neutral'}`} style={{ fontSize: '0.65rem' }}>
                        {rb.is_configured ? 'BOUND' : 'DEFAULT'}
                      </span>
                    </td>
                    <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                      {rb.description}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <SystemBackendsCard providers={data.available_providers} />
    </div>
  );
};
