import React from 'react';
import { ModelInfo } from './api';
import { DigestModel, modelLabel } from './admin_model_constants';

interface Props {
  value: DigestModel;
  onChange: (v: DigestModel) => void;
  models: ModelInfo[];
  disabled?: boolean;
  className?: string;
}

/** Modelkeuze gevoed door de live LiteLLM-lijst (permanent-dode modellen worden
 *  server-side al weggefilterd). De huidige waarde blijft altijd selecteerbaar,
 *  ook als die niet meer geserveerd wordt. */
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
        <option value={value}>{modelLabel(value)}</option>
      )}
      {models.map(m => (
        <option key={m.name} value={m.name}>{m.label || modelLabel(m.name)}</option>
      ))}
    </select>
  );
}
