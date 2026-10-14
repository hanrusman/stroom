import React from 'react';
import { Select } from 'stroom-ds';

export const WithOptions = () => (
  <div className="w-72">
    <Select
      defaultValue="stroom-deep"
      options={[
        { value: 'stroom-bulk', label: 'Stroom Bulk' },
        { value: 'stroom-deep', label: 'Stroom Deep' },
        { value: 'stroom-sonnet', label: 'Stroom Sonnet' },
        { value: 'cloud-kimi', label: 'Cloud Kimi' },
      ]}
    />
  </div>
);

export const WithChildren = () => (
  <div className="w-72">
    <Select defaultValue="week">
      <option value="dag">Vandaag</option>
      <option value="week">Deze week</option>
      <option value="maand">Deze maand</option>
    </Select>
  </div>
);

export const Disabled = () => (
  <div className="w-72">
    <Select disabled options={[{ value: 'x', label: 'Geen modellen beschikbaar' }]} />
  </div>
);
