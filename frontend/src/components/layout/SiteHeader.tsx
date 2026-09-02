import React from 'react';
import { BookOpen, FileText, Activity, Shield, Layers, Sun, Moon, Mic } from 'lucide-react';

interface SiteHeaderProps {
  activeTab: 'workspace' | 'academic' | 'voices' | 'runs' | 'providers';
  setActiveTab: (tab: 'workspace' | 'academic' | 'voices' | 'runs' | 'providers') => void;
  theme: 'light' | 'dark';
  setTheme: (theme: 'light' | 'dark') => void;
  onOpenDrawer: () => void;
  onOpenStart: () => void;
}

export const SiteHeader: React.FC<SiteHeaderProps> = ({
  activeTab,
  setActiveTab,
  theme,
  setTheme,
  onOpenDrawer,
  onOpenStart,
}) => {
  const toggleTheme = () => {
    const next = theme === 'light' ? 'dark' : 'light';
    setTheme(next);
    document.documentElement.setAttribute('data-theme', next);
  };

  return (
    <header className="site-header">
      <div className="header-top">
        <div className="header-brand">
          <button className="brand-sig" onClick={onOpenStart} style={{ background: 'none', border: 'none', textAlign: 'left', padding: 0 }}>
            HOWL // <span>WRITER</span>
          </button>
          <span className="subsystem-tag">[CONTROL PLANE]</span>
        </div>
        <div className="header-actions">
          <button
            type="button"
            className="btn-theme-toggle"
            onClick={toggleTheme}
            aria-label="Toggle light/dark theme"
          >
            {theme === 'light' ? <Moon size={14} /> : <Sun size={14} />}
            <span>[{theme === 'light' ? 'DARK' : 'LIGHT'}]</span>
          </button>
          <button
            type="button"
            className="btn-eco-toggle"
            onClick={onOpenDrawer}
            aria-label="Open Howl ecosystem directory"
          >
            <Layers size={14} />
            <span>[ECOSYSTEM ▾]</span>
          </button>
        </div>
      </div>

      <nav className="section-nav" aria-label="Main Navigation">
        <span className="section-nav-label">SURFACES:</span>
        <button
          type="button"
          className={`nav-tab ${activeTab === 'workspace' ? 'active' : ''}`}
          onClick={() => setActiveTab('workspace')}
        >
          <FileText size={14} />
          <span>WORKSPACE</span>
        </button>
        <button
          type="button"
          className={`nav-tab ${activeTab === 'academic' ? 'active' : ''}`}
          onClick={() => setActiveTab('academic')}
        >
          <BookOpen size={14} />
          <span>ACADEMIC PAPER</span>
        </button>
        <button
          type="button"
          className={`nav-tab ${activeTab === 'voices' ? 'active' : ''}`}
          onClick={() => setActiveTab('voices')}
        >
          <Mic size={14} />
          <span>VOICES</span>
        </button>
        <button
          type="button"
          className={`nav-tab ${activeTab === 'runs' ? 'active' : ''}`}
          onClick={() => setActiveTab('runs')}
        >
          <Activity size={14} />
          <span>RECENT RUNS</span>
        </button>
        <button
          type="button"
          className={`nav-tab ${activeTab === 'providers' ? 'active' : ''}`}
          onClick={() => setActiveTab('providers')}
        >
          <Shield size={14} />
          <span>PROVIDERS & ROLES</span>
        </button>
      </nav>
    </header>
  );
};
