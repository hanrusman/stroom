import React from 'react';
import { ModelInfo } from './api';
import { DigestModel, modelLabel } from './admin_model_constants';

// Markeer krediet-/quota-gevoelige modellen in de optietekst, zonder ze te
// blokkeren (keuze "tonen maar markeren"). 'degraded' = nu niet beschikbaar;
// 'unknown' = status onbekend (health-probe gaf geen uitsluitsel).
function optionLabel(m: ModelInfo): string {
  const base = m.label || modelLabel(m.name);
  if (m.status === 'degraded') return `${base} — ⚠ nu niet beschikbaar`;
  if (m.status === 'unknown') return `${base} — ⚠ status onbekend`;
  return base;
}

interface Props {
  value: DigestModel;
  onChange: (v: DigestModel) => void;
  models: ModelInfo[];
  disabled?: boolean;
  className?: string;
}

/** Modelkeuze gevoed door de live LiteLLM-lijst. De huidige waarde blijft altijd
 *  selecteerbaar, ook als die niet meer geserveerd wordt. */
export function ModelSelect({ value, onChange, models, disabled, className }: Props) {
  const present = models.some(m => m.name === value);

  return (
    <select
      value={value}
      disabled={disabled}
      onChange={e => onChange(e.target.value as DigestModel)}
      className={className}
    >
      {!present && value && (
        <option value={value}>{modelLabel(value)} — niet meer beschikbaar</option>
      )}
      {models.length === 0 && present === false && !value && (
        <option value="" disabled>Laden…</option>
      )}
      {models.map(m => (
        <option key={m.name} value={m.name}>{optionLabel(m)}</option>
      ))}
    </select>
  );
}
