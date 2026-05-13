import React, { useEffect, useRef, useState } from 'react';
import { ArrowLeft, Plus, Pencil, Check, X, Trash2, Loader2, RefreshCw, ListOrdered, ChevronUp, ChevronDown, Mic, PlayCircle, Sparkles, BookOpen, Archive } from 'lucide-react';
import {
  AdminSource, AdminSourceUpdate, AdminSourceCreate, SourceKind,
  fetchAdminSources, updateAdminSource, createAdminSource, deleteAdminSource,
  refreshAdminSource, refreshAllAdminSources, fetchAdminQueue, QueueItem,
  fetchTopics, Topic, ApiError, DigestModel, ModelAction,
  AdminTopic, fetchAdminTopics, updateTopicOrder, deleteTopic,
  CronResult, cronTranscribePodcasts, cronTranscribeVideos, cronSummarizeArticles, cronDigestTopics,
  removeFromQueue, restartQueue, fetchDigestStatus, DigestStatus,
  bulkArchive, BulkArchiveResponse, AdminStats, fetchAdminStats,
} from './api';
import { useSettings } from './settings';

const MODEL_LABELS: Record<DigestModel, string> = { qwen: 'Qwen (lokaal)', sonnet: 'Sonnet', opus: 'Opus' };
const ACTION_LABELS: Record<ModelAction, string> = {
  expand: 'Verdiep deze les',
  distill: 'Meer lessen destilleren',
  digest: 'Digest genereren',
  ask: 'Vraag beantwoorden',
};

const ModelDefaultsPanel = () => {
  const { settings, save } = useSettings();
  const [draft, setDraft] = useState(settings.model_defaults);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => { setDraft(settings.model_defaults); }, [settings]);

  const dirty = (['expand','distill','digest','ask'] as ModelAction[]).some(a => draft[a] !== settings.model_defaults[a]);

  const onSave = async () => {
    setBusy(true); setErr(null);
    try {
      await save({ model_defaults: draft });
      setSavedAt(Date.now());
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mb-10 bg-brand-cream rounded-2xl border border-brand-ink/10 p-6 shadow-sm">
      <h2 className="font-display text-2xl text-brand-ink tracking-[-0.01em] mb-1">Model-defaults</h2>
      <p className="text-[13px] text-brand-ink/60 mb-5">Welk model wordt gebruikt als je nergens een override hebt ingesteld.</p>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {(['expand','distill','digest','ask'] as ModelAction[]).map(action => (
          <label key={action} className="flex flex-col gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/50">{ACTION_LABELS[action]}</span>
            <select value={draft[action]} disabled={busy}
              onChange={e => setDraft(d => ({ ...d, [action]: e.target.value as DigestModel }))}
              className="px-3 py-2 rounded-xl bg-brand-surface border border-brand-ink/10 text-sm text-brand-ink disabled:opacity-50">
              {(['qwen','sonnet','opus'] as DigestModel[]).map(m => (
                <option key={m} value={m}>{MODEL_LABELS[m]}</option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <div className="mt-5 flex items-center gap-3">
        <button onClick={onSave} disabled={busy || !dirty}
          className="px-4 py-2 rounded-xl bg-brand-accent text-brand-cream text-sm flex items-center gap-2 disabled:opacity-50 hover:opacity-90 transition">
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
          Opslaan
        </button>
        {savedAt && !dirty && <span className="text-[11px] font-mono uppercase tracking-[0.15em] text-emerald-700">Opgeslagen</span>}
        {err && <span className="text-[12px] text-rose-600">{err}</span>}
      </div>
    </section>
  );
};

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


type CronJob = 'podcasts' | 'videos' | 'articles' | 'digest';

const CronPanel = () => {
  const { getDefault } = useSettings();
  const [busy, setBusy] = useState<CronJob | null>(null);
  const [last, setLast] = useState<{ job: CronJob; result: CronResult } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [digestStatus, setDigestStatus] = useState<DigestStatus | null>(null);
  const digestPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Poll bij mount zodat de knop altijd de huidige status reflecteert,
    // ook na een refresh terwijl er nog digests draaien.
    startDigestPolling();
    return () => { if (digestPollRef.current) clearInterval(digestPollRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startDigestPolling = () => {
    if (digestPollRef.current) clearInterval(digestPollRef.current);
    const tick = async () => {
      try {
        const s = await fetchDigestStatus('daily');
        setDigestStatus(s);
        if (s.in_progress === 0 && digestPollRef.current) {
          clearInterval(digestPollRef.current);
          digestPollRef.current = null;
        }
      } catch { /* swallow */ }
    };
    tick();
    digestPollRef.current = setInterval(tick, 4000);
  };

  const run = async (job: CronJob, fn: () => Promise<CronResult>) => {
    if (busy) return;
    setBusy(job); setErr(null);
    try {
      const result = await fn();
      setLast({ job, result });
      if (job === 'digest') startDigestPolling();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(null);
    }
  };

  const buttons: { id: CronJob; label: string; icon: React.ComponentType<{ size?: number }>;
                   action: () => Promise<CronResult>; sub: string }[] = [
    { id: 'podcasts', label: 'Podcasts (24u)', icon: Mic,
      action: () => cronTranscribePodcasts(24),
      sub: 'transcribeer alle podcasts ≥ weight 5' },
    { id: 'videos', label: 'Videos (24u)', icon: PlayCircle,
      action: () => cronTranscribeVideos(24),
      sub: 'transcribeer alle YouTube ≥ weight 5' },
    { id: 'articles', label: 'Artikelen (24u)', icon: Sparkles,
      action: () => cronSummarizeArticles(24),
      sub: 'samenvatting voor articles ≥ weight 5' },
    { id: 'digest', label: 'Topic-digests', icon: BookOpen,
      action: () => cronDigestTopics('daily', getDefault('digest')),
      sub: digestStatus && digestStatus.in_progress > 0
        ? `bezig — ${digestStatus.in_progress} te gaan · ${digestStatus.done} klaar`
        : `genereer dagelijkse digest per topic · ${getDefault('digest')}` },
  ];

  const digestRunning = (digestStatus?.in_progress ?? 0) > 0;

  const summary = (job: CronJob, r: CronResult): string => {
    if (job === 'podcasts' || job === 'videos') return `${r.queued} in queue gezet`;
    if (job === 'articles') return `${r.articles_kicked} samenvattingen gestart`;
    if (job === 'digest') return `${r.digests_started} digests gestart`;
    return JSON.stringify(r);
  };

  return (
    <section className="mb-10 bg-brand-cream rounded-2xl border border-brand-ink/10 p-6 shadow-sm">
      <h2 className="font-display text-2xl text-brand-ink tracking-[-0.01em] mb-1">Nachtelijke taken</h2>
      <p className="text-[13px] text-brand-ink/60 mb-5">Handmatig triggeren — anders draait dit allemaal automatisch in de nightly cron.</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {buttons.map(b => {
          const isBusy = busy === b.id;
          const isDigestActive = b.id === 'digest' && digestRunning;
          const disabled = !!busy || isDigestActive;
          const Icon = b.icon;
          const showSpinner = isBusy || isDigestActive;
          return (
            <button key={b.id} onClick={() => run(b.id, b.action)} disabled={disabled}
              className="flex flex-col items-start gap-2 p-4 rounded-xl bg-brand-surface hover:bg-brand-accent hover:text-brand-cream text-brand-ink/80 transition disabled:opacity-50 disabled:cursor-not-allowed text-left">
              <div className="flex items-center gap-2">
                {showSpinner ? <Loader2 size={16} className="animate-spin" /> : <Icon size={16} />}
                <span className="font-mono text-[11px] uppercase tracking-[0.18em] font-medium">
                  {b.label}{isDigestActive ? ' · bezig' : ''}
                </span>
              </div>
              <span className="font-mono text-[10px] uppercase tracking-[0.16em] opacity-60">{b.sub}</span>
            </button>
          );
        })}
      </div>
      {last && (
        <div className="mt-4 px-4 py-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm font-mono">
          {buttons.find(b => b.id === last.job)?.label}: {summary(last.job, last.result)}
        </div>
      )}
      {digestStatus && (digestStatus.in_progress > 0 || (last?.job === 'digest')) && (
        <div className="mt-3 px-4 py-3 rounded-xl bg-brand-surface border border-brand-ink/10 text-sm font-mono flex items-center gap-3">
          {digestStatus.in_progress > 0 && <Loader2 size={14} className="animate-spin text-brand-accent" />}
          <span className="text-brand-ink/70">
            {digestStatus.in_progress > 0
              ? `${digestStatus.in_progress} bezig · ${digestStatus.done} klaar · ${digestStatus.failed} mislukt`
              : `Klaar — ${digestStatus.done} succesvol${digestStatus.failed ? `, ${digestStatus.failed} mislukt` : ''}`}
          </span>
        </div>
      )}
      {err && <div className="mt-4 text-rose-600 text-sm">{err}</div>}
    </section>
  );
};

const TopicsPanel = () => {
  const [topics, setTopics] = useState<AdminTopic[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [reassignTo, setReassignTo] = useState<string>('');

  const load = () => fetchAdminTopics().then(setTopics).catch(e => setErr(String(e)));
  useEffect(() => { load(); }, []);

  const move = async (slug: string, dir: -1 | 1) => {
    if (!topics || busy) return;
    const idx = topics.findIndex(t => t.slug === slug);
    const j = idx + dir;
    if (idx < 0 || j < 0 || j >= topics.length) return;
    const next = topics.slice();
    [next[idx], next[j]] = [next[j], next[idx]];
    setTopics(next);
    setBusy(true); setErr(null);
    try {
      await updateTopicOrder(next.map(t => t.slug));
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : String(e));
      load();
    } finally {
      setBusy(false);
    }
  };

  const startDelete = (slug: string) => {
    setPendingDelete(slug);
    const others = (topics ?? []).filter(t => t.slug !== slug);
    setReassignTo(others[0]?.slug ?? '');
    setErr(null);
  };

  const confirmDelete = async () => {
    if (!pendingDelete || !reassignTo || busy) return;
    setBusy(true); setErr(null);
    try {
      await deleteTopic(pendingDelete, reassignTo);
      setPendingDelete(null);
      await load();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mb-10 bg-brand-cream rounded-2xl border border-brand-ink/10 p-6 shadow-sm">
      <h2 className="font-display text-2xl text-brand-ink tracking-[-0.01em] mb-1">Topics</h2>
      <p className="text-[13px] text-brand-ink/60 mb-5">Volgorde aanpassen met de pijlen, of een topic verwijderen — alle gekoppelde sources en items verhuizen dan naar het topic dat je kiest.</p>

      {topics === null ? (
        <div className="text-brand-ink/40 italic text-sm py-4">Laden…</div>
      ) : (
        <ul className="divide-y divide-brand-ink/5">
          {topics.map((t, i) => {
            const isDeleting = pendingDelete === t.slug;
            return (
              <li key={t.slug} className="py-3">
                <div className="flex items-center gap-3 flex-wrap">
                  <div className="flex flex-col">
                    <button onClick={() => move(t.slug, -1)} disabled={busy || i === 0}
                      className="w-6 h-5 flex items-center justify-center text-brand-ink/40 hover:text-brand-accent disabled:opacity-25 disabled:cursor-not-allowed">
                      <ChevronUp size={14} />
                    </button>
                    <button onClick={() => move(t.slug, 1)} disabled={busy || i === topics.length - 1}
                      className="w-6 h-5 flex items-center justify-center text-brand-ink/40 hover:text-brand-accent disabled:opacity-25 disabled:cursor-not-allowed">
                      <ChevronDown size={14} />
                    </button>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-serif font-semibold text-[15px] text-brand-ink">{t.name}</div>
                    <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/45 mt-0.5">
                      {t.slug} · {t.source_count} sources · {t.item_count} items
                    </div>
                  </div>
                  {!isDeleting && (
                    <button onClick={() => startDelete(t.slug)} disabled={busy}
                      title="Verwijder topic"
                      className="px-2 py-1.5 rounded-lg text-brand-ink/40 hover:text-rose-600 hover:bg-rose-50 transition disabled:opacity-50">
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
                {isDeleting && (
                  <div className="mt-3 ml-9 p-4 rounded-xl bg-rose-50/60 border border-rose-200/60">
                    <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-rose-700 mb-2">
                      Verplaats {t.source_count} sources + {t.item_count} items naar:
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <select value={reassignTo} onChange={e => setReassignTo(e.target.value)}
                        className="flex-1 min-w-[160px] px-3 py-2 rounded-lg bg-white border border-brand-ink/10 text-sm">
                        {topics.filter(o => o.slug !== t.slug).map(o => (
                          <option key={o.slug} value={o.slug}>{o.name}</option>
                        ))}
                      </select>
                      <button onClick={confirmDelete} disabled={busy || !reassignTo}
                        className="px-3 py-2 rounded-lg bg-rose-600 text-white text-sm flex items-center gap-1.5 disabled:opacity-50 hover:bg-rose-700">
                        {busy ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                        Verwijder
                      </button>
                      <button onClick={() => setPendingDelete(null)} disabled={busy}
                        className="px-3 py-2 rounded-lg text-brand-ink/60 hover:bg-brand-surface text-sm">
                        Annuleer
                      </button>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {err && <div className="mt-3 text-rose-600 text-sm">{err}</div>}
    </section>
  );
};

const FORMATS: { key: string; label: string }[] = [
  { key: 'article', label: 'Artikelen' },
  { key: 'podcast', label: 'Podcasts' },
  { key: 'video', label: 'Videos' },
  { key: 'short', label: 'Shorts' },
];

const BulkArchivePanel = ({ topics }: { topics: Topic[] }) => {
  const [selectedTopics, setSelectedTopics] = useState<string[]>([]);
  const [olderThanDays, setOlderThanDays] = useState<number>(30);
  const [weightMax, setWeightMax] = useState<number>(5);
  const [selectedFormats, setSelectedFormats] = useState<string[]>(['article']);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<BulkArchiveResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const toggleTopic = (slug: string) => {
    setSelectedTopics(prev =>
      prev.includes(slug) ? prev.filter(s => s !== slug) : [...prev, slug]
    );
  };

  const toggleAllTopics = () => {
    if (selectedTopics.length === topics.length) {
      setSelectedTopics([]);
    } else {
      setSelectedTopics(topics.map(t => t.slug));
    }
  };

  const toggleFormat = (key: string) => {
    setSelectedFormats(prev =>
      prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]
    );
  };

  const toggleAllFormats = () => {
    if (selectedFormats.length === FORMATS.length) {
      setSelectedFormats([]);
    } else {
      setSelectedFormats(FORMATS.map(f => f.key));
    }
  };

  const submit = async () => {
    if (selectedTopics.length === 0) {
      setErr('Selecteer minstens 1 topic');
      return;
    }
    if (selectedFormats.length === 0) {
      setErr('Selecteer minstens 1 format');
      return;
    }
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      const r = await bulkArchive({
        topic_slugs: selectedTopics,
        older_than_days: olderThanDays,
        weight_max: weightMax,
        formats: selectedFormats,
      });
      setResult(r);
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mb-10 bg-brand-cream rounded-2xl border border-brand-ink/10 p-6 shadow-sm">
      <h2 className="font-display text-2xl text-brand-ink tracking-[-0.01em] mb-1">Bulk archiveren</h2>
      <p className="text-[13px] text-brand-ink/60 mb-5">Archiveer oude items automatisch op basis van filters.</p>

      <div className="space-y-5">
        {/* Topics */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 font-mono">Topics</span>
            <button onClick={toggleAllTopics} className="text-[11px] text-brand-blue hover:underline">
              {selectedTopics.length === topics.length ? 'Deselecteer alles' : 'Selecteer alles'}
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {topics.map(t => {
              const on = selectedTopics.includes(t.slug);
              return (
                <button key={t.slug} onClick={() => toggleTopic(t.slug)}
                  className={`px-2.5 py-1 rounded-full text-[11px] font-mono uppercase tracking-[0.1em] transition ${
                    on ? 'bg-brand-blue text-brand-cream' : 'bg-brand-surface text-brand-ink/50 hover:bg-brand-surface-low'
                  }`}>
                  {t.slug}
                </button>
              );
            })}
          </div>
        </div>

        {/* Formats */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 font-mono">Format</span>
            <button onClick={toggleAllFormats} className="text-[11px] text-brand-blue hover:underline">
              {selectedFormats.length === FORMATS.length ? 'Deselecteer alles' : 'Selecteer alles'}
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {FORMATS.map(f => {
              const on = selectedFormats.includes(f.key);
              return (
                <button key={f.key} onClick={() => toggleFormat(f.key)}
                  className={`px-2.5 py-1 rounded-full text-[11px] font-mono uppercase tracking-[0.1em] transition ${
                    on ? 'bg-brand-blue text-brand-cream' : 'bg-brand-surface text-brand-ink/50 hover:bg-brand-surface-low'
                  }`}>
                  {f.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Date and Weight */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="block">
            <span className="block text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 mb-1.5 font-mono">Ouder dan (dagen)</span>
            <input type="number" min={1} max={365} value={olderThanDays}
              onChange={e => setOlderThanDays(Number(e.target.value))}
              className="w-full px-3 py-2 rounded-lg border border-brand-ink/20 text-sm bg-brand-cream" />
          </label>
          <label className="block">
            <span className="block text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 mb-1.5 font-mono">Max source weight</span>
            <input type="number" min={1} max={10} value={weightMax}
              onChange={e => setWeightMax(Number(e.target.value))}
              className="w-full px-3 py-2 rounded-lg border border-brand-ink/20 text-sm bg-brand-cream" />
          </label>
        </div>

        {/* Submit */}
        <div className="pt-2">
          <button onClick={submit} disabled={busy}
            className="px-5 py-2.5 rounded-xl bg-rose-600 text-brand-cream text-sm flex items-center gap-2 hover:bg-rose-700 disabled:opacity-50 transition">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Archive size={14} />}
            Archiveer {selectedTopics.length > 0 ? selectedTopics.length : ''} topic(s)
          </button>
        </div>

        {/* Result */}
        {result && (
          <div className="px-4 py-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm font-mono">
            {result.archived} items gearchiveerd
          </div>
        )}
        {err && <div className="text-rose-600 text-sm">{err}</div>}
      </div>
    </section>
  );
};

const StatsPanel = () => {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = async (showLoading = true) => {
    if (showLoading) setRefreshing(true);
    try {
      const data = await fetchAdminStats();
      setStats(data);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    load();
    const interval = setInterval(() => load(false), 60 * 60 * 1000); // 1 hour
    return () => clearInterval(interval);
  }, []);

  if (loading) return (
    <section className="mb-10 bg-brand-cream rounded-2xl border border-brand-ink/10 p-6 shadow-sm">
      <h2 className="font-display text-2xl text-brand-ink tracking-[-0.01em] mb-5">Statistieken</h2>
      <div className="text-brand-ink/50 italic">Laden...</div>
    </section>
  );

  if (error) return (
    <section className="mb-10 bg-brand-cream rounded-2xl border border-brand-ink/10 p-6 shadow-sm">
      <h2 className="font-display text-2xl text-brand-ink tracking-[-0.01em] mb-5">Statistieken</h2>
      <div className="text-rose-600 text-sm">{error}</div>
    </section>
  );

  if (!stats) return null;

  const queueTotal = stats.queue.summarize_queued + stats.queue.transcribe_queued +
                     stats.queue.summarizing + stats.queue.transcribing;

  const has24hData = Object.keys(stats.type_breakdown_24h).length > 0;

  return (
    <section className="mb-10 bg-brand-cream rounded-2xl border border-brand-ink/10 p-6 shadow-sm">
      <div className="flex items-center justify-between mb-5">
        <h2 className="font-display text-2xl text-brand-ink tracking-[-0.01em]">Statistieken</h2>
        <button
          onClick={() => load(true)}
          disabled={refreshing}
          className="px-3 py-1.5 rounded-xl bg-brand-surface hover:bg-brand-surface-low text-brand-ink text-sm flex items-center gap-2 transition disabled:opacity-50"
        >
          {refreshing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          Ververs
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {/* Total items */}
        <div className="bg-brand-surface rounded-xl p-4">
          <div className="text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 font-mono">Totaal items</div>
          <div className="text-2xl font-display text-brand-ink">{stats.total_items.toLocaleString()}</div>
        </div>

        {/* Total sources */}
        <div className="bg-brand-surface rounded-xl p-4">
          <div className="text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 font-mono">Sources</div>
          <div className="text-2xl font-display text-brand-ink">{stats.total_sources.toLocaleString()}</div>
        </div>

        {/* Queue status */}
        <div className="bg-brand-surface rounded-xl p-4">
          <div className="text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 font-mono">In queue</div>
          <div className="text-2xl font-display text-brand-ink">{queueTotal.toLocaleString()}</div>
          <div className="text-[10px] text-brand-ink/50 mt-1 font-mono leading-tight">
            {stats.queue.summarize_queued + stats.queue.summarizing} sum · {stats.queue.transcribe_queued + stats.queue.transcribing} trans
          </div>
        </div>

        {/* Recent items */}
        <div className="bg-brand-surface rounded-xl p-4">
          <div className="text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 font-mono">Nieuw (24u / 7d)</div>
          <div className="text-2xl font-display text-brand-ink">
            {stats.recent_items.hours_24.toLocaleString()}
            <span className="text-brand-ink/40 text-lg ml-1">/ {stats.recent_items.days_7.toLocaleString()}</span>
          </div>
        </div>
      </div>

      {/* Type breakdown - Total */}
      <div className="mb-5">
        <div className="text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 font-mono mb-3">Per type (totaal)</div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(stats.type_breakdown).map(([type, count]) => (
            <span key={type} className="px-3 py-1.5 rounded-full text-xs font-mono bg-brand-surface text-brand-ink/70">
              <span className="capitalize">{type}</span>: {count.toLocaleString()}
            </span>
          ))}
        </div>
      </div>

      {/* Type breakdown - 24h */}
      {has24hData && (
        <div className="mb-5">
          <div className="text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 font-mono mb-3">Per type (laatste 24u)</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.type_breakdown_24h).map(([type, count]) => (
              <span key={type} className="px-3 py-1.5 rounded-full text-xs font-mono bg-brand-surface text-brand-ink/70">
                <span className="capitalize">{type}</span>: {count.toLocaleString()}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Status breakdown */}
      <div>
        <div className="text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 font-mono mb-3">Status verdeling</div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(stats.status_breakdown).map(([status, count]) => (
            <span key={status}
              className={`px-3 py-1.5 rounded-full text-xs font-mono ${
                status === 'ready' ? 'bg-emerald-50 text-emerald-700' :
                status === 'failed' ? 'bg-rose-50 text-rose-700' :
                status.includes('queued') ? 'bg-amber-50 text-amber-700' :
                status.includes('ing') ? 'bg-blue-50 text-blue-700' :
                'bg-brand-surface-low text-brand-ink/70'
              }`}>
              {status}: {count.toLocaleString()}
            </span>
          ))}
        </div>
      </div>

      <div className="mt-4 text-[11px] text-brand-ink/40 font-mono">
        Auto-refresh elke uur
      </div>
    </section>
  );
};

const QueuePanel = ({ onClose }: { onClose: () => void }) => {
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [restarting, setRestarting] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const load = async () => {
    try { setItems(await fetchAdminQueue()); }
    catch (e) { setError(String(e)); }
  };

  useEffect(() => {
    let cancelled = false;
    const tick = () => fetchAdminQueue()
      .then(d => { if (!cancelled) setItems(d); })
      .catch(e => { if (!cancelled) setError(String(e)); });
    tick();
    const t = setInterval(tick, 5000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  const remove = async (id: string) => {
    setBusyId(id); setError(null);
    try { await removeFromQueue(id); await load(); }
    catch (e) { setError(e instanceof ApiError ? e.detail : String(e)); }
    finally { setBusyId(null); }
  };

  const restart = async () => {
    if (restarting) return;
    if (!confirm('Stuck items resetten en queue herstarten?')) return;
    setRestarting(true); setError(null); setToast(null);
    try {
      const r = await restartQueue();
      const stuck = typeof r.stuck_reset === 'number' ? r.stuck_reset : 0;
      setToast(`${stuck} stuck-items gereset · queue ${r.queue_started ? 'gekickt' : 'niet gestart'}`);
      setError(null);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setRestarting(false);
    }
  };

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  return (
    <div className="fixed inset-0 z-50 bg-brand-ink/40 backdrop-blur-sm flex items-start justify-center pt-20 px-6"
         onClick={onClose}>
      <div className="bg-brand-cream rounded-2xl shadow-xl border border-brand-ink/10 max-w-2xl w-full max-h-[70vh] overflow-hidden flex flex-col"
           onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center px-6 py-4 border-b border-brand-ink/10 gap-3">
          <h3 className="font-display text-2xl text-brand-ink tracking-[-0.01em]">Transcribe queue</h3>
          <div className="flex items-center gap-2">
            <button onClick={restart} disabled={restarting}
              className="px-3 py-1.5 rounded-full bg-brand-surface hover:bg-brand-accent hover:text-brand-cream font-mono text-[10px] uppercase tracking-[0.18em] inline-flex items-center gap-1.5 disabled:opacity-50">
              {restarting ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
              Herstart queue
            </button>
            <button onClick={onClose} className="text-brand-ink/40 hover:text-brand-ink/60 p-1"><X size={18} /></button>
          </div>
        </div>
        {toast && <div className="px-6 py-2 bg-emerald-50 border-b border-emerald-200 text-emerald-800 text-[12px] font-mono">{toast}</div>}
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
                    {it.processing_status === 'transcribing' || it.processing_status === 'summarizing'
                      ? <Loader2 size={14} className={`animate-spin mx-auto ${it.processing_status === 'transcribing' ? 'text-blue-600' : 'text-amber-600'}`} />
                      : <span className="text-brand-ink/50">#{it.queue_position}</span>}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-brand-ink truncate">{it.title}</div>
                    <div className="text-[11px] text-brand-ink/40 font-mono uppercase tracking-[0.1em]">
                      {it.source_name} · {it.format}
                    </div>
                  </div>
                  <span className={`text-[10px] font-mono uppercase tracking-[0.1em] px-2 py-0.5 rounded-full ${
                    it.processing_status === 'transcribing' ? 'bg-blue-50 text-blue-700' :
                    it.processing_status === 'summarizing' ? 'bg-amber-50 text-amber-700' :
                    'bg-brand-surface text-brand-ink/50'
                  }`}>{it.processing_status}</span>
                  <button onClick={() => remove(it.id)} disabled={busyId === it.id}
                    title="Uit queue halen"
                    className="p-1.5 rounded text-brand-ink/40 hover:text-rose-600 hover:bg-rose-50 disabled:opacity-30">
                    {busyId === it.id ? <Loader2 size={13} className="animate-spin" /> : <X size={13} />}
                  </button>
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
        (r.thumbnails_scheduled ? ` · ${r.thumbnails_scheduled} thumbnails op de achtergrond` : '') +
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

      <ModelDefaultsPanel />

      <StatsPanel />

      <CronPanel />

      <TopicsPanel />

      <BulkArchivePanel topics={topics} />

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
// Force rebuild Wed May 13 10:28:54 UTC 2026
