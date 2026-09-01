import React from 'react';
import { X } from 'lucide-react';

interface EcosystemDrawerProps {
  isOpen: boolean;
  onClose: () => void;
}

const NODES = [
  { name: 'HOWL // HUB', role: '[PORTAL]', roleColor: 'var(--color-blue)', desc: 'Central ecosystem portal, architectural blueprint, and cross-project governance map.', url: 'https://howlcipher.github.io/howl/' },
  { name: 'HOWLFRAME', role: '[VM & COMPILER]', roleColor: 'var(--color-magenta)', desc: 'AI-native reasoning language, typed intermediate representation, and sandboxed bytecode VM.', url: 'https://howlcipher.github.io/howlframe/' },
  { name: 'HOWLPLANE', role: '[CONTROL PLANE]', roleColor: 'var(--color-blue)', desc: 'Engineering control plane with deterministic routing, adversarial falsification, and human gates.', url: 'https://howlcipher.github.io/howlplane/' },
  { name: 'HOWLNOTES', role: '[KNOWLEDGE NOTEBOOK]', roleColor: 'var(--color-cyan)', desc: 'Engineering knowledge notebook & full-stack dogfood consumer proving native persistent storage.', url: 'https://howlcipher.github.io/howlnotes/' },
  { name: 'HOWLCHANGEOPS', role: '[AUTHORITY GATE]', roleColor: 'var(--color-red)', desc: 'Governed release controller enforcing cryptographic human approvals and bounded Git mutations.', url: 'https://howlcipher.github.io/howlchangeops/' },
  { name: 'HOWLBOARD', role: '[EVALUATION SURFACE]', roleColor: 'var(--color-amber)', desc: 'Observation console and full-stack deterministic task state machine application.', url: 'https://howlcipher.github.io/howlboard/' },
  { name: 'HOWLWRITER', role: '[WRITING CONTROL]', roleColor: 'var(--color-magenta)', desc: 'Writing control system for voice preservation, deterministic style linting, humanization, and review.', url: 'https://howlcipher.github.io/howlwriter/', active: true },
];

export const EcosystemDrawer: React.FC<EcosystemDrawerProps> = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  return (
    <>
      <div className="eco-drawer-overlay" onClick={onClose} aria-hidden="true" />
      <aside className="eco-drawer" aria-label="Howl Ecosystem Directory">
        <div className="drawer-header">
          <div className="drawer-title">HOWL // ECOSYSTEM DIRECTORY</div>
          <button className="btn-drawer-close" type="button" onClick={onClose}>
            <X size={14} /> [CLOSE]
          </button>
        </div>
        <div className="drawer-body">
          {NODES.map((node) => (
            <a
              key={node.name}
              href={node.url}
              target="_blank"
              rel="noopener noreferrer"
              className={`drawer-node-card ${node.active ? 'active-hub' : ''}`}
            >
              <div className="node-card-top">
                <span className="node-card-name">{node.name}</span>
                <span className="node-card-role" style={{ color: node.roleColor }}>
                  {node.role}
                </span>
              </div>
              <div className="node-card-desc">{node.desc}</div>
            </a>
          ))}
        </div>
      </aside>
    </>
  );
};
