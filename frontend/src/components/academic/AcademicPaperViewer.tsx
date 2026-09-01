import React from 'react';
import { Copy, Check, FileDown, BookOpen } from 'lucide-react';
import { AcademicResult } from '../../types';

interface AcademicPaperViewerProps {
  result: AcademicResult;
}

export const AcademicPaperViewer: React.FC<AcademicPaperViewerProps> = ({
  result,
}) => {
  const [copied, setCopied] = React.useState(false);

  const copyPaper = () => {
    navigator.clipboard.writeText(result.paper_text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const exportMarkdown = () => {
    const blob = new Blob([result.paper_text], { type: 'text/markdown;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `${result.title.toLowerCase().replace(/\s+/g, '_')}.md`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="tech-panel" style={{ height: '100%' }}>
      <div className="tech-header">
        <h3><BookOpen size={16} /> GENERATED ACADEMIC PAPER</h3>
        <div style={{ display: 'flex', gap: '0.4rem' }}>
          <button type="button" className="btn-tech" onClick={copyPaper} style={{ fontSize: '0.75rem' }}>
            {copied ? <Check size={12} color="var(--color-cyan)" /> : <Copy size={12} />}
            <span>{copied ? 'COPIED' : '[COPY]'}</span>
          </button>
          <button type="button" className="btn-tech" onClick={exportMarkdown} style={{ fontSize: '0.75rem' }}>
            <FileDown size={12} /> [EXPORT .MD]
          </button>
        </div>
      </div>

      <div className="tech-body" style={{ background: 'var(--bg-panel)', padding: '1.5rem 2rem', overflowY: 'auto' }}>
        <article style={{ maxWidth: '820px', margin: '0 auto', color: 'var(--text-primary)', lineHeight: 1.8, fontSize: '1.02rem' }}>
          <div style={{ whiteSpace: 'pre-wrap', fontFamily: 'var(--font-sans)' }}>
            {result.paper_text}
          </div>
        </article>
      </div>
    </div>
  );
};
