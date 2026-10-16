import React from 'react';
import { X, Cpu, AlertCircle } from 'lucide-react';
import {
  fetchModelChoices,
  ModelChoiceRequest,
  ModelOption,
  onModelChoiceRequest,
} from '../../api/modelChoice';

/** Asks which model runs a step, each time one is needed. Nothing is sent until RUN. */
export const ModelPickerModal: React.FC = () => {
  const [request, setRequest] = React.useState<ModelChoiceRequest | null>(null);
  const [options, setOptions] = React.useState<ModelOption[]>([]);
  const [selected, setSelected] = React.useState<string>('');
  const [agreed, setAgreed] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    onModelChoiceRequest((next) => {
      setRequest(next);
      setSelected('');
      setAgreed(false);
      setError(null);
      fetchModelChoices()
        .then(setOptions)
        .catch((err: Error) => setError(err.message));
    });
    return () => onModelChoiceRequest(null);
  }, []);

  if (!request) return null;

  const chosen = options.find((o) => o.provider === selected);
  const canRun = !!chosen && chosen.available && (chosen.local || agreed);
  const step = request.role.replace(/_/g, ' ');

  const finish = (provider: string | null, confirmed = false) => {
    request.resolve(provider ? { provider, confirmed } : null);
    setRequest(null);
  };

  return (
    <div className="modal-overlay">
      <div className="modal-card" style={{ width: 'min(600px, calc(100vw - 32px))' }}>
        <div className="modal-header">
          <div className="modal-title">CHOOSE A MODEL FOR THE {step.toUpperCase()} STEP</div>
          <button type="button" className="btn-drawer-close" onClick={() => finish(null)}>
            <X size={14} /> [CANCEL]
          </button>
        </div>

        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>
            Nothing has been sent yet. Pick the model for this run; you will be asked again next time.
          </div>
          {error && (
            <div style={{ border: '1px solid var(--color-red)', padding: '0.65rem 0.85rem', fontSize: '0.8rem', color: 'var(--color-red)' }}>
              <AlertCircle size={14} style={{ display: 'inline', marginRight: '0.35rem' }} />
              {error}
            </div>
          )}
          {options.map((option) => (
            <label
              key={option.provider}
              style={{
                display: 'flex',
                gap: '0.6rem',
                alignItems: 'flex-start',
                opacity: option.available ? 1 : 0.5,
                cursor: option.available ? 'pointer' : 'not-allowed',
              }}
            >
              <input
                type="radio"
                name="model-choice"
                value={option.provider}
                disabled={!option.available}
                checked={selected === option.provider}
                onChange={() => {
                  setSelected(option.provider);
                  setAgreed(false);
                }}
              />
              <span style={{ fontSize: '0.85rem' }}>
                <strong>{option.label}</strong>{' '}
                <span style={{ color: 'var(--text-dim)' }}>
                  {option.local ? '(private, on this machine)' : '(sends text to its provider)'}
                </span>
                {!option.available && (
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Unavailable: {option.detail}</div>
                )}
              </span>
            </label>
          ))}
          {chosen && !chosen.local && (
            <label style={{ display: 'flex', gap: '0.6rem', alignItems: 'flex-start', fontSize: '0.8rem' }}>
              <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
              <span>{chosen.disclosure} I agree to send it for this run.</span>
            </label>
          )}
        </div>

        <div className="modal-footer" style={{ flexWrap: 'wrap', gap: '0.5rem' }}>
          <button type="button" className="btn-tech" onClick={() => finish('none')}>
            [CONTINUE WITHOUT A MODEL]
          </button>
          <button
            type="button"
            className="btn-tech btn-tech-primary"
            disabled={!canRun}
            onClick={() => chosen && finish(chosen.provider, !chosen.local)}
          >
            <Cpu size={13} />
            <span>[RUN WITH {chosen ? chosen.label.toUpperCase() : 'MODEL'}]</span>
          </button>
        </div>
      </div>
    </div>
  );
};
