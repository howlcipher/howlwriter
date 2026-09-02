import React from 'react';
import { Loader2, AlertCircle, Clock, CheckCircle2 } from 'lucide-react';
import { Stage } from '../../types';

interface PipelineProgressRailProps {
  stages: Stage[];
  elapsedSeconds: number;
  status: string;
  runId?: string;
  errorMessage?: string | null;
}

export const PipelineProgressRail: React.FC<PipelineProgressRailProps> = ({
  stages,
  elapsedSeconds,
  runId,
  errorMessage,
}) => {
  return (
    <div className="tech-panel" style={{ height: '100%' }}>
      <div className="tech-header">
        <h3>
          <Clock size={15} />
          PIPELINE PROGRESS RAIL ({elapsedSeconds.toFixed(1)}s)
        </h3>
        {runId && (
          <span className="sec-id" style={{ fontSize: '0.7rem' }}>
            RUN: {runId}
          </span>
        )}
      </div>

      <div className="tech-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
        {errorMessage && (
          <div style={{ background: 'rgba(217, 71, 50, 0.15)', border: '1px solid var(--color-red)', padding: '0.65rem 0.85rem', fontSize: '0.8rem', color: 'var(--color-red)', marginBottom: '0.5rem' }}>
            <div style={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <AlertCircle size={14} /> PIPELINE HALTED / ERROR:
            </div>
            <div style={{ marginTop: '0.25rem' }}>{errorMessage}</div>
          </div>
        )}

        <div className="pipeline-rail">
          {stages.map((stage, idx) => {
            const isDone = stage.status === 'DONE';
            const isRunning = stage.status === 'RUNNING';
            const isFailed = stage.status === 'FAILED';

            return (
              <div
                key={stage.id}
                className={`rail-stage ${isRunning ? 'stage-running' : isDone ? 'stage-done' : isFailed ? 'stage-failed' : ''}`}
              >
                <div className="rail-stage-info">
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-dim)', width: '20px' }}>
                    0{idx + 1}
                  </span>

                  <span className="stage-icon">
                    {isDone ? (
                      <CheckCircle2 size={15} color="var(--color-cyan)" />
                    ) : isRunning ? (
                      <Loader2 size={15} color="var(--color-cyan)" style={{ animation: 'spin 1s linear infinite' }} />
                    ) : isFailed ? (
                      <AlertCircle size={15} color="var(--color-red)" />
                    ) : (
                      <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: 'var(--border-medium)', margin: '0 3.5px' }} />
                    )}
                  </span>

                  <span style={{ fontWeight: isRunning || isDone ? 700 : 400, color: isRunning ? 'var(--color-cyan)' : isDone ? 'var(--text-primary)' : 'var(--text-dim)' }}>
                    {stage.label}
                  </span>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  {stage.data && Object.keys(stage.data).length > 0 && (
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-secondary)', background: 'var(--bg-sunken)', padding: '0.1rem 0.35rem' }}>
                      {stage.data.sources_found !== undefined && `${stage.data.sources_found} sources`}
                      {stage.data.actual_words !== undefined && `${stage.data.actual_words}w`}
                      {stage.data.verified_claims !== undefined && `${stage.data.verified_claims} claims`}
                      {stage.data.banned_words !== undefined && `lint: ${stage.data.banned_words}b`}
                      {stage.data.meaning_preservation !== undefined && `meaning: ${stage.data.meaning_preservation}`}
                    </span>
                  )}

                  <span className={`chip ${isDone ? 'chip-pass' : isRunning ? 'chip-cyan' : isFailed ? 'chip-fail' : 'chip-neutral'}`} style={{ fontSize: '0.65rem' }}>
                    {stage.status}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
