import React from 'react';
import { ModelInfo } from './api';
import { DigestModel } from './admin_model_constants';

interface Props {
  value: DigestModel;
  onChange: (v: DigestModel) => void;
  models: ModelInfo[];
  disabled?: boolean;
  className?: string;
}

/** Modelkeuze gevoed door de live LiteLLM-lijst. Verborgen modellen zijn niet
 *  kiesbaar, maar de huidige waarde blijft altijd selecteerbaar — ook als die
 *  verborgen is of niet meer geserveerd wordt. */
export function ModelSelect({ value, onChange, models, disabled, className }: Props) {
  const visible = models.filter(m => !m.hidden);
  const present = visible.some(m => m.name === value);
  const currentLabel = models.find(m => m.name === value)?.label || value;

  return (
    <select
      value={value}
      disabled={disabled}
      onChange={e => onChange(e.target.value as DigestModel)}
      className={className}
    >
      {!present && value && (
        <option value={value}>{currentLabel}</option>
      )}
      {visible.map(m => (
        <option key={m.name} value={m.name}>{m.label || m.name}</option>
      ))}
    </select>
  );
}
