import React from 'react';
import { ContentCard, IconButton } from 'stroom-ds';
import { Bookmark, Archive } from 'lucide-react';

export const Article = () => (
  <ContentCard
    format="article"
    title="De stille herontdekking van het langzame internet"
    summary="Weg van de algoritmische tijdlijn ontstaat een nieuwe generatie lezers die bewust kiest voor RSS, nieuwsbrieven en zelf samengestelde stromen — en daarmee de regie over hun aandacht terugneemt."
    sourceName="De Correspondent"
    meta="8 min"
    actions={
      <div className="flex items-center gap-1">
        <IconButton aria-label="Bewaren" size="sm"><Bookmark size={16} /></IconButton>
        <IconButton aria-label="Archiveren" size="sm"><Archive size={16} /></IconButton>
      </div>
    }
  />
);

export const Podcast = () => (
  <ContentCard
    format="podcast"
    title="Lex Fridman — Over de toekomst van open-source AI"
    sourceName="Lex Fridman Podcast"
    meta="2u 14m"
  />
);

export const Video = () => (
  <ContentCard
    format="video"
    title="Hoe pgvector semantisch zoeken mogelijk maakt"
    summary="Een heldere uitleg van embeddings, indexering en similarity search in Postgres."
    sourceName="YouTube · Dwarkesh"
    meta="22 min"
  />
);

export const NoImage = () => (
  <ContentCard
    format="article"
    title="Een korte geschiedenis van de feedreader"
    summary="Van NetNewsWire tot de teloorgang van Google Reader en de stille wederopstanding daarna."
    sourceName="Stroom"
    meta="5 min"
  />
);
