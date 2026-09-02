import React from 'react';
import { X, Copy, Check, Activity } from 'lucide-react';
import { RunRecord } from '../../types';

interface RunDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  record: RunRecord | null;
}

export const RunDetailModal: React.FC<RunDetailModalProps> = ({
  isOpen,
  onClose,
  record,
}) => {
  const [copied, setCopied] = React.useState(false);

  if (!isOpen || !record) return null;

  const copyJson = () => {
    navigator.clipboard.writeText(JSON.stringify(record, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="modal-overlay">
      <div className="modal-card" style={{ width: '800px' }}>
        <div className="modal-header">
          <div className="modal-title">
            <Activity size={15} style={{ display: 'inline', marginRight: '0.4rem' }} />
            RUN DIAGNOSTIC RECORD // {record.run_id}
          </div>
          <button type="button" className="btn-drawer-close" onClick={onClose}>
            <X size={14} /> [CLOSE]
          </button>
        </div>

        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.75rem', background: 'var(--bg-surface)', padding: '0.75rem', border: '1px solid var(--border-subtle)' }}>
            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>COMMAND:</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{record.command}</div>
            </div>
            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>STATUS:</div>
              <div>
                <span className={`chip ${record.status === 'READY' ? 'chip-pass' : 'chip-require'}`}>
                  {record.status}
                </span>
              </div>
            </div>
            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>HUMANIZER:</div>
              <div style={{ fontFamily: 'var(--font-mono)' }}>{record.humanizer_provider || 'deterministic'}</div>
            </div>
            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>REVIEWER:</div>
              <div style={{ fontFamily: 'var(--font-mono)' }}>{record.meaning_reviewer_provider || 'deterministic'}</div>
            </div>
            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>INDEPENDENCE:</div>
              <div style={{ fontFamily: 'var(--font-mono)' }}>{record.reviewer_independence || 'N/A'}</div>
            </div>
            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>DURATION:</div>
              <div style={{ fontFamily: 'var(--font-mono)' }}>{record.total_duration_seconds ? `${record.total_duration_seconds.toFixed(2)}s` : 'N/A'}</div>
            </div>
          </div>

          <pre
            style={{
              background: 'var(--bg-code)',
              color: 'var(--text-code)',
              padding: '1rem',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.8rem',
              overflowX: 'auto',
              maxHeight: '380px',
              border: '1px solid var(--border-medium)',
            }}
          >
            {JSON.stringify(record, null, 2)}
          </pre>
        </div>

        <div className="modal-footer">
          <button type="button" className="btn-tech" onClick={copyJson}>
            {copied ? <Check size={14} color="var(--color-cyan)" /> : <Copy size={14} />}
            <span>{copied ? 'COPIED' : '[COPY JSON]'}</span>
          </button>
          <button type="button" className="btn-tech btn-tech-primary" onClick={onClose}>
            [CLOSE]
          </button>
        </div>
      </div>
    </div>
  );
};
