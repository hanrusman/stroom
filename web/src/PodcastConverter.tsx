import React, { useEffect, useState } from 'react';
import { ArrowLeft, Download, Loader2, Mic, RefreshCw, Trash2 } from 'lucide-react';
import { fetchPodcastModels, fetchPodcastTests, generatePodcast, deletePodcastTest,
  PodcastCatalog, PodcastModel, PodcastTest } from './api';

const SAMPLE = `Welcome to Stroom. Today, we're trying something simple: turning a piece of writing into a podcast you actually enjoy listening to.

A good narrator knows when to pause. When to move a little faster. And when to let an idea breathe. The words matter, of course, but so does the space between them.

Here's the question: can a small, locally hosted speech model make this sound natural? We'll compare the same text across three models. Listen for clear pronunciation, a steady voice, and the rhythm of an ordinary conversation.`;
const LABELS = { queued: 'In de wachtrij', rendering: 'Audio wordt gemaakt', ready: 'Klaar', failed: 'Niet gelukt' };
const DRAFT_KEY = 'stroom-podcast-draft';
const POLL_ERROR = 'De status kon niet worden opgehaald. De generatie kan nog doorlopen.';
const active = (job: PodcastTest) => job.status === 'queued' || job.status === 'rendering';

export function PodcastConverter({ onBack }: { onBack: () => void }) {
  const [text, setText] = useState(() => { try { return sessionStorage.getItem(DRAFT_KEY) ?? ''; } catch { return ''; } });
  const [model, setModel] = useState<PodcastModel>('omnivoice');
  const [catalog, setCatalog] = useState<PodcastCatalog | null>(null);
  const [jobs, setJobs] = useState<PodcastTest[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const max = catalog?.max_characters ?? 4000;
  const selected = catalog?.models.find(m => m.id === model);
  const pending = jobs.some(active);

  useEffect(() => { try { sessionStorage.setItem(DRAFT_KEY, text); } catch { /* private mode */ } }, [text]);

  useEffect(() => {
    let alive = true;
    Promise.all([fetchPodcastModels(), fetchPodcastTests()]).then(([choices, history]) => {
      if (!alive) return;
      setCatalog(choices); setJobs(history);
      setModel(choices.models.find(m => m.available)?.id ?? 'omnivoice');
    }).catch(e => { if (alive) setError(String(e.message ?? e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!pending) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const history = await fetchPodcastTests();
        // A later successful poll clears only its own earlier failure.
        if (alive) { setJobs(history); setError(e => e === POLL_ERROR ? null : e); }
      } catch {
        if (alive) setError(POLL_ERROR);
      } finally {
        if (alive) timer = setTimeout(poll, 5000);
      }
    };
    timer = setTimeout(poll, 5000);
    return () => { alive = false; clearTimeout(timer); };
  }, [pending]);

  const refresh = async () => {
    setLoading(true); setError(null);
    try {
      const [choices, history] = await Promise.all([fetchPodcastModels(), fetchPodcastTests()]);
      setCatalog(choices); setJobs(history);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  };

  const generate = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const job = await generatePodcast(text.trim(), model);
      setJobs(previous => [job, ...previous.filter(j => j.id !== job.id)]);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const remove = async (id: string) => {
    setDeleting(id); setError(null);
    try { await deletePodcastTest(id); setJobs(previous => previous.filter(j => j.id !== id)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setDeleting(null); setConfirmDelete(null); }
  };

  return <div className="max-w-3xl mx-auto text-brand-ink">
    <button onClick={onBack} className="inline-flex items-center gap-2 min-h-11 mb-6 text-sm text-brand-ink/70 hover:text-brand-accent">
      <ArrowLeft size={16} /> Terug naar Stroom
    </button>
    <div className="flex items-center gap-3 mb-3"><Mic className="text-brand-accent" size={26} />
      <h1 className="font-display text-3xl md:text-4xl">Podcast uit tekst</h1>
    </div>
    <p className="text-brand-ink/70 leading-relaxed mb-7">Plak een Engelse tekst, kies een model en luister. Gebruik dezelfde tekst om de modellen te vergelijken.</p>

    <form onSubmit={generate} className="rounded-2xl border border-brand-ink/10 bg-brand-surface/40 p-5 md:p-7 space-y-5">
      <div>
        <div className="flex items-center justify-between gap-3 mb-2">
          <label htmlFor="podcast-text" className="font-medium">Je tekst</label>
          <button type="button" onClick={() => setText(SAMPLE)} disabled={!!text.trim()}
            className="min-h-11 text-sm text-brand-accent disabled:opacity-40">Voorbeeldtekst</button>
        </div>
        <textarea id="podcast-text" value={text} onChange={e => setText(e.target.value)} rows={10}
          maxLength={max} aria-describedby="podcast-text-help"
          placeholder="Welcome to today's episode…"
          className="w-full resize-y rounded-xl border border-brand-ink/20 bg-brand-cream p-4 text-base leading-relaxed focus:outline-none focus:ring-2 focus:ring-brand-accent" />
        <div id="podcast-text-help" className="mt-2 flex justify-between gap-3 text-xs text-brand-ink/60">
          <span>De tekst wordt uitgesproken zoals je hem invoert.</span><span className="shrink-0">{text.length} / {max}</span>
        </div>
      </div>
      <div className="flex flex-col sm:flex-row sm:items-end gap-4">
        <label className="flex-1 space-y-2" htmlFor="podcast-model">
          <span className="block font-medium">Spraakmodel</span>
          <select id="podcast-model" value={model} onChange={e => setModel(e.target.value as PodcastModel)}
            disabled={!catalog || busy} className="w-full min-h-12 rounded-xl border border-brand-ink/20 bg-brand-cream px-3 focus:ring-2 focus:ring-brand-accent">
            {(catalog?.models ?? [{ id: 'omnivoice', name: 'Modellen laden…', available: false }]).map(m =>
              <option key={m.id} value={m.id}>{m.name}{!m.available && catalog ? ' — niet beschikbaar' : ''}</option>)}
          </select>
        </label>
        <button type="submit" disabled={busy || !selected?.available || !text.trim() || text.length > max}
          className="min-h-12 px-6 rounded-xl bg-brand-accent text-brand-cream font-medium flex items-center justify-center gap-2 disabled:opacity-40 hover:opacity-90 focus-visible:ring-2 focus-visible:ring-brand-accent focus-visible:ring-offset-2">
          {busy ? <Loader2 size={18} className="animate-spin" /> : <Mic size={18} />}
          {busy ? 'Toevoegen…' : 'Genereer podcast'}
        </button>
      </div>
      {selected?.reason && <p className="text-sm text-brand-ink/70" role="status">{selected.reason}</p>}
      <p className="text-xs leading-relaxed text-brand-ink/60">Eén test tegelijk. Bij drukte wacht je podcast tot er capaciteit is. Je kunt deze pagina sluiten en later terugkomen.</p>
    </form>
    {error && <p role="alert" className="mt-4 text-rose-700 dark:text-rose-300">{error}</p>}

    <div className="flex items-center justify-between mt-10 mb-4">
      <h2 className="font-display text-2xl">Je tests</h2>
      <button onClick={refresh} disabled={loading} className="min-h-11 px-3 flex items-center gap-2 text-sm text-brand-ink/70">
        <RefreshCw size={15} className={loading ? 'animate-spin' : ''} /> Vernieuwen
      </button>
    </div>
    {!loading && !jobs.length && <p className="text-brand-ink/60 py-5">Je eerste podcast verschijnt hier. Daarna kun je dezelfde tekst met een ander model proberen.</p>}
    <div className="space-y-4">
      {jobs.map(job => <article key={job.id} className="rounded-2xl border border-brand-ink/10 p-5 bg-brand-surface/30">
        <div className="flex flex-wrap justify-between items-center gap-2">
          <h3 className="font-medium">{job.model_name}</h3>
          <span role="status" className="text-sm text-brand-ink/70 inline-flex items-center gap-2">
            {active(job) && <Loader2 size={14} className="animate-spin" />}{LABELS[job.status]}
          </span>
        </div>
        <p className="text-xs text-brand-ink/60 mt-1">{new Date(job.created_at).toLocaleString('nl-NL')}
          {job.elapsed_seconds != null && ` · ${Math.round(job.elapsed_seconds)} s generatietijd`}</p>
        {job.message && <p className="mt-3 text-sm" role={job.status === 'failed' ? 'alert' : undefined}>{job.message}</p>}
        {job.audio_url && <>
          <audio controls preload="none" src={job.audio_url} aria-label={`Podcast met ${job.model_name}`} className="w-full mt-4" />
          <a href={job.audio_url} download={`stroom-${job.model}.mp3`} className="inline-flex items-center gap-2 min-h-11 text-sm text-brand-accent"><Download size={15} /> Download MP3</a>
        </>}
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-brand-ink/70">Gebruikte tekst</summary>
          <p className="whitespace-pre-wrap mt-3 leading-relaxed">{job.text}</p>
          <button onClick={() => { setText(job.text); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
            className="min-h-11 text-brand-accent">Gebruik deze tekst opnieuw</button>
        </details>
        {!active(job) && <div className="mt-2 flex flex-wrap gap-3 items-center text-sm">
          {confirmDelete === job.id ? <>
            <span>Deze test en audio verwijderen?</span>
            <button onClick={() => remove(job.id)} disabled={deleting === job.id} className="min-h-11 text-rose-700">Verwijderen</button>
            <button onClick={() => setConfirmDelete(null)} className="min-h-11">Annuleren</button>
          </> : <button onClick={() => setConfirmDelete(job.id)} className="min-h-11 text-brand-ink/60 inline-flex items-center gap-2"><Trash2 size={14} /> Verwijder test</button>}
        </div>}
      </article>)}
    </div>
  </div>;
}
