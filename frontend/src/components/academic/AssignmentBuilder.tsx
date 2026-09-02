import React from 'react';
import { BookOpen, Plus, Trash2, Code, Play } from 'lucide-react';
import { AssignmentSpec } from '../../types';
import { YamlPreviewModal } from './YamlPreviewModal';
import { api } from '../../api/client';

interface AssignmentBuilderProps {
  spec: AssignmentSpec;
  setSpec: (spec: AssignmentSpec) => void;
  onStartPipeline: (spec: AssignmentSpec) => void;
  isRunning: boolean;
}

const SAMPLE_SPEC: AssignmentSpec = {
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

export const AssignmentBuilder: React.FC<AssignmentBuilderProps> = ({
  spec,
  setSpec,
  onStartPipeline,
  isRunning,
}) => {
  const [yamlPreview, setYamlPreview] = React.useState<string | null>(null);
  const [validationErrors, setValidationErrors] = React.useState<string[]>([]);
  const [newRequirement, setNewRequirement] = React.useState('');
  const [newOutlineItem, setNewOutlineItem] = React.useState('');

  const loadSample = () => {
    setSpec(SAMPLE_SPEC);
    setValidationErrors([]);
  };

  const handleViewYaml = async () => {
    try {
      const res = await api.validateSpec(spec);
      setYamlPreview(res.yaml_preview);
      if (!res.valid) {
        setValidationErrors(res.errors);
      } else {
        setValidationErrors([]);
      }
    } catch (err: any) {
      setValidationErrors([err.message || 'Validation error']);
    }
  };

  const addRequirement = () => {
    if (newRequirement.trim()) {
      setSpec({
        ...spec,
        requirements: [...spec.requirements, newRequirement.trim()],
      });
      setNewRequirement('');
    }
  };

  const removeRequirement = (index: number) => {
    setSpec({
      ...spec,
      requirements: spec.requirements.filter((_, i) => i !== index),
    });
  };

  const addOutlineItem = () => {
    if (newOutlineItem.trim()) {
      setSpec({
        ...spec,
        outline: [...spec.outline, newOutlineItem.trim()],
      });
      setNewOutlineItem('');
    }
  };

  const removeOutlineItem = (index: number) => {
    setSpec({
      ...spec,
      outline: spec.outline.filter((_, i) => i !== index),
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await api.validateSpec(spec);
      if (!res.valid) {
        setValidationErrors(res.errors);
        return;
      }
      setValidationErrors([]);
      onStartPipeline(spec);
    } catch (err: any) {
      setValidationErrors([err.message || 'Validation error']);
    }
  };

  return (
    <div className="tech-panel" style={{ height: '100%' }}>
      <div className="tech-header">
        <h3><BookOpen size={16} /> ACADEMIC ASSIGNMENT SPEC BUILDER</h3>
        <div style={{ display: 'flex', gap: '0.4rem' }}>
          <button type="button" className="btn-tech" onClick={loadSample} disabled={isRunning} style={{ fontSize: '0.75rem' }}>
            [LOAD SAMPLE]
          </button>
          <button type="button" className="btn-tech" onClick={handleViewYaml} style={{ fontSize: '0.75rem' }}>
            <Code size={12} /> [VIEW YAML]
          </button>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="tech-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {validationErrors.length > 0 && (
          <div style={{ background: 'rgba(217, 71, 50, 0.1)', border: '1px solid var(--color-red)', padding: '0.75rem', fontSize: '0.8rem', color: 'var(--color-red)' }}>
            <strong>Validation Errors:</strong>
            <ul style={{ margin: '0.25rem 0 0 1.25rem' }}>
              {validationErrors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="form-group">
          <label className="form-label">PAPER TITLE</label>
          <input
            type="text"
            className="form-input"
            value={spec.title}
            onChange={(e) => setSpec({ ...spec, title: e.target.value })}
            placeholder="e.g. Surface Code Quantum Error Correction"
            required
            disabled={isRunning}
          />
        </div>

        <div className="form-group">
          <label className="form-label">RESEARCH TOPIC & SCOPE</label>
          <textarea
            className="form-textarea"
            rows={2}
            value={spec.topic}
            onChange={(e) => setSpec({ ...spec, topic: e.target.value })}
            placeholder="Detailed description of what the paper will analyze and synthesize..."
            required
            disabled={isRunning}
          />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem' }}>
          <div className="form-group">
            <label className="form-label">TARGET WORDS</label>
            <input
              type="number"
              className="form-input"
              value={spec.target_words}
              onChange={(e) => setSpec({ ...spec, target_words: parseInt(e.target.value, 10) || 500 })}
              min={200}
              max={20000}
              disabled={isRunning}
            />
          </div>

          <div className="form-group">
            <label className="form-label">WORD TOLERANCE (±%)</label>
            <input
              type="number"
              className="form-input"
              value={spec.word_tolerance_percent}
              onChange={(e) => setSpec({ ...spec, word_tolerance_percent: parseFloat(e.target.value) || 10.0 })}
              min={1}
              max={30}
              disabled={isRunning}
            />
          </div>

          <div className="form-group">
            <label className="form-label">MINIMUM SOURCES</label>
            <input
              type="number"
              className="form-input"
              value={spec.source_requirements.minimum_sources}
              onChange={(e) =>
                setSpec({
                  ...spec,
                  source_requirements: {
                    ...spec.source_requirements,
                    minimum_sources: parseInt(e.target.value, 10) || 1,
                  },
                })
              }
              min={1}
              max={20}
              disabled={isRunning}
            />
          </div>

          <div className="form-group">
            <label className="form-label">CITATION STYLE</label>
            <select
              className="form-select"
              value={spec.citation_style}
              onChange={(e) => setSpec({ ...spec, citation_style: e.target.value })}
              disabled={isRunning}
            >
              <option value="apa7">APA 7 (American Psychological Association)</option>
            </select>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '1.5rem', background: 'var(--bg-surface)', padding: '0.65rem 0.85rem', border: '1px solid var(--border-subtle)', flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', fontSize: '0.8rem', fontFamily: 'var(--font-mono)', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={spec.source_requirements.prefer_primary_sources}
              onChange={(e) =>
                setSpec({
                  ...spec,
                  source_requirements: { ...spec.source_requirements, prefer_primary_sources: e.target.checked },
                })
              }
              disabled={isRunning}
            />
            PREFER PRIMARY SOURCES
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', fontSize: '0.8rem', fontFamily: 'var(--font-mono)', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={spec.source_requirements.scholarly_or_authoritative}
              onChange={(e) =>
                setSpec({
                  ...spec,
                  source_requirements: { ...spec.source_requirements, scholarly_or_authoritative: e.target.checked },
                })
              }
              disabled={isRunning}
            />
            SCHOLARLY / AUTHORITATIVE ONLY
          </label>
        </div>

        {/* Outline Section Builder */}
        <div className="form-group">
          <label className="form-label">
            <span>REQUIRED OUTLINE SECTIONS ({spec.outline.length})</span>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Every section strictly enforced</span>
          </label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
            {spec.outline.map((sec, idx) => (
              <div key={idx} style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                <span className="chip chip-neutral" style={{ width: '28px', textAlign: 'center' }}>{idx + 1}</span>
                <input
                  type="text"
                  className="form-input"
                  style={{ flex: 1, padding: '0.35rem 0.6rem', fontSize: '0.82rem' }}
                  value={sec}
                  onChange={(e) => {
                    const newArr = [...spec.outline];
                    newArr[idx] = e.target.value;
                    setSpec({ ...spec, outline: newArr });
                  }}
                  disabled={isRunning}
                />
                <button
                  type="button"
                  className="btn-tech btn-tech-danger"
                  onClick={() => removeOutlineItem(idx)}
                  disabled={isRunning || spec.outline.length <= 1}
                  style={{ padding: '0.35rem 0.5rem' }}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
            <div style={{ display: 'flex', gap: '0.4rem', marginTop: '0.25rem' }}>
              <input
                type="text"
                className="form-input"
                style={{ flex: 1, padding: '0.35rem 0.6rem', fontSize: '0.82rem' }}
                value={newOutlineItem}
                onChange={(e) => setNewOutlineItem(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addOutlineItem(); } }}
                placeholder="Add next section heading..."
                disabled={isRunning}
              />
              <button
                type="button"
                className="btn-tech"
                onClick={addOutlineItem}
                disabled={isRunning || !newOutlineItem.trim()}
                style={{ padding: '0.35rem 0.65rem' }}
              >
                <Plus size={13} /> [ADD]
              </button>
            </div>
          </div>
        </div>

        {/* Requirements List Builder */}
        <div className="form-group">
          <label className="form-label">
            <span>KEY REQUIREMENTS & CONSTRAINTS ({spec.requirements.length})</span>
          </label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
            {spec.requirements.map((req, idx) => (
              <div key={idx} style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                <span className="chip chip-blue" style={{ width: '28px', textAlign: 'center' }}>R{idx + 1}</span>
                <input
                  type="text"
                  className="form-input"
                  style={{ flex: 1, padding: '0.35rem 0.6rem', fontSize: '0.82rem' }}
                  value={req}
                  onChange={(e) => {
                    const newArr = [...spec.requirements];
                    newArr[idx] = e.target.value;
                    setSpec({ ...spec, requirements: newArr });
                  }}
                  disabled={isRunning}
                />
                <button
                  type="button"
                  className="btn-tech btn-tech-danger"
                  onClick={() => removeRequirement(idx)}
                  disabled={isRunning}
                  style={{ padding: '0.35rem 0.5rem' }}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
            <div style={{ display: 'flex', gap: '0.4rem', marginTop: '0.25rem' }}>
              <input
                type="text"
                className="form-input"
                style={{ flex: 1, padding: '0.35rem 0.6rem', fontSize: '0.82rem' }}
                value={newRequirement}
                onChange={(e) => setNewRequirement(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addRequirement(); } }}
                placeholder="Add requirement (e.g. Cite specific dataset, evaluate error thresholds)..."
                disabled={isRunning}
              />
              <button
                type="button"
                className="btn-tech"
                onClick={addRequirement}
                disabled={isRunning || !newRequirement.trim()}
                style={{ padding: '0.35rem 0.65rem' }}
              >
                <Plus size={13} /> [ADD]
              </button>
            </div>
          </div>
        </div>

        <div style={{ marginTop: 'auto', paddingTop: '1rem', borderTop: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
          <button
            type="submit"
            className="btn-tech btn-tech-primary"
            disabled={isRunning}
            style={{ padding: '0.6rem 1.25rem', fontSize: '0.9rem' }}
          >
            <Play size={15} />
            <span>[START ACADEMIC PAPER PIPELINE]</span>
          </button>
        </div>
      </form>

      <YamlPreviewModal
        isOpen={yamlPreview !== null}
        onClose={() => setYamlPreview(null)}
        yamlContent={yamlPreview || ''}
      />
    </div>
  );
};
