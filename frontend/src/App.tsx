import React from 'react';
import { SiteHeader } from './components/layout/SiteHeader';
import { SiteFooter } from './components/layout/SiteFooter';
import { EcosystemDrawer } from './components/layout/EcosystemDrawer';
import { DocumentEditor } from './components/workspace/DocumentEditor';
import { WorkspaceActions } from './components/workspace/WorkspaceActions';
import { LintPanel } from './components/workspace/LintPanel';
import { RedPenPanel } from './components/workspace/RedPenPanel';
import { DiffModal } from './components/workspace/DiffModal';
import { ReadinessExplanation } from './components/workspace/ReadinessExplanation';
import { AssignmentBuilder } from './components/academic/AssignmentBuilder';
import { PipelineProgressRail } from './components/academic/PipelineProgressRail';
import { AcademicPaperViewer } from './components/academic/AcademicPaperViewer';
import { AcademicStatsBar } from './components/academic/AcademicStatsBar';
import { ClaimEvidenceInspector } from './components/academic/ClaimEvidenceInspector';
import { SourceListPanel } from './components/academic/SourceListPanel';
import { SourceDetailModal } from './components/academic/SourceDetailModal';
import { ApaReferencesPanel } from './components/academic/ApaReferencesPanel';
import { RunsLedger } from './components/runs/RunsLedger';
import { ProviderMatrix } from './components/providers/ProviderMatrix';
import { StartScreen } from './components/dialogs/StartScreen';
import { OpenFileModal } from './components/dialogs/OpenFileModal';
import { api } from './api/client';
import {
  AcademicResult,
  AssignmentSpec,
  DocumentData,
  HumanizeResponse,
  JobResponse,
  LintResponse,
  RedPenResponse,
  Source,
  WritingMode,
} from './types';
import { FileText, ShieldCheck, BookOpen, Quote } from 'lucide-react';

const INITIAL_TEXT = `# Surface Code Topologies and Quantum Error Correction

In conclusion, it is important to delve into the intricate tapestry of quantum error correction. Definitively speaking, modern topological stabilizer codes provide robust fault tolerance against decoherence and environmental noise.

We must delve into how syndrome measurement cycles preserve logical qubits without measuring the underlying superposition state.`;

const DEFAULT_SPEC: AssignmentSpec = {
  title: 'Quantum Error Correction in Surface Codes: Syndromes and Fault Tolerance',
  topic: 'Analysis of surface codes, stabilizer measurements, and fault-tolerant quantum error correction protocols.',
  type: 'research_paper',
  target_words: 1500,
  word_tolerance_percent: 10.0,
  citation_style: 'apa7',
  source_requirements: {
    minimum_sources: 3,
    prefer_primary_sources: true,
    scholarly_or_authoritative: true,
    allowed_types: ['peer_reviewed', 'preprint', 'scholarly'],
  },
  requirements: [
    'Explain syndrome extraction cycles and stabilizer measurements',
    'Compare physical qubit error rates with logical qubit error thresholds',
    'Cite foundational papers by Fowler, Bravyi, or Kitaev using APA 7 format',
  ],
  outline: [
    'Introduction to Fault-Tolerant Quantum Computing',
    'Surface Code Topology and Stabilizer Operations',
    'Syndrome Measurement and Minimum-Weight Perfect Matching',
    'Physical-to-Logical Scaling and Current Experimental State',
    'Conclusion and Future Outlook',
  ],
  metadata: {},
};

export const App: React.FC = () => {
  // Theme & Navigation
  const [theme, setTheme] = React.useState<'light' | 'dark'>('light');
  const [activeTab, setActiveTab] = React.useState<'workspace' | 'academic' | 'runs' | 'providers'>('workspace');
  const [isEcoDrawerOpen, setIsEcoDrawerOpen] = React.useState(false);
  const [isStartOpen, setIsStartOpen] = React.useState(false);
  const [isOpenFileOpen, setIsOpenFileOpen] = React.useState(false);
  const [isDiffOpen, setIsDiffOpen] = React.useState(false);
  const [selectedSource, setSelectedSource] = React.useState<Source | null>(null);

  // Active Run ID across surfaces
  const [currentRunId, setCurrentRunId] = React.useState<string | null>(null);

  // Document Workspace State
  const [title, setTitle] = React.useState('sample-quantum-draft.md');
  const [content, setContent] = React.useState(INITIAL_TEXT);
  const [mode, setMode] = React.useState<WritingMode>('article');
  const [activeFilePath, setActiveFilePath] = React.useState<string | null>(null);
  const [isDirty, setIsDirty] = React.useState(false);
  const [isActionLoading, setIsActionLoading] = React.useState(false);
  const [loadingActionName, setLoadingActionName] = React.useState('');

  const [lintResult, setLintResult] = React.useState<LintResponse | null>(null);
  const [redPenResult, setRedPenResult] = React.useState<RedPenResponse | null>(null);
  const [humanizeResult, setHumanizeResult] = React.useState<HumanizeResponse | null>(null);
  const [workspaceRightTab, setWorkspaceRightTab] = React.useState<'lint' | 'redpen'>('lint');

  // Academic Surface State
  const [assignmentSpec, setAssignmentSpec] = React.useState<AssignmentSpec>(DEFAULT_SPEC);
  const [isPipelineRunning, setIsPipelineRunning] = React.useState(false);
  const [academicJob, setAcademicJob] = React.useState<JobResponse | null>(null);
  const [academicResult, setAcademicResult] = React.useState<AcademicResult | null>(null);
  const [academicViewTab, setAcademicViewTab] = React.useState<'paper' | 'claims' | 'sources' | 'references'>('paper');

  // Track edits
  React.useEffect(() => {
    setIsDirty(true);
  }, [content, title, mode]);

  // Word count helper
  const wordCount = React.useMemo(() => {
    const trimmed = content.trim();
    return trimmed ? trimmed.split(/\s+/).length : 0;
  }, [content]);

  // Document Operations
  const handleLint = async () => {
    setIsActionLoading(true);
    setLoadingActionName('Linting');
    try {
      const res = await api.runLint(content, title);
      setLintResult(res);
      setWorkspaceRightTab('lint');
    } catch (err: any) {
      alert(`Lint Error: ${err.message}`);
    } finally {
      setIsActionLoading(false);
    }
  };

  const handleRedPen = async () => {
    setIsActionLoading(true);
    setLoadingActionName('Red Pen Critique');
    try {
      const res = await api.runRedPen(content, title);
      setRedPenResult(res);
      setWorkspaceRightTab('redpen');
    } catch (err: any) {
      alert(`Red Pen Error: ${err.message}`);
    } finally {
      setIsActionLoading(false);
    }
  };

  const handleHumanize = async () => {
    setIsActionLoading(true);
    setLoadingActionName('Humanizing');
    try {
      const res = await api.runHumanize({
        text: content,
        title,
        mode,
        deterministic_only: false,
        apply_safe_rewrites: true,
      });
      setHumanizeResult(res);
      setCurrentRunId(res.run_id);
      setIsDiffOpen(true);
    } catch (err: any) {
      alert(`Humanize Error: ${err.message}`);
    } finally {
      setIsActionLoading(false);
    }
  };

  const handleHowl = async () => {
    setIsActionLoading(true);
    setLoadingActionName('Full Howl Pipeline');
    try {
      const res = await api.runHowl({
        text: content,
        title,
        deterministic_only: false,
      });
      setContent(res.final_text);
      setCurrentRunId(res.run_id);
      setLintResult({
        matches: res.lint_matches,
        banned_words_count: res.lint_matches.filter((m) => m.rule_code.includes('BANNED')).length,
        ai_style_warnings_count: res.lint_matches.filter((m) => !m.rule_code.includes('BANNED')).length,
        total_count: res.lint_matches.length,
      });
      setRedPenResult({
        findings: res.red_pen_findings,
        total_count: res.red_pen_findings.length,
      });
      alert(`Pipeline complete! Run ID: ${res.run_id} (Status: ${res.status})`);
    } catch (err: any) {
      alert(`Howl Pipeline Error: ${err.message}`);
    } finally {
      setIsActionLoading(false);
    }
  };

  const handleSave = async () => {
    if (!activeFilePath) {
      const target = prompt('Enter path to save file:', title || 'document.md');
      if (!target) return;
      setActiveFilePath(target);
      try {
        await api.saveDocument(target, content);
        setIsDirty(false);
        alert(`Saved successfully to ${target}`);
      } catch (err: any) {
        alert(`Save failed: ${err.message}`);
      }
    } else {
      try {
        await api.saveDocument(activeFilePath, content);
        setIsDirty(false);
        alert(`Saved successfully to ${activeFilePath}`);
      } catch (err: any) {
        alert(`Save failed: ${err.message}`);
      }
    }
  };

  const handleDocumentLoaded = (doc: DocumentData) => {
    setTitle(doc.title);
    setContent(doc.content);
    setMode(doc.mode);
    setActiveFilePath(doc.path || null);
    setIsDirty(false);
    setLintResult(null);
    setRedPenResult(null);
  };

  const handleNewDoc = () => {
    if (isDirty && !confirm('Discard unsaved document changes?')) return;
    setTitle('untitled.md');
    setContent('');
    setActiveFilePath(null);
    setIsDirty(false);
    setLintResult(null);
    setRedPenResult(null);
  };

  // Academic Pipeline Operations
  const handleStartAcademicPipeline = async (specToRun: AssignmentSpec) => {
    setIsPipelineRunning(true);
    setAcademicResult(null);
    try {
      const initialJob = await api.generatePaper(specToRun, false);
      setAcademicJob(initialJob);
      setCurrentRunId(initialJob.run_id);

      // Subscribe to SSE stream for live stage events
      const unsubscribe = api.subscribeToJobEvents(
        initialJob.job_id,
        (event) => {
          if (event.event === 'stage_update' && event.stage) {
            setAcademicJob((prev) => {
              if (!prev) return prev;
              const updatedStages = prev.stages.map((s) =>
                s.id === event.stage.id ? { ...s, ...event.stage } : s
              );
              return { ...prev, stages: updatedStages, current_stage_id: event.stage.id };
            });
          } else if (event.event === 'completed' && event.result) {
            setAcademicResult(event.result);
            setIsPipelineRunning(false);
            setAcademicViewTab('paper');
          } else if (event.event === 'failed') {
            setIsPipelineRunning(false);
            setAcademicJob((prev) => (prev ? { ...prev, status: 'FAILED', error_message: event.error_message } : null));
          }
        },
        (err) => {
          console.warn('SSE stream error, polling fallback:', err);
        }
      );

      // Polling fallback to guarantee state synchronization
      const pollInterval = setInterval(async () => {
        try {
          const pollStatus = await api.getJobStatus(initialJob.job_id);
          setAcademicJob(pollStatus);
          if (pollStatus.status === 'COMPLETED' && pollStatus.result) {
            setAcademicResult(pollStatus.result);
            setIsPipelineRunning(false);
            clearInterval(pollInterval);
            unsubscribe();
          } else if (pollStatus.status === 'FAILED') {
            setIsPipelineRunning(false);
            clearInterval(pollInterval);
            unsubscribe();
          }
        } catch {}
      }, 1000);
    } catch (err: any) {
      alert(`Academic Job Error: ${err.message}`);
      setIsPipelineRunning(false);
    }
  };

  return (
    <div className="app-viewport">
      <SiteHeader
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        theme={theme}
        setTheme={setTheme}
        onOpenDrawer={() => setIsEcoDrawerOpen(true)}
        onOpenStart={() => setIsStartOpen(true)}
      />

      <main className="app-main">
        {/* WORKSPACE TAB */}
        {activeTab === 'workspace' && (
          <div className="workspace-layout">
            <div className="workspace-main">
              <WorkspaceActions
                onLint={handleLint}
                onRedPen={handleRedPen}
                onHumanize={handleHumanize}
                onHowl={handleHowl}
                onSave={handleSave}
                onOpen={() => setIsOpenFileOpen(true)}
                onNew={handleNewDoc}
                isLoading={isActionLoading}
                loadingAction={loadingActionName}
              />
              <DocumentEditor
                title={title}
                setTitle={setTitle}
                content={content}
                setContent={setContent}
                mode={mode}
                setMode={setMode}
                isDirty={isDirty}
                activeFilePath={activeFilePath}
              />
            </div>

            <div className="workspace-sidebar">
              {/* Readiness Explanation if linted */}
              {lintResult && (
                <ReadinessExplanation
                  status={lintResult.total_count === 0 ? 'READY' : 'NEEDS_REVIEW'}
                  meaningPreservation={humanizeResult?.meaning_preservation_status || 'PASS'}
                  bannedWordsCount={lintResult.banned_words_count}
                  aiStyleCount={lintResult.ai_style_warnings_count}
                  redPenFindingsCount={redPenResult?.total_count || 0}
                />
              )}

              {/* Sidebar Tabs */}
              <div style={{ display: 'flex', gap: '0.25rem', marginBottom: '0.25rem' }}>
                <button
                  type="button"
                  className={`nav-tab ${workspaceRightTab === 'lint' ? 'active' : ''}`}
                  onClick={() => setWorkspaceRightTab('lint')}
                  style={{ flex: 1, justifyContent: 'center' }}
                >
                  LINT FINDINGS {lintResult ? `(${lintResult.total_count})` : ''}
                </button>
                <button
                  type="button"
                  className={`nav-tab ${workspaceRightTab === 'redpen' ? 'active' : ''}`}
                  onClick={() => setWorkspaceRightTab('redpen')}
                  style={{ flex: 1, justifyContent: 'center' }}
                >
                  RED PEN {redPenResult ? `(${redPenResult.total_count})` : ''}
                </button>
              </div>

              <div style={{ flex: 1, overflow: 'hidden' }}>
                {workspaceRightTab === 'lint' ? (
                  <LintPanel lintResult={lintResult} onClear={() => setLintResult(null)} />
                ) : (
                  <RedPenPanel redPenResult={redPenResult} onClear={() => setRedPenResult(null)} />
                )}
              </div>
            </div>
          </div>
        )}

        {/* ACADEMIC TAB */}
        {activeTab === 'academic' && (
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', paddingBottom: '0.75rem' }}>
            {!academicResult && !isPipelineRunning ? (
              <AssignmentBuilder
                spec={assignmentSpec}
                setSpec={setAssignmentSpec}
                onStartPipeline={handleStartAcademicPipeline}
                isRunning={isPipelineRunning}
              />
            ) : isPipelineRunning && academicJob ? (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr', height: '100%', overflow: 'hidden' }}>
                <PipelineProgressRail
                  stages={academicJob.stages}
                  elapsedSeconds={academicJob.elapsed_seconds}
                  status={academicJob.status}
                  runId={academicJob.run_id}
                  errorMessage={academicJob.error_message}
                />
              </div>
            ) : academicResult ? (
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
                <AcademicStatsBar
                  result={academicResult}
                  onReset={() => { setAcademicResult(null); setAcademicJob(null); }}
                />

                {/* Sub-nav for Academic Results */}
                <div style={{ display: 'flex', gap: '0.35rem', marginBottom: '0.5rem' }}>
                  <button
                    type="button"
                    className={`nav-tab ${academicViewTab === 'paper' ? 'active' : ''}`}
                    onClick={() => setAcademicViewTab('paper')}
                  >
                    <FileText size={13} /> PAPER DRAFT
                  </button>
                  <button
                    type="button"
                    className={`nav-tab ${academicViewTab === 'claims' ? 'active' : ''}`}
                    onClick={() => setAcademicViewTab('claims')}
                  >
                    <ShieldCheck size={13} /> CLAIM & EVIDENCE INSPECTOR ({academicResult.claims.length})
                  </button>
                  <button
                    type="button"
                    className={`nav-tab ${academicViewTab === 'sources' ? 'active' : ''}`}
                    onClick={() => setAcademicViewTab('sources')}
                  >
                    <BookOpen size={13} /> SOURCES REGISTRY ({academicResult.sources.length})
                  </button>
                  <button
                    type="button"
                    className={`nav-tab ${academicViewTab === 'references' ? 'active' : ''}`}
                    onClick={() => setAcademicViewTab('references')}
                  >
                    <Quote size={13} /> APA 7 REFERENCES
                  </button>
                </div>

                <div style={{ flex: 1, overflow: 'hidden' }}>
                  {academicViewTab === 'paper' && (
                    <AcademicPaperViewer result={academicResult} />
                  )}
                  {academicViewTab === 'claims' && (
                    <ClaimEvidenceInspector
                      claims={academicResult.claims}
                      sources={academicResult.sources}
                      onOpenSourceModal={(s) => setSelectedSource(s)}
                    />
                  )}
                  {academicViewTab === 'sources' && (
                    <SourceListPanel
                      sources={academicResult.sources}
                      onSelectSource={(s) => setSelectedSource(s)}
                    />
                  )}
                  {academicViewTab === 'references' && (
                    <ApaReferencesPanel
                      referencesText={academicResult.references_text}
                      citationWarnings={academicResult.warnings}
                    />
                  )}
                </div>
              </div>
            ) : null}
          </div>
        )}

        {/* RUNS TAB */}
        {activeTab === 'runs' && (
          <div style={{ height: '100%', overflow: 'hidden', paddingBottom: '0.75rem' }}>
            <RunsLedger />
          </div>
        )}

        {/* PROVIDERS TAB */}
        {activeTab === 'providers' && (
          <div style={{ height: '100%', overflow: 'hidden', paddingBottom: '0.75rem' }}>
            <ProviderMatrix />
          </div>
        )}
      </main>

      <SiteFooter
        currentRunId={currentRunId}
        activeFilePath={activeFilePath}
        wordCount={wordCount}
      />

      {/* Modals & Drawers */}
      <EcosystemDrawer
        isOpen={isEcoDrawerOpen}
        onClose={() => setIsEcoDrawerOpen(false)}
      />

      <StartScreen
        isOpen={isStartOpen}
        onClose={() => setIsStartOpen(false)}
        onNewDoc={handleNewDoc}
        onOpenDoc={() => setIsOpenFileOpen(true)}
        onAcademic={() => setActiveTab('academic')}
        onRuns={() => setActiveTab('runs')}
        onProviders={() => setActiveTab('providers')}
      />

      <OpenFileModal
        isOpen={isOpenFileOpen}
        onClose={() => setIsOpenFileOpen(false)}
        onDocumentLoaded={handleDocumentLoaded}
      />

      <DiffModal
        isOpen={isDiffOpen}
        onClose={() => setIsDiffOpen(false)}
        humanizeResult={humanizeResult}
        onAccept={(transformed) => {
          setContent(transformed);
          setIsDirty(true);
        }}
      />

      <SourceDetailModal
        isOpen={selectedSource !== null}
        onClose={() => setSelectedSource(null)}
        source={selectedSource}
      />
    </div>
  );
};

export default App;
