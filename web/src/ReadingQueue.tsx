import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { ListPlus, Check, Archive, X, RefreshCw } from 'lucide-react';
import { changeReadingQueue, fetchReadingQueue, fetchReadingQueueIds, HuygensItem, setItemStatus } from './api';
import { excerptText } from './contentText';

const QueueContext = createContext<{
  ids: Set<string>; busy: Set<string>; error: string | null;
  refresh: () => Promise<void>; change: (id: string, queued: boolean) => Promise<boolean>;
}>(null!);
export const useReadingQueue = () => useContext(QueueContext);
export function ReadingQueueProvider({ children }: { children: React.ReactNode }) {
  const [ids, setIds] = useState(new Set<string>());
  const [busy, setBusy] = useState(new Set<string>());
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(new Set<string>());
  const revision = useRef(0);
  const refresh = useCallback(async () => {
    const version = ++revision.current;
    try { const result = await fetchReadingQueueIds(); if (version === revision.current) { setIds(new Set(result)); setError(null); } }
    catch (e) { if (version === revision.current) setError(`Wachtrij ophalen mislukt: ${String(e)}. Controleer of de server is bijgewerkt.`); }
  }, []);
  useEffect(() => {
    void refresh();
    const focus = () => { void refresh(); };
    const archived = (event: Event) => {
      const { id, status } = (event as CustomEvent).detail;
      if (status === 'archived') { ++revision.current; setIds(old => { const next = new Set(old); next.delete(id); return next; }); }
    };
    window.addEventListener('focus', focus); window.addEventListener('stroom:item-status', archived);
    return () => { window.removeEventListener('focus', focus); window.removeEventListener('stroom:item-status', archived); };
  }, [refresh]);
  const change = async (id: string, queued: boolean) => {
    if (pending.current.has(id)) return false;
    pending.current.add(id); setBusy(new Set(pending.current)); ++revision.current;
    try {
      await changeReadingQueue(id, queued);
      ++revision.current;
      setIds(old => { const next = new Set(old); if (queued) next.add(id); else next.delete(id); return next; });
      setError(null); await refresh(); return true;
    } catch (e) { setError(`Wachtrij wijzigen mislukt: ${String(e)}`); return false; }
    finally { pending.current.delete(id); setBusy(new Set(pending.current)); }
  };
  return <QueueContext.Provider value={{ ids, busy, error, refresh, change }}>{children}</QueueContext.Provider>;
}
export function QueueButton({ id, archived = false }: { id: string; archived?: boolean }) {
  const queue = useReadingQueue(); const queued = queue.ids.has(id);
  return <button type="button" disabled={queue.busy.has(id) || archived}
    title={archived ? 'Haal eerst uit het archief' : queued ? 'Verwijder uit wachtrij' : 'In wachtrij'}
    aria-label={queued ? 'Verwijder uit wachtrij' : 'In wachtrij'} aria-pressed={queued}
    className={`min-w-11 min-h-11 inline-flex items-center justify-center rounded-full disabled:opacity-40 ${queued ? 'text-brand-accent bg-brand-accent/10' : 'text-brand-ink/60 hover:bg-brand-ink/5'}`}
    onClick={e => { e.preventDefault(); e.stopPropagation(); void queue.change(id, !queued); }}>
    {queued ? <Check size={18} /> : <ListPlus size={18} />}
  </button>;
}
export function ReadingQueuePage({ onOpen, onBack }: { onOpen: (id: string) => void; onBack: () => void }) {
  const queue = useReadingQueue();
  const [items, setItems] = useState<HuygensItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [more, setMore] = useState(false);
  const [working, setWorking] = useState<string | null>(null);
  const load = async (append = false) => {
    setLoading(true);
    try {
      const rows = await fetchReadingQueue(append ? items.filter(i => queue.ids.has(i.id)).length : 0);
      setItems(old => append ? [...old, ...rows.filter(row => !old.some(x => x.id === row.id))] : rows);
      setMore(rows.length === 100); setError(null); await queue.refresh();
    } catch (e) { setError(String(e)); } finally { setLoading(false); }
  };
  useEffect(() => {
    void load();
    const focus = () => { void load(); };
    window.addEventListener('focus', focus);
    return () => window.removeEventListener('focus', focus);
  }, []);
  return <section className="max-w-3xl mx-auto">
    <button onClick={onBack} className="min-h-11 text-brand-accent">← Terug naar Stroom</button>
    <h1 className="font-display text-5xl my-5">Jouw wachtrij</h1>
    <p className="text-brand-ink/60 mb-6">Eén lijst voor lezen, kijken en luisteren. Het eerst toegevoegde item staat bovenaan. Gedeeld met je iPhone.</p>
    <button onClick={() => void load()} disabled={loading} className="min-h-11 inline-flex items-center gap-2"><RefreshCw size={16} /> Verversen</button>
    {(error || queue.error) && <p role="alert" className="text-red-600 py-3">{error || queue.error}</p>}
    {!loading && !error && !queue.error && !items.some(i => queue.ids.has(i.id)) && <p className="py-12 text-brand-ink/60">Je wachtrij is leeg. Voeg iets toe met het wachtrij-icoon op een kaart of in de reader.</p>}
    {items.filter(i => queue.ids.has(i.id)).map(item => <article key={item.id} className="py-6 border-b border-brand-ink/10">
      <p className="text-xs text-brand-ink/50 uppercase tracking-wider">{item.source_name} · {item.format}</p>
      <button onClick={() => onOpen(item.id)} className="text-left font-display text-2xl my-2 hover:text-brand-accent">{item.title}</button>
      <p className="text-sm text-brand-ink/60 line-clamp-2">{excerptText(item.description)}</p>
      <div className="flex gap-4 mt-3 text-sm">
        <button disabled={working === item.id} className="min-h-11 inline-flex items-center gap-2" onClick={async () => {
          setWorking(item.id); try { await setItemStatus(item.id, 'archived'); setError(null); }
          catch(e) { setError(String(e)); } finally { setWorking(null); }
        }}><Archive size={16} /> Gelezen · archiveren</button>
        <button disabled={queue.busy.has(item.id)} className="min-h-11 inline-flex items-center gap-2" onClick={() => void queue.change(item.id, false)}><X size={16} /> Uit wachtrij</button>
      </div>
    </article>)}
    {loading && <p role="status" className="py-6">Wachtrij ophalen…</p>}
    {more && <button className="min-h-11" disabled={loading} onClick={() => void load(true)}>Meer ophalen</button>}
  </section>;
}
