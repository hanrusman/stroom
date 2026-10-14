import React from 'react';
import { Textarea } from 'stroom-ds';

export const Default = () => (
  <div className="w-96">
    <Textarea
      rows={4}
      defaultValue="Vat dit artikel samen in drie kernpunten, gericht op de gevolgen voor het klimaatbeleid."
    />
  </div>
);

export const Placeholder = () => (
  <div className="w-96">
    <Textarea rows={4} placeholder="Schrijf een prompt voor de samenvat-agent…" />
  </div>
);

export const Disabled = () => (
  <div className="w-96">
    <Textarea rows={3} disabled defaultValue="Wachten op transcriptie…" />
  </div>
);
