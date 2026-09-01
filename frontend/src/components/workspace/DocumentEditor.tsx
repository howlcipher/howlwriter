import React from 'react';
import { FileCode, Type } from 'lucide-react';
import { WritingMode } from '../../types';

interface DocumentEditorProps {
  title: string;
  setTitle: (title: string) => void;
  content: string;
  setContent: (content: string) => void;
  mode: WritingMode;
  setMode: (mode: WritingMode) => void;
  isDirty: boolean;
  activeFilePath?: string | null;
}

export const DocumentEditor: React.FC<DocumentEditorProps> = ({
  title,
  setTitle,
  content,
  setContent,
  mode,
  setMode,
  isDirty,
  activeFilePath,
}) => {
  const [useMonospace, setUseMonospace] = React.useState(false);

  const lines = React.useMemo(() => content.split('\n').length, [content]);
  const chars = content.length;
  const words = React.useMemo(() => {
    const trimmed = content.trim();
    return trimmed ? trimmed.split(/\s+/).length : 0;
  }, [content]);

  return (
    <div className="editor-wrapper">
      <div className="action-bar" style={{ borderTop: 'none', borderLeft: 'none', borderRight: 'none' }}>
        <div className="action-bar-group" style={{ flex: 1 }}>
          <input
            type="text"
            className="form-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Document Title (e.g. quantum-computing-overview.md)"
            style={{ fontWeight: 700, minWidth: '260px', flex: 1 }}
          />
          {isDirty && <span className="chip chip-amber">[UNSAVED]</span>}
        </div>

        <div className="action-bar-group">
          <select
            className="form-select"
            value={mode}
            onChange={(e) => setMode(e.target.value as WritingMode)}
            title="Writing Mode Profile"
            style={{ fontSize: '0.75rem', padding: '0.3rem 0.5rem' }}
          >
            <option value="article">Mode: Article</option>
            <option value="academic">Mode: Academic</option>
            <option value="casual">Mode: Casual</option>
            <option value="professional">Mode: Professional</option>
            <option value="technical">Mode: Technical</option>
            <option value="documentation">Mode: Documentation</option>
            <option value="email">Mode: Email</option>
            <option value="linkedin">Mode: LinkedIn</option>
          </select>

          <button
            type="button"
            className="btn-tech"
            onClick={() => setUseMonospace(!useMonospace)}
            title="Toggle Monospace / Sans-Serif font"
            style={{ padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}
          >
            {useMonospace ? <Type size={13} /> : <FileCode size={13} />}
            <span>{useMonospace ? 'SANS' : 'MONO'}</span>
          </button>
        </div>
      </div>

      <textarea
        className="editor-textarea"
        style={{ fontFamily: useMonospace ? 'var(--font-mono)' : 'var(--font-sans)', fontSize: useMonospace ? '0.9rem' : '1.02rem' }}
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Type or paste your markdown / draft prose here to begin writing, linting, or humanizing..."
        spellCheck="false"
      />

      <div className="editor-footer">
        <div style={{ display: 'flex', gap: '1rem' }}>
          <span>LINES: {lines}</span>
          <span>WORDS: {words}</span>
          <span>CHARS: {chars}</span>
        </div>
        <div>
          {activeFilePath ? (
            <span style={{ color: 'var(--text-dim)' }}>{activeFilePath}</span>
          ) : (
            <span style={{ color: 'var(--color-amber)' }}>Buffer: Unsaved Memory</span>
          )}
        </div>
      </div>
    </div>
  );
};
