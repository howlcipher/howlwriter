import React from 'react';
import { Activity, RefreshCw, Eye } from 'lucide-react';
import { RunRecord } from '../../types';
import { RunDetailModal } from './RunDetailModal';
import { api } from '../../api/client';

export const RunsLedger: React.FC = () => {
  const [runs, setRuns] = React.useState<RunRecord[]>([]);
  const [isLoading, setIsLoading] = React.useState(false);
  const [selectedRecord, setSelectedRecord] = React.useState<RunRecord | null>(null);

  const fetchRuns = async () => {
    setIsLoading(true);
    try {
      const data = await api.listRuns(50);
      setRuns(data);
    } catch (err) {
      console.error('Failed to fetch runs:', err);
    } finally {
      setIsLoading(false);
    }
  };

  React.useEffect(() => {
    fetchRuns();
  }, []);

  return (
    <div className="tech-panel" style={{ height: '100%' }}>
      <div className="tech-header">
        <h3><Activity size={16} /> RECENT LOCAL RUNS LEDGER (~/.howlwriter/runs/)</h3>
        <button
          type="button"
          className="btn-tech"
          onClick={fetchRuns}
          disabled={isLoading}
          style={{ fontSize: '0.75rem' }}
        >
          <RefreshCw size={12} className={isLoading ? 'spin' : ''} style={{ animation: isLoading ? 'spin 1s linear infinite' : 'none' }} />
          <span>[REFRESH]</span>
        </button>
      </div>

      <div className="tech-body" style={{ padding: 0 }}>
        {runs.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-dim)', fontSize: '0.9rem' }}>
            No recent run records found on this machine.
          </div>
        ) : (
          <div className="table-wrap" style={{ margin: 0, border: 'none' }}>
            <table>
              <thead>
                <tr>
                  <th>RUN ID</th>
                  <th>TIMESTAMP</th>
                  <th>COMMAND</th>
                  <th>STATUS</th>
                  <th>HUMANIZER</th>
                  <th>REVIEWER</th>
                  <th>INDEPENDENCE</th>
                  <th>DURATION</th>
                  <th>ACTIONS</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => {
                  const isReady = r.status === 'READY';
                  return (
                    <tr key={r.run_id}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--color-cyan)' }}>
                        {r.run_id}
                      </td>
                      <td style={{ fontSize: '0.75rem', whiteSpace: 'nowrap' }}>
                        {r.timestamp.substring(0, 19).replace('T', ' ')}
                      </td>
                      <td>
                        <span className="chip chip-neutral" style={{ fontSize: '0.65rem' }}>{r.command}</span>
                      </td>
                      <td>
                        <span className={`chip ${isReady ? 'chip-pass' : 'chip-require'}`} style={{ fontSize: '0.65rem' }}>
                          {r.status}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>
                        {r.humanizer_provider || 'deterministic'}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>
                        {r.meaning_reviewer_provider || 'deterministic'}
                      </td>
                      <td>
                        <span className={`chip ${r.reviewer_independence === 'INDEPENDENT' ? 'chip-pass' : 'chip-neutral'}`} style={{ fontSize: '0.65rem' }}>
                          {r.reviewer_independence || 'N/A'}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>
                        {r.total_duration_seconds ? `${r.total_duration_seconds.toFixed(2)}s` : '—'}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn-tech"
                          onClick={() => setSelectedRecord(r)}
                          style={{ padding: '0.2rem 0.4rem', fontSize: '0.68rem' }}
                        >
                          <Eye size={11} /> [INSPECT]
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <RunDetailModal
        isOpen={selectedRecord !== null}
        onClose={() => setSelectedRecord(null)}
        record={selectedRecord}
      />
    </div>
  );
};
