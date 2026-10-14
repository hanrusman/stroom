import React from 'react';
import { Prose } from 'stroom-ds';

const summary = `## Kernpunten

De auteur betoogt dat **aandacht** het schaarste goed van het digitale tijdperk is. Drie observaties springen eruit:

- Algoritmische feeds optimaliseren voor *betrokkenheid*, niet voor begrip.
- Zelf samengestelde stromen herstellen de regie, maar vragen onderhoud.
- AI-samenvattingen kunnen die last verlichten — mits transparant gewogen.

> "We hebben geen gebrek aan informatie, maar aan een rustige plek om die te verwerken."

De conclusie is hoopvol: de techniek die ons afleidde, kan ons ook helpen focussen.`;

export const Summary = () => (
  <div className="w-[680px] max-w-full">
    <Prose markdown={summary} size="md" />
  </div>
);

export const ArticleSize = () => (
  <div className="w-[680px] max-w-full">
    <Prose
      size="lg"
      markdown={'Langzaam lezen is geen nostalgie. Het is een **discipline** — een bewuste keuze om één gedachte tot het einde te volgen voordat de volgende zich aandient.'}
    />
  </div>
);

export const Inverted = () => (
  <div className="w-[680px] max-w-full bg-brand-ink rounded-2xl p-6">
    <Prose
      invert
      size="md"
      markdown={'### Op een donkere kaart\n\nDe `prose-stroom-dark` variant houdt koppen en links leesbaar op ink- of accent-vlakken.'}
    />
  </div>
);
