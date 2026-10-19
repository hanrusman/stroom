import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, ChevronDown, ChevronUp, Loader2, Search } from 'lucide-react';
import { fetchTipMentions, fetchTips } from './api';
import type {
  TipCategory,
  TipMentionsResponse,
  TipSort,
  TipStrength,
  TipWork,
  TipsQuery,
  TipsResponse,
} from './api';

const CATEGORY_ORDER: TipCategory[] = [
  'book',
  'software',
  'film',
  'series',
  'documentary',
  'game',
  'podcast',
  'music',
  'youtube',
  'newsletter',
  'comic',
  'theatre',
  'other',
];

const CATEGORY_LABELS: Record<TipCategory, string> = {
  book: 'Boeken',
  software: 'Software',
  film: 'Films',
  series: 'Series',
  documentary: 'Documentaires',
  game: 'Games',
  podcast: 'Podcasts',
  music: 'Muziek',
  youtube: 'YouTube',
  newsletter: 'Nieuwsbrieven',
  comic: 'Strips',
  theatre: 'Theater',
  other: 'Overig',
};

const STRENGTH_LABELS: Record<TipStrength, string> = {
  strong: 'expliciete aanrader',
  medium: 'enthousiast besproken',
  weak: 'terloops genoemd',
};

type PeriodPreset = { id: string; label: string; days: number | null };

const PRESETS: PeriodPreset[] = [
  { id: 'all', label: 'Altijd', days: null },
  { id: 'month', label: 'Laatste maand', days: 30 },
  { id: 'quarter', label: '3 maanden', days: 91 },
  { id: 'year', label: 'Afgelopen jaar', days: 365 },
];

const toISODate = (d: Date): string =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

const formatDateNL = (iso: string): string =>
  new Date(`${iso}T00:00:00`).toLocaleDateString('nl-NL', { day: 'numeric', month: 'short', year: 'numeric' });

const inputClass =
  'bg-brand-surface rounded-full px-4 py-1.5 text-[13px] text-brand-ink border border-brand-ink/10 focus:outline-none focus:border-brand-accent focus-visible:ring-2 focus-visible:ring-brand-accent';

const chipClass = (active: boolean, small = false): string =>
  `rounded-full font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent ${
    small ? 'px-3 py-1 text-[11px]' : 'px-4 py-1.5 text-[12px]'
  } ${
    active
      ? 'bg-brand-accent text-brand-cream shadow-sm'
      : 'bg-brand-surface hover:bg-brand-surface-low text-brand-ink/70'
  }`;

export function TipsPage({ onBack, onOpenItem }: { onBack: () => void; onOpenItem: (id: string) => void }) {
  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [category, setCategory] = useState<TipCategory | null>(null);
  const [since, setSince] = useState<string | null>(null);
  const [preset, setPreset] = useState<string | null>('all');
  const [sort, setSort] = useState<TipSort>('score');
  const [strongOnly, setStrongOnly] = useState(false);
  const [minEpisodes, setMinEpisodes] = useState(false);
  const [source, setSource] = useState<string | null>(null);

  const [data, setData] = useState<TipsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [expanded, setExpanded] = useState<TipWork | null>(null);
  const [mentions, setMentions] = useState<TipMentionsResponse | null>(null);
  const [mentionsError, setMentionsError] = useState<string | null>(null);
  const mentionsCache = useRef<Map<string, TipMentionsResponse>>(new Map());
  const moreAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const t: ReturnType<typeof setTimeout> = setTimeout(() => setDebouncedQ(q), 300);
    return () => clearTimeout(t);
  }, [q]);

  const query = useMemo<TipsQuery>(
    () => ({
      q: debouncedQ.trim() || undefined,
      category: category ?? undefined,
      since: since ?? undefined,
      source: source ?? undefined,
      strongOnly: strongOnly || undefined,
      minEpisodes: minEpisodes ? 2 : undefined,
      sort,
      limit: 100,
    }),
    [debouncedQ, category, since, source, strongOnly, minEpisodes, sort],
  );

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setExpanded(null);
    fetchTips({ ...query, offset: 0, signal: controller.signal })
      .then(res => {
        if (controller.signal.aborted) return;
        setData(res);
        setLoading(false);
      })
      .catch(err => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
    return () => {
      controller.abort();
      moreAbortRef.current?.abort();
    };
  }, [query]);

  // 'since' staat bewust niet in de dependencies: dit effect hoeft alleen te draaien
  // wanneer een werk wordt opengeklapt, en elke filterwijziging (ook 'since') reset
  // 'expanded' al — de vastgelegde waarde kan dus niet verouderd zijn.
  useEffect(() => {
    if (!expanded) return;
    const cacheKey = `${expanded.title_key}|${expanded.category}|${since ?? ''}`;
    const cached = mentionsCache.current.get(cacheKey);
    if (cached) {
      setMentions(cached);
      return;
    }
    let cancelled = false;
    fetchTipMentions(expanded.title_key, expanded.category, since)
      .then(res => {
        if (cancelled) return;
        mentionsCache.current.set(cacheKey, res);
        setMentions(res);
      })
      .catch(err => {
        if (!cancelled) setMentionsError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [expanded]);

  const toggleExpand = (w: TipWork) => {
    if (expanded === w) {
      setExpanded(null);
      return;
    }
    setExpanded(w);
    setMentions(mentionsCache.current.get(`${w.title_key}|${w.category}|${since ?? ''}`) ?? null);
    setMentionsError(null);
  };

  const loadMore = () => {
    if (!data || loading || loadingMore || data.works.length >= data.total) return;
    const controller = new AbortController();
    moreAbortRef.current = controller;
    setLoadingMore(true);
    fetchTips({ ...query, offset: data.works.length, signal: controller.signal })
      .then(res => {
        if (controller.signal.aborted) return;
        setData(prev => (prev ? { ...prev, works: [...prev.works, ...res.works], total: res.total } : res));
      })
      .catch(err => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        setLoadingMore(false);
      });
  };

  return (
    <div className="max-w-4xl mx-auto pt-2">
      <button
        type="button"
        onClick={onBack}
        className="mb-8 font-mono text-[11px] uppercase tracking-[0.18em] text-brand-ink/50 hover:text-brand-accent flex items-center gap-2 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent"
      >
        <ArrowLeft size={14} /> Terug
      </button>

      <h1 className="font-display text-5xl md:text-6xl text-brand-ink font-medium tracking-[-0.04em] mb-4">Tips</h1>
      <p className="font-serif text-[15px] text-brand-ink/60 mb-2">
        Boeken, software, films, series, games en meer die in je podcasts en video&apos;s worden aangeraden.
      </p>
      <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-brand-ink/50 mb-8">
        {data ? `${data.total.toLocaleString('nl-NL')} werken` : '\u00A0'}
      </p>

      <div className="flex flex-wrap items-center gap-2 mb-10">
        <div className="relative w-full sm:w-72">
          <Search
            size={14}
            className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-brand-ink/40"
          />
          <input
            type="search"
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="Zoek titel, maker, persoon of podcast…"
            aria-label="Zoek titel, maker, persoon of podcast"
            className={`${inputClass} w-full pl-9`}
          />
        </div>

        <button
          type="button"
          onClick={() => setCategory(null)}
          aria-pressed={category === null}
          className={chipClass(category === null)}
        >
          Alles
        </button>
        {CATEGORY_ORDER.map(id => {
          const n = data?.categories[id] ?? 0;
          if (n === 0 && category !== id) return null;
          return (
            <button
              key={id}
              type="button"
              onClick={() => setCategory(id)}
              aria-pressed={category === id}
              className={chipClass(category === id)}
            >
              {CATEGORY_LABELS[id]} <span className="opacity-60">{n.toLocaleString('nl-NL')}</span>
            </button>
          );
        })}

        <div className="flex flex-wrap items-center gap-2">
          <label
            htmlFor="tips-since"
            className="font-mono text-[10px] uppercase tracking-[0.14em] text-brand-ink/50"
          >
            genoemd vanaf
          </label>
          <input
            id="tips-since"
            type="date"
            value={since ?? ''}
            onChange={e => {
              if (e.target.value) {
                setSince(e.target.value);
                setPreset(null);
              } else {
                setSince(null);
                setPreset('all');
              }
            }}
            className={inputClass}
          />
          {PRESETS.map(p => (
            <button
              key={p.id}
              type="button"
              aria-pressed={preset === p.id}
              onClick={() => {
                setPreset(p.id);
                if (p.days === null) {
                  setSince(null);
                } else {
                  const d = new Date();
                  d.setDate(d.getDate() - p.days);
                  setSince(toISODate(d));
                }
              }}
              className={chipClass(preset === p.id, true)}
            >
              {p.label}
            </button>
          ))}
        </div>

        <select
          value={sort}
          onChange={e => setSort(e.target.value as TipSort)}
          aria-label="Sortering"
          className={inputClass}
        >
          <option value="score">Meest aangeraden</option>
          <option value="episodes">Meeste afleveringen</option>
          <option value="recent">Recentst genoemd</option>
          <option value="title">Titel A–Z</option>
        </select>

        <label className="flex cursor-pointer items-center gap-2 rounded-full border border-brand-ink/10 bg-brand-surface px-4 py-1.5 text-[12px] font-medium text-brand-ink/70 transition-all hover:bg-brand-surface-low">
          <input
            type="checkbox"
            checked={strongOnly}
            onChange={e => setStrongOnly(e.target.checked)}
            className="accent-brand-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent"
          />
          alleen expliciete aanraders
        </label>
        <label className="flex cursor-pointer items-center gap-2 rounded-full border border-brand-ink/10 bg-brand-surface px-4 py-1.5 text-[12px] font-medium text-brand-ink/70 transition-all hover:bg-brand-surface-low">
          <input
            type="checkbox"
            checked={minEpisodes}
            onChange={e => setMinEpisodes(e.target.checked)}
            className="accent-brand-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent"
          />
          in 2+ afleveringen
        </label>

        <select
          value={source ?? ''}
          onChange={e => setSource(e.target.value || null)}
          aria-label="Podcast of kanaal"
          className={inputClass}
        >
          <option value="">Alle podcasts en kanalen</option>
          {(data?.sources ?? []).map(s => (
            <option key={s.name} value={s.name}>
              {s.name} ({s.n.toLocaleString('nl-NL')})
            </option>
          ))}
        </select>
      </div>

      {loading && !data && (
        <div className="flex justify-center py-12">
          <Loader2 size={20} className="animate-spin text-brand-ink/40" />
        </div>
      )}

      {error && <div className="text-red-600 text-sm mb-6">Fout: {error}</div>}

      {!loading && !error && data && data.works.length === 0 && (
        <p className="py-8 font-serif italic text-[15px] text-brand-ink/40">Niets gevonden. Kies een eerdere datum, een andere zoekterm of zet een filter uit.</p>
      )}

      {!error && data && data.works.length > 0 && (
        // Bij een nieuwe filterwaarde blijft de vorige lijst gedimd staan tot het antwoord er is.
        <ul className={loading ? 'opacity-50 transition-opacity' : 'transition-opacity'} aria-busy={loading}>
          {data.works.map(w => {
            const isOpen = expanded === w;
            return (
              <li key={`${w.category}|${w.title_key}`} className="border-t border-brand-ink/10">
                <button
                  type="button"
                  onClick={() => toggleExpand(w)}
                  aria-expanded={isOpen}
                  className="block w-full rounded pt-5 pb-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent"
                >
                  <span className="flex items-baseline justify-between gap-4">
                    <span className="min-w-0">
                      <span className="font-display text-xl text-brand-ink">{w.title}</span>
                      {w.creator && <span className="font-serif italic text-brand-ink/50"> — {w.creator}</span>}
                    </span>
                    <span className="flex shrink-0 items-center gap-2 whitespace-nowrap font-mono text-[12px] text-brand-ink/50">
                      <span>{w.episodes}×</span>
                      {w.strong > 0 && <span>★{w.strong}</span>}
                      {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </span>
                  </span>
                  {w.blurb && (
                    <span className="mt-1 block line-clamp-2 font-serif text-[14px] text-brand-ink/80">{w.blurb}</span>
                  )}
                  <span className="mt-2 block">
                    <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-brand-accent">
                      {CATEGORY_LABELS[w.category]}
                    </span>
                    {w.who.length > 0 && (
                      <span className="ml-2 text-[12px] text-brand-ink/50">
                        door {w.who.slice(0, 3).join(', ')}
                        {w.who.length > 3 ? ` en ${w.who.length - 3} anderen` : ''}
                      </span>
                    )}
                  </span>
                </button>

                {isOpen && (
                  <div className="pb-6">
                    {mentionsError && <p className="mb-4 text-sm text-red-600">Fout: {mentionsError}</p>}
                    {!mentionsError && !mentions && (
                      <div className="flex justify-center py-4">
                        <Loader2 size={16} className="animate-spin text-brand-ink/40" />
                      </div>
                    )}
                    {mentions && (
                      <div className="space-y-4">
                        {mentions.mentions.map(m => (
                          <div
                            key={m.item_id}
                            className={`border-l-2 pl-4 ${m.strength === 'strong' ? 'border-brand-accent' : 'border-brand-ink/15'}`}
                          >
                            <p className="font-mono text-[11px] text-brand-ink/50">
                              <span className="font-semibold">{m.by}</span>
                              {' · '}
                              <button
                                type="button"
                                onClick={() => onOpenItem(m.item_id)}
                                className="rounded underline-offset-2 hover:text-brand-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent"
                              >
                                {m.episode}
                              </button>
                              {m.published && <>{' · '}{formatDateNL(m.published)}</>}
                              {' · '}
                              {STRENGTH_LABELS[m.strength]}
                            </p>
                            {m.quote && (
                              <q className="mt-1 block font-serif italic text-[14px] text-brand-ink/80">{m.quote}</q>
                            )}
                            {m.why && <p className="mt-1 font-serif text-[14px] text-brand-ink/80">{m.why}</p>}
                          </div>
                        ))}
                      </div>
                    )}
                    {w.aka.length > 0 && (
                      <p className="mt-6 font-serif text-[13px] text-brand-ink/50">
                        Ook gehoord als: {w.aka.join(', ')}
                      </p>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {!loading && !error && data && data.works.length < data.total && (
        <div className="flex justify-center border-t border-brand-ink/10 pt-8">
          <button
            type="button"
            onClick={loadMore}
            disabled={loadingMore}
            className="flex items-center gap-2 rounded-full border border-brand-ink/15 px-6 py-2 font-mono text-[11px] uppercase tracking-[0.18em] text-brand-ink/60 transition-all hover:border-brand-accent hover:text-brand-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent disabled:opacity-50"
          >
            {loadingMore ? (
              <>
                <Loader2 size={14} className="animate-spin" /> Laden…
              </>
            ) : (
              'Toon meer'
            )}
          </button>
        </div>
      )}
    </div>
  );
}
