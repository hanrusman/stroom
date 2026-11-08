// Pure helpers voor de dossierpagina (ResearchPage.tsx); los getest in researchText.test.ts.

export const STAGES = [
  { id: 'planning', label: 'Plan maken', detail: 'De vraag uiteenrafelen in aspecten en 20+ zoekvragen (NL/EN).' },
  { id: 'recall', label: 'Archief doorzoeken', detail: 'Elke zoekvraag op trefwoord én betekenis; bronnen die vaak opduiken winnen.' },
  { id: 'screening', label: 'Screenen', detail: 'Titels en teasers in batches beoordelen op relevantie.' },
  { id: 'extracting', label: 'Bronnen lezen', detail: 'Per relevante bron de concrete beweringen, actoren en citaten eruit halen.' },
  { id: 'deepening', label: 'Verdiepen', detail: 'Kijken wat ontbreekt (tegengeluid, regio’s, harder bewijs) en daar gericht verder zoeken.' },
  { id: 'writing', label: 'Dossier schrijven', detail: 'Het sterkste model schrijft het dossier over alle bevindingen.' },
  { id: 'critiquing', label: 'Kritische review', detail: 'Een model uit een andere familie toetst onderbouwing en tegengeluid.' },
  { id: 'revising', label: 'Herzien', detail: 'De kritiek verwerken in de definitieve versie.' },
] as const;

export function stageIndex(status: string): number {
  if (status === 'queued') return 0;
  if (status === 'done') return STAGES.length;
  const i = STAGES.findIndex(s => s.id === status);
  return i < 0 ? 0 : i;
}

const CITE_RE = /\[(S\d+(?:\s*,\s*S\d+)*)\]/g;

/** Vervangt [S3, S12] in (al gesaneerde) HTML door klikbare knoppen. Alleen cijfers
 *  komen in de markup terecht, dus dit kan na DOMPurify zonder nieuw risico. */
export function citationsToButtons(html: string): string {
  return html.replace(CITE_RE, (_m, inner: string) => {
    const refs = inner.split(',').map(r => r.trim()).filter(r => /^S\d+$/.test(r));
    const btns = refs.map(r =>
      `<button type="button" class="cite" data-ref="${r}" aria-label="Bron ${r.slice(1)}">${r.slice(1)}</button>`);
    return `<span class="cites">${btns.join('')}</span>`;
  });
}

export function formatDateNL(iso: string | null | undefined): string {
  if (!iso) return '?';
  const d = new Date(iso.length <= 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return '?';
  return d.toLocaleDateString('nl-NL', { day: 'numeric', month: 'short', year: 'numeric' });
}

/** Aantal bronnen per maand, van de eerste tot de laatste maand (lege maanden = 0). */
export function monthHistogram(dates: (string | null)[]): { month: string; label: string; n: number }[] {
  const months = dates.filter((d): d is string => !!d && /^\d{4}-\d{2}/.test(d)).map(d => d.slice(0, 7)).sort();
  if (!months.length) return [];
  const counts = new Map<string, number>();
  for (const m of months) counts.set(m, (counts.get(m) ?? 0) + 1);
  const out: { month: string; label: string; n: number }[] = [];
  let [y, mo] = months[0].split('-').map(Number);
  const [ey, em] = months[months.length - 1].split('-').map(Number);
  // Max 60 maanden tonen; oudere bronnen tellen dan mee in de eerste balk.
  const span = (ey - y) * 12 + (em - mo);
  if (span > 59) {
    const start = new Date(ey, em - 1 - 59, 1);
    let early = 0;
    for (const [m, n] of counts) if (m < `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}`) early += n;
    y = start.getFullYear(); mo = start.getMonth() + 1;
    const k = `${y}-${String(mo).padStart(2, '0')}`;
    counts.set(k, (counts.get(k) ?? 0) + early);
  }
  while (y < ey || (y === ey && mo <= em)) {
    const k = `${y}-${String(mo).padStart(2, '0')}`;
    const label = new Date(y, mo - 1, 1).toLocaleDateString('nl-NL', { month: 'short', year: '2-digit' });
    out.push({ month: k, label, n: counts.get(k) ?? 0 });
    mo += 1;
    if (mo > 12) { mo = 1; y += 1; }
  }
  return out;
}

/** 754 → "12:34", 3725 → "1:02:05". */
export function fmtClock(secs: number): string {
  const s = Math.max(0, Math.floor(secs));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const mm = h ? String(m).padStart(2, '0') : String(m);
  return `${h ? `${h}:` : ''}${mm}:${String(r).padStart(2, '0')}`;
}

/** YouTube-id uit de vormen die in Stroom voorkomen (/v/, watch?v=, youtu.be/, /embed/). */
export function youtubeId(url: string | null | undefined): string | null {
  if (!url) return null;
  const m = url.match(/(?:youtube\.com\/(?:v\/|embed\/|shorts\/|watch\?(?:.*&)?v=)|youtu\.be\/)([A-Za-z0-9_-]{11})/);
  return m ? m[1] : null;
}

export function youtubeAt(id: string, secs: number): string {
  return `https://www.youtube.com/watch?v=${id}&t=${Math.max(0, Math.floor(secs))}s`;
}
