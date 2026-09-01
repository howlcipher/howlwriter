import React from 'react';
import { X, FolderOpen, AlertCircle } from 'lucide-react';
import { api } from '../../api/client';
import { DocumentData } from '../../types';

interface OpenFileModalProps {
  isOpen: boolean;
  onClose: () => void;
  onDocumentLoaded: (doc: DocumentData) => void;
}

export const OpenFileModal: React.FC<OpenFileModalProps> = ({
  isOpen,
  onClose,
  onDocumentLoaded,
}) => {
  const [filePath, setFilePath] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const [isLoading, setIsLoading] = React.useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!filePath.trim()) return;

    setIsLoading(true);
    setError(null);
    try {
      const doc = await api.openDocument(filePath.trim());
      onDocumentLoaded(doc);
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to open file');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-card" style={{ width: '600px' }}>
        <div className="modal-header">
          <div className="modal-title">OPEN LOCAL DOCUMENT FILE</div>
          <button type="button" className="btn-drawer-close" onClick={onClose}>
            <X size={14} /> [CLOSE]
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {error && (
              <div style={{ background: 'rgba(217, 71, 50, 0.1)', border: '1px solid var(--color-red)', padding: '0.65rem 0.85rem', fontSize: '0.8rem', color: 'var(--color-red)' }}>
                <AlertCircle size={14} style={{ display: 'inline', marginRight: '0.35rem' }} />
                {error}
              </div>
            )}

            <div className="form-group">
              <label className="form-label">FILE PATH ON LOCAL DISK</label>
              <input
                type="text"
                className="form-input"
                value={filePath}
                onChange={(e) => setFilePath(e.target.value)}
                placeholder="/path/to/my-document.md or ./draft.txt"
                required
                autoFocus
              />
              <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '0.25rem' }}>
                Enter the absolute or relative file path to load into the writing workspace.
              </div>
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn-tech" onClick={onClose} disabled={isLoading}>
              [CANCEL]
            </button>
            <button type="submit" className="btn-tech btn-tech-primary" disabled={isLoading || !filePath.trim()}>
              <FolderOpen size={13} />
              <span>{isLoading ? 'LOADING...' : '[OPEN FILE]'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
