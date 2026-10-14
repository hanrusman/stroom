import React from 'react';
import { Badge } from 'stroom-ds';

export const Tones = () => (
  <div className="flex flex-wrap items-center gap-2">
    <Badge tone="neutral">Tech</Badge>
    <Badge tone="accent">Nieuw</Badge>
    <Badge tone="tint">Wetenschap</Badge>
  </div>
);

export const Topics = () => (
  <div className="flex flex-wrap items-center gap-2">
    <Badge>Klimaat</Badge>
    <Badge>AI &amp; Samenleving</Badge>
    <Badge>Geopolitiek</Badge>
    <Badge>Economie</Badge>
  </div>
);

export const WithDot = () => (
  <Badge tone="accent" dot>Live transcriptie</Badge>
);
