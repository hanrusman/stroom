import React from 'react';
import { Button } from 'stroom-ds';
import { Sparkles, Mic, ArrowRight } from 'lucide-react';

export const Variants = () => (
  <div className="flex flex-wrap items-center gap-3">
    <Button variant="primary">Samenvatten</Button>
    <Button variant="secondary">Archiveren</Button>
    <Button variant="ghost">Later lezen</Button>
  </div>
);

export const Sizes = () => (
  <div className="flex flex-wrap items-center gap-3">
    <Button size="md">Podcast maken</Button>
    <Button size="sm">Transcriberen</Button>
  </div>
);

export const WithIcon = () => (
  <div className="flex flex-wrap items-center gap-3">
    <Button variant="primary" icon={<Sparkles size={14} />}>AI-samenvatting</Button>
    <Button variant="secondary" icon={<Mic size={14} />}>Beluister</Button>
    <Button variant="ghost" icon={<ArrowRight size={14} />}>Naar bron</Button>
  </div>
);

export const Disabled = () => (
  <Button variant="primary" disabled>Bezig…</Button>
);
