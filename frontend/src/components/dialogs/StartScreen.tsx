import React from 'react';
import { FilePlus, FolderOpen, BookOpen, Activity, X } from 'lucide-react';

interface StartScreenProps {
  isOpen: boolean;
  onClose: () => void;
  onNewDoc: () => void;
  onOpenDoc: () => void;
  onAcademic: () => void;
  onRuns: () => void;
  onProviders: () => void;
}

export const StartScreen: React.FC<StartScreenProps> = ({
  isOpen,
  onClose,
  onNewDoc,
  onOpenDoc,
  onAcademic,
  onRuns,
}) => {
  if (!isOpen) return null;

  return (
    <div className="modal-overlay">
      <div className="modal-card" style={{ width: '760px' }}>
        <div className="modal-header">
          <div className="modal-title">
            HOWL // WRITER [CONTROL PLANE]
          </div>
          <button type="button" className="btn-drawer-close" onClick={onClose}>
            <X size={14} /> [CLOSE]
          </button>
        </div>

        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          <div style={{ background: 'var(--bg-surface)', padding: '1rem', border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '1.1rem', color: 'var(--text-primary)', marginBottom: '0.35rem' }}>
              Writing Control System, Humanization & Verification Interface
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.88rem', lineHeight: 1.5 }}>
              Deterministic style linting, independent semantic review, verifiable claim-to-evidence academic pipeline, and local durable run diagnostics.
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.85rem' }}>
            <button
              type="button"
              className="drawer-node-card active-hub"
              onClick={() => { onClose(); onNewDoc(); }}
              style={{ textAlign: 'left', cursor: 'pointer', border: '1px solid var(--border-medium)' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem', color: 'var(--color-cyan)', fontWeight: 700 }}>
                <FilePlus size={16} /> [NEW DOCUMENT]
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Open a blank markdown editor buffer for drafting, linting, and humanizing.
              </div>
            </button>

            <button
              type="button"
              className="drawer-node-card"
              onClick={() => { onClose(); onOpenDoc(); }}
              style={{ textAlign: 'left', cursor: 'pointer', border: '1px solid var(--border-medium)' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem', color: 'var(--color-blue)', fontWeight: 700 }}>
                <FolderOpen size={16} /> [OPEN LOCAL FILE]
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Load an existing markdown or text file from the local filesystem.
              </div>
            </button>

            <button
              type="button"
              className="drawer-node-card"
              onClick={() => { onClose(); onAcademic(); }}
              style={{ textAlign: 'left', cursor: 'pointer', border: '1px solid var(--border-medium)' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem', color: 'var(--color-magenta)', fontWeight: 700 }}>
                <BookOpen size={16} /> [ACADEMIC PAPER]
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Build an AssignmentSpec form, discover scholarly sources, and verify claims.
              </div>
            </button>

            <button
              type="button"
              className="drawer-node-card"
              onClick={() => { onClose(); onRuns(); }}
              style={{ textAlign: 'left', cursor: 'pointer', border: '1px solid var(--border-medium)' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem', color: 'var(--color-amber)', fontWeight: 700 }}>
                <Activity size={16} /> [RECENT RUNS]
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Inspect execution history and diagnostic run records in ~/.howlwriter/runs/.
              </div>
            </button>
          </div>
        </div>

        <div className="modal-footer">
          <button type="button" className="btn-tech btn-tech-primary" onClick={onClose}>
            [ENTER WORKSPACE]
          </button>
        </div>
      </div>
    </div>
  );
};
