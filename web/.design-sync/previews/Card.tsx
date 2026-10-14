import React from 'react';
import { Card, Badge, Button } from 'stroom-ds';

export const Variants = () => (
  <div className="flex flex-wrap gap-4">
    <Card className="p-6 w-60">
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/45 mb-2">Surface</div>
      <h3 className="font-serif font-semibold text-[18px] text-brand-ink leading-tight">De stille kracht van langzaam lezen</h3>
    </Card>
    <Card variant="tint" className="p-6 w-60">
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/45 mb-2">Tint</div>
      <h3 className="font-serif font-semibold text-[18px] text-brand-ink leading-tight">Een wekelijkse digest van wat ertoe doet</h3>
    </Card>
    <Card variant="outline" className="p-6 w-60">
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/45 mb-2">Outline</div>
      <h3 className="font-serif font-semibold text-[18px] text-brand-ink leading-tight">Bronnen toevoegen aan je stroom</h3>
    </Card>
  </div>
);

export const Composed = () => (
  <Card large className="p-7 w-80">
    <Badge tone="tint" className="mb-4">Digest · week 25</Badge>
    <h3 className="font-serif font-semibold text-[22px] text-brand-ink leading-[1.2] tracking-[-0.01em] mb-2">
      Wat je deze week niet wilde missen
    </h3>
    <p className="text-brand-ink/70 text-[13px] leading-[1.55] mb-5">
      Zeven artikelen, twee podcasts en een lange video — gewogen op jouw interesses en
      teruggebracht tot de kern.
    </p>
    <Button variant="primary" size="sm">Lees de digest</Button>
  </Card>
);

export const Interactive = () => (
  <Card interactive large className="p-6 w-72">
    <h3 className="font-serif font-semibold text-[18px] text-brand-ink leading-tight mb-1">Klikbare kaart</h3>
    <p className="text-brand-ink/60 text-[13px]">De hele kaart is een doelwit — hover voor de elevatie.</p>
  </Card>
);
