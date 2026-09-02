import React from 'react';
import { Sparkles, CheckSquare, Edit3, Flame, Save, FolderOpen, FilePlus, Loader2 } from 'lucide-react';

interface WorkspaceActionsProps {
  onLint: () => void;
  onRedPen: () => void;
  onHumanize: () => void;
  onHowl: () => void;
  onSave: () => void;
  onOpen: () => void;
  onNew: () => void;
  isLoading: boolean;
  loadingAction: string;
}

export const WorkspaceActions: React.FC<WorkspaceActionsProps> = ({
  onLint,
  onRedPen,
  onHumanize,
  onHowl,
  onSave,
  onOpen,
  onNew,
  isLoading,
  loadingAction,
}) => {
  return (
    <div className="action-bar" style={{ borderRadius: '0', borderBottom: '1px solid var(--border-medium)' }}>
      <div className="action-bar-group">
        <button
          type="button"
          className="btn-tech"
          onClick={onNew}
          disabled={isLoading}
          title="New blank document"
        >
          <FilePlus size={14} />
          <span>[NEW]</span>
        </button>
        <button
          type="button"
          className="btn-tech"
          onClick={onOpen}
          disabled={isLoading}
          title="Open local markdown file"
        >
          <FolderOpen size={14} />
          <span>[OPEN]</span>
        </button>
        <button
          type="button"
          className="btn-tech"
          onClick={onSave}
          disabled={isLoading}
          title="Save to local disk"
        >
          <Save size={14} />
          <span>[SAVE]</span>
        </button>
      </div>

      <div className="action-bar-group">
        {isLoading && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--color-cyan)' }}>
            <Loader2 size={14} className="spin" style={{ animation: 'spin 1s linear infinite' }} />
            <span>RUNNING {loadingAction.toUpperCase()}...</span>
          </div>
        )}

        <button
          type="button"
          className="btn-tech"
          onClick={onLint}
          disabled={isLoading}
          title="Run deterministic style and banned word linting"
        >
          <CheckSquare size={14} color="var(--color-cyan)" />
          <span>[LINT]</span>
        </button>

        <button
          type="button"
          className="btn-tech"
          onClick={onRedPen}
          disabled={isLoading}
          title="Run Red Pen stylistic criticism"
        >
          <Edit3 size={14} color="var(--color-red)" />
          <span>[RED PEN]</span>
        </button>

        <button
          type="button"
          className="btn-tech btn-tech-primary"
          onClick={onHumanize}
          disabled={isLoading}
          title="Humanize prose with meaning preservation review"
        >
          <Sparkles size={14} />
          <span>[HUMANIZE]</span>
        </button>

        <button
          type="button"
          className="btn-tech btn-tech-danger"
          onClick={onHowl}
          disabled={isLoading}
          title="Run complete Howl writing pipeline"
        >
          <Flame size={14} />
          <span>[HOWL IT]</span>
        </button>
      </div>
    </div>
  );
};
