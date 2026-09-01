import React from 'react';
import { X, Copy, Check } from 'lucide-react';

interface YamlPreviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  yamlContent: string;
}

export const YamlPreviewModal: React.FC<YamlPreviewModalProps> = ({
  isOpen,
  onClose,
  yamlContent,
}) => {
  const [copied, setCopied] = React.useState(false);

  if (!isOpen) return null;

  const copyYaml = () => {
    navigator.clipboard.writeText(yamlContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="modal-overlay">
      <div className="modal-card" style={{ width: '680px' }}>
        <div className="modal-header">
          <div className="modal-title">ASSIGNMENT SPEC // YAML REPRESENTATION</div>
          <button type="button" className="btn-drawer-close" onClick={onClose}>
            <X size={14} /> [CLOSE]
          </button>
        </div>
        <div className="modal-body">
          <pre
            style={{
              background: 'var(--bg-code)',
              color: 'var(--text-code)',
              padding: '1rem',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.82rem',
              overflowX: 'auto',
              maxHeight: '480px',
              border: '1px solid var(--border-medium)',
            }}
          >
            {yamlContent}
          </pre>
        </div>
        <div className="modal-footer">
          <button type="button" className="btn-tech" onClick={copyYaml}>
            {copied ? <Check size={14} color="var(--color-cyan)" /> : <Copy size={14} />}
            <span>{copied ? 'COPIED' : '[COPY YAML]'}</span>
          </button>
          <button type="button" className="btn-tech btn-tech-primary" onClick={onClose}>
            [CLOSE]
          </button>
        </div>
      </div>
    </div>
  );
};
