import React from 'react';
import { Spinner, Button } from 'stroom-ds';

export const Default = () => (
  <div className="flex items-center gap-3 text-brand-ink/70">
    <Spinner />
    <span className="font-mono text-[11px] uppercase tracking-[0.18em]">Transcriberen…</span>
  </div>
);

export const Sizes = () => (
  <div className="flex items-center gap-4">
    <Spinner size={14} />
    <Spinner size={20} />
    <Spinner size={28} />
  </div>
);

export const InButton = () => (
  <Button variant="primary" disabled icon={<Spinner size={14} className="text-brand-cream" />}>
    Samenvatten…
  </Button>
);
