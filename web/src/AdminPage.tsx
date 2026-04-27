import React, { useEffect, useState } from 'react';
import { ArrowLeft, Plus, Pencil, Check, X, Trash2, Loader2, RefreshCw, ListOrdered } from 'lucide-react';
import {
  AdminSource, AdminSourceUpdate, AdminSourceCreate, SourceKind,
  fetchAdminSources, updateAdminSource, createAdminSource, deleteAdminSource,
  refreshAdminSource, refreshAllAdminSources, fetchAdminQueue, QueueItem,
  fetchTopics, Topic, ApiError,
} from './api';

const KINDS: SourceKind[] = ['rss', 'podcast', 'youtube'];

const TopicChips = ({ all, selected, onToggle }: {
  all: Topic[]; selected: string[]; onToggle: (slug: string) => void;
}) => (
  <div className="flex flex-wrap gap-1.5">
    {all.map(t => {
      const on = selected.includes(t.slug);
      return (
        <button key={t.slug} type="button" onClick={() => onToggle(t.slug)}
          className={`px-2.5 py-1 rounded-full text-[11px] font-mono uppercase tracking-[0.1em] transition ${
            on ? 'bg-brand-blue text-brand-cream' : 'bg-brand-surface text-brand-ink/50 hover:bg-brand-surface-low'
          }`}>
          {t.slug}
        </button>
      );
    })}
  </div>
);


const SourceRow = ({ src, topics, onSaved, onDeleted, onRefreshed }: {
  key?: React.Key; src: AdminSource; topics: Topic[];
  onSaved: (s: AdminSource) => void;
  onDeleted: (id: string) => void;
  onRefreshed: (id: string, msg: string) => void;
}) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<AdminSourceUpdate>({});
  const [busy, setBusy] = useState<'save' | 'delete' | 'refresh' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const startEdit = () => {
    setDraft({
      name: src.name, url: src.url, kind: src.kind, image_url: src.image_url,
      weight: src.weight, max_per_rail: src.max_per_rail, active: src.active,
      poll_interval_min: src.poll_interval_min, topic_slugs: [...src.topic_slugs],
    });
    setEditing(true);
    setError(null);
  };

  const save = async () => {
    setBusy('save'); setError(null);
    try {
      const updated = await updateAdminSource(src.id, draft);
      onSaved(updated);
      setEditing(false);
    } catch (e) { setError(e instanceof ApiError ? e.detail : String(e)); }
    finally { setBusy(null); }
  };

  const remove = async () => {
    if (!confirm(`Source "${src.name}" + alle ${src.item_count} items verwijderen?`)) return;
    setBusy('delete'); setError(null);
    try { await deleteAdminSource(src.id); onDeleted(src.id); }
    catch (e) { setError(e instanceof ApiError ? e.detail : String(e)); setBusy(null); }
  };

  const refresh = async () => {
    setBusy('refresh'); setError(null);
    try {
      const r = await refreshAdminSource(src.id);
      onRefreshed(src.id, `${src.name}: ${r.inserted} nieuwe items (${r.checked} gecheckt)`);
    } catch (e) { setError(e instanceof ApiError ? e.detail : String(e)); }
    finally { setBusy(null); }
  };

  const toggleSlug = (slug: string) => {
    const cur = draft.topic_slugs ?? [];
    setDraft({ ...draft, topic_slugs: cur.includes(slug) ? cur.filter(s => s !== slug) : [...cur, slug] });
  };

  if (!editing) {
    return (
      <tr className={`border-b border-brand-ink/5 hover:bg-brand-surface-low ${!src.active ? 'opacity-50' : ''}`}>
        <td className="py-4 px-4 align-top">
          <div className="font-medium text-brand-ink leading-tight">{src.name}</div>
          <div className="text-brand-ink/40 text-[11px] truncate max-w-[280px] font-mono mt-1">{src.url}</div>
        </td>
        <td className="py-4 pr-4 align-top font-mono text-[10px] uppercase tracking-[0.1em] text-brand-ink/50">{src.kind}</td>
        <td className="py-4 pr-4 align-top">
          <div className="flex flex-wrap gap-1 max-w-[200px]">
            {src.topic_slugs.map(s => <span key={s} className="px-1.5 py-0.5 rounded bg-brand-surface text-brand-ink/60 text-[10px] font-mono">{s}</span>)}
            {src.topic_slugs.length === 0 && <span className="text-brand-ink/30 text-xs italic">geen</span>}
          </div>
        </td>
        <td className="py-4 pr-4 align-top text-center font-mono text-sm">{src.weight}</td>
        <td className="py-4 pr-4 align-top text-center font-mono text-sm text-brand-ink/50">{src.max_per_rail ?? '∞'}</td>
        <td className="py-4 pr-4 align-top text-center font-mono text-sm text-brand-ink/50">{src.item_count}</td>
        <td className="py-4 pr-4 align-top">
          {src.active
            ? <span className="inline-block px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 text-[10px] font-mono uppercase tracking-[0.1em]">actief</span>
            : <span className="inline-block px-2 py-0.5 rounded-full bg-brand-surface text-brand-ink/40 text-[10px] font-mono uppercase tracking-[0.1em]">uit</span>}
        </td>
        <td className="py-4 pr-4 align-top text-right whitespace-nowrap">
          <div className="inline-flex items-center gap-0.5">
            <button onClick={refresh} disabled={busy !== null} title="Refresh feed"
              className="p-2 hover:bg-blue-50 rounded text-blue-600 disabled:opacity-30">
              {busy === 'refresh' ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            </button>
            <button onClick={startEdit} disabled={busy !== null} title="Bewerken"
              className="p-2 hover:bg-brand-surface rounded text-brand-ink/50 disabled:opacity-30"><Pencil size={14} /></button>
            <button onClick={remove} disabled={busy !== null} title="Verwijderen"
              className="p-2 hover:bg-red-50 rounded text-red-600 disabled:opacity-30">
              {busy === 'delete' ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            </button>
          </div>
          {error && <div className="text-red-600 text-[10px] mt-1 max-w-[200px]">{error}</div>}
        </td>
      </tr>
    );
  }

  return (
    <tr className="border-b border-brand-ink/5 bg-amber-50/30">
      <td className="py-3 px-4 align-top">
        <input value={draft.name ?? ''} onChange={e => setDraft({ ...draft, name: e.target.value })}
          placeholder="Naam"
          className="w-full px-2.5 py-1.5 rounded-md border border-brand-ink/20 text-sm bg-brand-cream" />
        <input value={draft.url ?? ''} onChange={e => setDraft({ ...draft, url: e.target.value })}
          placeholder="Feed URL"
          className="mt-1.5 w-full px-2.5 py-1.5 rounded-md border border-brand-ink/20 text-[11px] font-mono bg-brand-cream" />
        <div className="mt-1.5 flex items-center gap-2">
          {draft.image_url && <img src={draft.image_url} alt="" className="w-8 h-8 rounded object-cover bg-brand-surface shrink-0" />}
          <input value={draft.image_url ?? ''} onChange={e => setDraft({ ...draft, image_url: e.target.value || null })}
            placeholder="Image URL (optioneel)"
            className="flex-1 px-2.5 py-1.5 rounded-md border border-brand-ink/20 text-[11px] font-mono bg-brand-cream" />
        </div>
      </td>
      <td className="py-3 pr-4 align-top">
        <select value={draft.kind} onChange={e => setDraft({ ...draft, kind: e.target.value as SourceKind })}
          className="px-2 py-1.5 rounded-md border border-brand-ink/20 text-sm bg-brand-cream">
          {KINDS.map(k => <option key={k} value={k}>{k}</option>)}
        </select>
      </td>
      <td className="py-3 pr-4 align-top max-w-[200px]">
        <TopicChips all={topics} selected={draft.topic_slugs ?? []} onToggle={toggleSlug} />
      </td>
      <td className="py-3 pr-4 align-top text-center">
        <input type="number" min={1} max={10} value={draft.weight ?? 5}
          onChange={e => setDraft({ ...draft, weight: Number(e.target.value) })}
          className="w-14 px-2 py-1.5 rounded-md border border-brand-ink/20 text-sm bg-brand-cream text-center" />
      </td>
      <td className="py-3 pr-4 align-top text-center">
        <input type="number" min={1} placeholder="∞" value={draft.max_per_rail ?? ''}
          onChange={e => setDraft({ ...draft, max_per_rail: e.target.value === '' ? null : Number(e.target.value) })}
          className="w-14 px-2 py-1.5 rounded-md border border-brand-ink/20 text-sm bg-brand-cream text-center" />
      </td>
      <td className="py-3 pr-4 align-top text-center text-brand-ink/30 text-xs">—</td>
      <td className="py-3 pr-4 align-top">
        <label className="flex items-center gap-1.5 text-xs cursor-pointer">
          <input type="checkbox" checked={draft.active ?? false}
            onChange={e => setDraft({ ...draft, active: e.target.checked })} />
          actief
        </label>
      </td>
      <td className="py-3 pr-4 align-top text-right whitespace-nowrap">
        <div className="inline-flex gap-0.5">
          <button onClick={save} disabled={busy !== null} title="Opslaan"
            className="p-2 hover:bg-emerald-50 rounded text-emerald-700 disabled:opacity-30">
            {busy === 'save' ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
          </button>
          <button onClick={() => setEditing(false)} title="Annuleren"
            className="p-2 hover:bg-brand-surface rounded text-brand-ink/50"><X size={14} /></button>
        </div>
        {error && <div className="text-red-600 text-[10px] mt-1 max-w-[200px]">{error}</div>}
      </td>
    </tr>
  );
};


const SourceCard = ({ src, topics, onSaved, onDeleted, onRefreshed }: {
  key?: React.Key; src: AdminSource; topics: Topic[];
  onSaved: (s: AdminSource) => void;
  onDeleted: (id: string) => void;
  onRefreshed: (id: string, msg: string) => void;
}) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<AdminSourceUpdate>({});
  const [busy, setBusy] = useState<'save' | 'delete' | 'refresh' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const startEdit = () => {
    setDraft({
      name: src.name, url: src.url, kind: src.kind, image_url: src.image_url,
      weight: src.weight, max_per_rail: src.max_per_rail, active: src.active,
      poll_interval_min: src.poll_interval_min, topic_slugs: [...src.topic_slugs],
    });
    setEditing(true); setError(null);
  };

  const save = async () => {
    setBusy('save'); setError(null);
    try {
      const updated = await updateAdminSource(src.id, draft);
      onSaved(updated);
      setEditing(false);
    } catch (e) { setError(e instanceof ApiError ? e.detail : String(e)); }
    finally { setBusy(null); }
  };

  const remove = async () => {
    if (!confirm(`Source "${src.name}" + alle ${src.item_count} items verwijderen?`)) return;
    setBusy('delete'); setError(null);
    try { await deleteAdminSource(src.id); onDeleted(src.id); }
    catch (e) { setError(e instanceof ApiError ? e.detail : String(e)); setBusy(null); }
  };

  const refresh = async () => {
    setBusy('refresh'); setError(null);
    try {
      const r = await refreshAdminSource(src.id);
      onRefreshed(src.id, `${src.name}: ${r.inserted} nieuwe items (${r.checked} gecheckt)`);
    } catch (e) { setError(e instanceof ApiError ? e.detail : String(e)); }
    finally { setBusy(null); }
  };

  const toggleSlug = (slug: string) => {
    const cur = draft.topic_slugs ?? [];
    setDraft({ ...draft, topic_slugs: cur.includes(slug) ? cur.filter(s => s !== slug) : [...cur, slug] });
  };

  if (!editing) {
    return (
      <div className={`rounded-2xl bg-brand-cream border border-brand-ink/10 p-4 ${!src.active ? 'opacity-60' : ''}`}>
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="min-w-0 flex-1">
            <div className="font-medium text-brand-ink leading-tight">{src.name}</div>
            <div className="text-brand-ink/40 text-[11px] truncate font-mono mt-0.5">{src.url}</div>
          </div>
          <span className={`shrink-0 inline-block px-2 py-0.5 rounded-full text-[10px] font-mono uppercase tracking-[0.1em] ${
            src.active ? 'bg-emerald-50 text-emerald-700' : 'bg-brand-surface text-brand-ink/40'
          }`}>{src.active ? 'actief' : 'uit'}</span>
        </div>
        <div className="flex flex-wrap gap-1 mb-3">
          {src.topic_slugs.map(s => (
            <span key={s} className="px-1.5 py-0.5 rounded bg-brand-surface text-brand-ink/60 text-[10px] font-mono">{s}</span>
          ))}
          {src.topic_slugs.length === 0 && <span className="text-brand-ink/30 text-xs italic">geen topics</span>}
        </div>
        <div className="flex items-center justify-between text-[11px] font-mono text-brand-ink/50 border-t border-brand-ink/5 pt-3">
          <div className="flex gap-3">
            <span><span className="text-brand-ink/40">kind:</span> {src.kind}</span>
            <span><span className="text-brand-ink/40">weight:</span> {src.weight}</span>
            <span><span className="text-brand-ink/40">items:</span> {src.item_count}</span>
          </div>
          <div className="inline-flex items-center gap-0.5">
            <button onClick={refresh} disabled={busy !== null} title="Refresh feed"
              className="p-2 hover:bg-blue-50 rounded text-blue-600 disabled:opacity-30">
              {busy === 'refresh' ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            </button>
            <button onClick={startEdit} disabled={busy !== null} title="Bewerken"
              className="p-2 hover:bg-brand-surface rounded text-brand-ink/50 disabled:opacity-30"><Pencil size={14} /></button>
            <button onClick={remove} disabled={busy !== null} title="Verwijderen"
              className="p-2 hover:bg-red-50 rounded text-red-600 disabled:opacity-30">
              {busy === 'delete' ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            </button>
          </div>
        </div>
        {error && <div className="text-red-600 text-[11px] mt-2">{error}</div>}
      </div>
    );
  }

  return (
    <div className="rounded-2xl bg-amber-50/40 border border-amber-200 p-4 space-y-3">
      <input value={draft.name ?? ''} onChange={e => setDraft({ ...draft, name: e.target.value })}
        placeholder="Naam"
        className="w-full px-3 py-2 rounded-md border border-brand-ink/20 text-sm bg-brand-cream" />
      <input value={draft.url ?? ''} onChange={e => setDraft({ ...draft, url: e.target.value })}
        placeholder="Feed URL"
        className="w-full px-3 py-2 rounded-md border border-brand-ink/20 text-[12px] font-mono bg-brand-cream" />
      <div className="flex items-center gap-2">
        {draft.image_url && <img src={draft.image_url} alt="" className="w-10 h-10 rounded object-cover bg-brand-surface shrink-0" />}
        <input value={draft.image_url ?? ''} onChange={e => setDraft({ ...draft, image_url: e.target.value || null })}
          placeholder="Image URL (optioneel — wordt anders auto uit feed gehaald)"
          className="flex-1 px-3 py-2 rounded-md border border-brand-ink/20 text-[12px] font-mono bg-brand-cream" />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="block text-[10px] uppercase tracking-[0.15em] text-brand-ink/50 mb-1 font-mono">Kind</span>
          <select value={draft.kind} onChange={e => setDraft({ ...draft, kind: e.target.value as SourceKind })}
            className="w-full px-2 py-1.5 rounded-md border border-brand-ink/20 text-sm bg-brand-cream">
            {KINDS.map(k => <option key={k} value={k}>{k}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="block text-[10px] uppercase tracking-[0.15em] text-brand-ink/50 mb-1 font-mono">Weight</span>
          <input type="number" min={1} max={10} value={draft.weight ?? 5}
            onChange={e => setDraft({ ...draft, weight: Number(e.target.value) })}
            className="w-full px-2 py-1.5 rounded-md border border-brand-ink/20 text-sm bg-brand-cream" />
        </label>
      </div>
      <div>
        <span className="block text-[10px] uppercase tracking-[0.15em] text-brand-ink/50 mb-1 font-mono">Topics</span>
        <TopicChips all={topics} selected={draft.topic_slugs ?? []} onToggle={toggleSlug} />
      </div>
      <label className="flex items-center gap-2 text-sm cursor-pointer">
        <input type="checkbox" checked={draft.active ?? false}
          onChange={e => setDraft({ ...draft, active: e.target.checked })} />
        Actief
      </label>
      {error && <div className="text-red-600 text-[11px]">{error}</div>}
      <div className="flex gap-2 pt-1">
        <button onClick={save} disabled={busy !== null}
          className="flex-1 px-3 py-2 rounded-xl bg-emerald-600 text-brand-cream text-sm flex items-center justify-center gap-1 hover:bg-emerald-700 disabled:opacity-50">
          {busy === 'save' ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Opslaan
        </button>
        <button onClick={() => setEditing(false)}
          className="px-3 py-2 rounded-xl bg-brand-surface-low text-brand-ink/75 text-sm hover:bg-brand-ink/10">
          Annuleren
        </button>
      </div>
    </div>
  );
};


const NewSourceForm = ({ topics, onCreated }: {
  topics: Topic[]; onCreated: (s: AdminSource) => void;
}) => {
  const [open, setOpen] = useState(false);
  const empty: AdminSourceCreate = {
    name: '', url: '', kind: 'rss', image_url: null,
    weight: 5, max_per_rail: null, active: true, poll_interval_min: 60, topic_slugs: [],
  };
  const [form, setForm] = useState<AdminSourceCreate>(empty);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const created = await createAdminSource(form);
      onCreated(created);
      setForm(empty);
      setOpen(false);
    } catch (e) { setError(e instanceof ApiError ? e.detail : String(e)); }
    finally { setBusy(false); }
  };

  const toggleSlug = (slug: string) => {
    setForm({ ...form,
      topic_slugs: form.topic_slugs.includes(slug)
        ? form.topic_slugs.filter(s => s !== slug)
        : [...form.topic_slugs, slug] });
  };

  if (!open) {
    return (
      <button onClick={() => setOpen(true)}
        className="px-4 py-2.5 rounded-xl bg-brand-blue text-brand-cream text-sm flex items-center gap-2 hover:opacity-90 transition">
        <Plus size={16} /> Nieuwe source
      </button>
    );
  }

  return (
    <form onSubmit={submit} className="mb-8 p-6 rounded-2xl bg-brand-cream border border-brand-ink/10 space-y-5 shadow-sm">
      <div className="flex justify-between items-center">
        <h3 className="font-display text-2xl text-brand-ink tracking-[-0.01em]">Nieuwe source</h3>
        <button type="button" onClick={() => setOpen(false)}
          className="text-brand-ink/40 hover:text-brand-ink/60 p-1"><X size={18} /></button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <label className="block md:col-span-2">
          <span className="block text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 mb-1.5 font-mono">Naam</span>
          <input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
            className="w-full px-3 py-2.5 rounded-lg border border-brand-ink/20 text-sm focus:outline-none focus:border-brand-blue" />
        </label>
        <label className="block">
          <span className="block text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 mb-1.5 font-mono">Kind</span>
          <select value={form.kind} onChange={e => setForm({ ...form, kind: e.target.value as SourceKind })}
            className="w-full px-3 py-2.5 rounded-lg border border-brand-ink/20 text-sm bg-brand-cream focus:outline-none focus:border-brand-blue">
            {KINDS.map(k => <option key={k} value={k}>{k}</option>)}
          </select>
        </label>
      </div>
      <label className="block">
        <span className="block text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 mb-1.5 font-mono">Feed URL</span>
        <input required value={form.url} onChange={e => setForm({ ...form, url: e.target.value })}
          placeholder="https://example.com/feed.xml"
          className="w-full px-3 py-2.5 rounded-lg border border-brand-ink/20 text-sm font-mono focus:outline-none focus:border-brand-blue" />
      </label>
      <label className="block">
        <span className="block text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 mb-1.5 font-mono">Image URL (optioneel)</span>
        <input value={form.image_url ?? ''} onChange={e => setForm({ ...form, image_url: e.target.value || null })}
          placeholder="https://..."
          className="w-full px-3 py-2.5 rounded-lg border border-brand-ink/20 text-sm font-mono focus:outline-none focus:border-brand-blue" />
      </label>
      <label className="block">
        <span className="block text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 mb-2 font-mono">Topics</span>
        <TopicChips all={topics} selected={form.topic_slugs} onToggle={toggleSlug} />
      </label>
      <div className="grid grid-cols-3 gap-4">
        <label className="block">
          <span className="block text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 mb-1.5 font-mono">Weight (1-10)</span>
          <input type="number" min={1} max={10} value={form.weight}
            onChange={e => setForm({ ...form, weight: Number(e.target.value) })}
            className="w-full px-3 py-2.5 rounded-lg border border-brand-ink/20 text-sm focus:outline-none focus:border-brand-blue" />
        </label>
        <label className="block">
          <span className="block text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 mb-1.5 font-mono">Max per rail</span>
          <input type="number" min={1} placeholder="geen cap" value={form.max_per_rail ?? ''}
            onChange={e => setForm({ ...form, max_per_rail: e.target.value === '' ? null : Number(e.target.value) })}
            className="w-full px-3 py-2.5 rounded-lg border border-brand-ink/20 text-sm focus:outline-none focus:border-brand-blue" />
        </label>
        <label className="block">
          <span className="block text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 mb-1.5 font-mono">Poll (min)</span>
          <input type="number" min={5} value={form.poll_interval_min}
            onChange={e => setForm({ ...form, poll_interval_min: Number(e.target.value) })}
            className="w-full px-3 py-2.5 rounded-lg border border-brand-ink/20 text-sm focus:outline-none focus:border-brand-blue" />
        </label>
      </div>
      {error && <div className="text-red-600 text-sm bg-red-50 px-3 py-2 rounded-lg">{error}</div>}
      <div className="flex justify-end gap-2 pt-2">
        <button type="button" onClick={() => setOpen(false)}
          className="px-4 py-2.5 rounded-xl text-brand-ink/60 hover:bg-brand-surface text-sm">Annuleren</button>
        <button type="submit" disabled={busy}
          className="px-5 py-2.5 rounded-xl bg-brand-blue text-brand-cream text-sm flex items-center gap-2 hover:opacity-90 disabled:opacity-50 transition">
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />} Aanmaken
        </button>
      </div>
    </form>
  );
};


const QueuePanel = ({ onClose }: { onClose: () => void }) => {
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => fetchAdminQueue()
      .then(d => { if (!cancelled) setItems(d); })
      .catch(e => { if (!cancelled) setError(String(e)); });
    load();
    const t = setInterval(load, 5000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  return (
    <div className="fixed inset-0 z-50 bg-brand-ink/40 backdrop-blur-sm flex items-start justify-center pt-20 px-6"
         onClick={onClose}>
      <div className="bg-brand-cream rounded-2xl shadow-xl border border-brand-ink/10 max-w-2xl w-full max-h-[70vh] overflow-hidden flex flex-col"
           onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center px-6 py-4 border-b border-brand-ink/10">
          <h3 className="font-display text-2xl text-brand-ink tracking-[-0.01em]">Transcribe queue</h3>
          <button onClick={onClose} className="text-brand-ink/40 hover:text-brand-ink/60 p-1"><X size={18} /></button>
        </div>
        <div className="overflow-y-auto p-2">
          {error && <div className="text-red-600 text-sm m-4">{error}</div>}
          {items === null ? (
            <div className="text-brand-ink/40 italic p-6">Loading…</div>
          ) : items.length === 0 ? (
            <div className="text-brand-ink/40 italic p-6 text-center">Queue is leeg.</div>
          ) : (
            <ul className="divide-y divide-brand-ink/5">
              {items.map(it => (
                <li key={it.id} className="px-4 py-3 flex items-center gap-3">
                  <div className="w-8 text-center font-mono text-xs">
                    {it.processing_status === 'transcribing'
                      ? <Loader2 size={14} className="animate-spin text-blue-600 mx-auto" />
                      : <span className="text-brand-ink/50">#{it.queue_position}</span>}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-brand-ink truncate">{it.title}</div>
                    <div className="text-[11px] text-brand-ink/40 font-mono uppercase tracking-[0.1em]">
                      {it.source_name} · {it.format}
                    </div>
                  </div>
                  <span className={`text-[10px] font-mono uppercase tracking-[0.1em] px-2 py-0.5 rounded-full ${
                    it.processing_status === 'transcribing'
                      ? 'bg-blue-50 text-blue-700'
                      : 'bg-brand-surface text-brand-ink/50'
                  }`}>{it.processing_status}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="px-6 py-3 text-[11px] text-brand-ink/40 border-t border-brand-ink/5 font-mono">
          Auto-refresh elke 5s.
        </div>
      </div>
    </div>
  );
};


export const AdminPage = ({ onBack }: { onBack: () => void }) => {
  const [sources, setSources] = useState<AdminSource[] | null>(null);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [showQueue, setShowQueue] = useState(false);
  const [refreshingAll, setRefreshingAll] = useState(false);

  const reload = () => {
    fetchAdminSources().then(setSources).catch(e => setError(String(e)));
  };

  const refreshAll = async () => {
    if (refreshingAll) return;
    if (!confirm('Refresh alle actieve sources? Dit kan even duren.')) return;
    setRefreshingAll(true);
    setError(null);
    try {
      const r = await refreshAllAdminSources();
      setToast(`${r.sources} sources gecheckt — ${r.inserted} nieuwe items` +
        (r.errors > 0 ? ` (${r.errors} errors)` : ''));
      reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setRefreshingAll(false);
    }
  };

  useEffect(() => {
    reload();
    fetchTopics().then(setTopics).catch(() => {});
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  return (
    <div className="max-w-6xl mx-auto pt-2">
      {showQueue && <QueuePanel onClose={() => setShowQueue(false)} />}

      <button onClick={onBack}
        className="mb-8 font-mono text-[11px] uppercase tracking-[0.18em] text-brand-ink/50 hover:text-brand-accent flex items-center gap-2">
        <ArrowLeft size={14} /> Terug naar feed
      </button>

      <div className="flex items-end justify-between mb-10 flex-wrap gap-4">
        <h1 className="font-display text-5xl md:text-6xl text-brand-ink font-medium tracking-[-0.04em]">Sources</h1>
        <div className="flex items-center gap-2">
          <button onClick={refreshAll} disabled={refreshingAll}
            className="px-4 py-2.5 rounded-xl bg-brand-surface hover:bg-brand-surface-low text-brand-ink text-sm flex items-center gap-2 transition disabled:opacity-50">
            {refreshingAll
              ? <Loader2 size={16} className="animate-spin" />
              : <RefreshCw size={16} />}
            Refresh alle
          </button>
          <button onClick={() => setShowQueue(true)}
            className="px-4 py-2.5 rounded-xl bg-brand-surface hover:bg-brand-surface-low text-brand-ink text-sm flex items-center gap-2 transition">
            <ListOrdered size={16} /> Toon queue
          </button>
        </div>
      </div>

      <div className="mb-6">
        <NewSourceForm topics={topics}
          onCreated={(s) => setSources(prev => [s, ...(prev ?? [])])} />
      </div>

      {toast && (
        <div className="mb-4 px-4 py-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm">
          {toast}
        </div>
      )}
      {error && <div className="text-red-600 text-sm mb-4">Fout: {error}</div>}

      {sources === null ? (
        <div className="text-brand-ink/40 italic">Loading…</div>
      ) : (
        <>
          {/* Mobile: card per source */}
          <div className="md:hidden space-y-3">
            {sources.map(s => (
              <SourceCard key={s.id} src={s} topics={topics}
                onSaved={(u) => setSources(prev => (prev ?? []).map(p => p.id === u.id ? u : p))}
                onDeleted={(id) => setSources(prev => (prev ?? []).filter(p => p.id !== id))}
                onRefreshed={(_id, msg) => setToast(msg)} />
            ))}
          </div>

          {/* Desktop: tabel */}
          <div className="hidden md:block bg-brand-cream rounded-2xl border border-brand-ink/10 overflow-hidden shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-brand-surface-low border-b border-brand-ink/10">
                  <tr className="text-left text-[10px] font-mono uppercase tracking-[0.18em] text-brand-ink/50">
                    <th className="py-3 px-4">Naam</th>
                    <th className="py-3 pr-4">Kind</th>
                    <th className="py-3 pr-4">Topics</th>
                    <th className="py-3 pr-4 text-center">Weight</th>
                    <th className="py-3 pr-4 text-center">Cap</th>
                    <th className="py-3 pr-4 text-center">Items</th>
                    <th className="py-3 pr-4">Status</th>
                    <th className="py-3 pr-4 text-right">Acties</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.map(s => (
                    <SourceRow key={s.id} src={s} topics={topics}
                      onSaved={(u) => setSources(prev => (prev ?? []).map(p => p.id === u.id ? u : p))}
                      onDeleted={(id) => setSources(prev => (prev ?? []).filter(p => p.id !== id))}
                      onRefreshed={(_id, msg) => setToast(msg)} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
};
