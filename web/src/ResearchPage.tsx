import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent, MouseEvent as ReactMouseEvent, ReactNode } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import {
  ArrowLeft, Check, Download, ExternalLink, FileText, Loader2, MessageSquare, NotebookPen,
  Play, RefreshCw, Send, Square, Trash2, X,
} from 'lucide-react';
import {
  askResearchRun, cancelResearchRun, createResearchRun, deleteResearchRun,
  exportResearchToObsidian, fetchResearchFunnel, fetchResearchMarkdown, fetchResearchRun,
  fetchResearchRuns, refreshResearchRun, resumeResearchRun,
} from './api';
import type {
  ResearchFinding, ResearchFunnelRow, ResearchListItem, ResearchRun, ResearchSource, ResearchStatus,
} from './api';
import { citationsToButtons, formatDateNL, monthHistogram, STAGES, stageIndex } from './researchText';

const EXAMPLES = [
  'Hoe verandert het inkopen van software, en waar kiezen organisaties voor zelf bouwen versus kopen?',
  'Wat zeggen mijn bronnen over de impact van AI-agents op werk en banen in Nederland?',
  'Hoe denken experts over digitale soevereiniteit en de afhankelijkheid van Amerikaanse big tech?',
  'Welke lessen over leiderschap en teams komen steeds terug?',
];

const STATUS_LABEL: Record<ResearchStatus, string> = {
  queued: 'In de wachtrij', planning: 'Plan maken', recall: 'Zoeken', screening: 'Screenen',
  extracting: 'Bronnen lezen', deepening: 'Verdiepen', writing: 'Schrijven', critiquing: 'Kritische review',
  revising: 'Herzien', done: 'Klaar', failed: 'Mislukt', cancelled: 'Gestopt',
};

const EVIDENCE_LABEL: Record<string, string> = {
  data: 'data', case: 'casus', expert: 'expert', prediction: 'voorspelling', anecdote: 'anekdote',
};

const isRunning = (s: ResearchStatus) => !['done', 'failed', 'cancelled'].includes(s);

const chip = (active: boolean) =>
  `rounded-full px-3 py-1 text-[12px] font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent ${
    active ? 'bg-brand-accent text-brand-cream shadow-sm' : 'bg-brand-surface hover:bg-brand-surface-low text-brand-ink/70'
  }`;

const actionBtn =
  'inline-flex items-center gap-1.5 rounded-full border border-brand-ink/10 bg-brand-surface px-3 py-1.5 text-[12px] font-medium text-brand-ink/75 hover:bg-brand-surface-low hover:text-brand-accent transition-colors disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent';

const mono = 'font-mono text-[11px] uppercase tracking-[0.18em] text-brand-ink/50';

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

// ---------------------------------------------------------------- list

export function ResearchPage({ runId, onOpenRun, onBack, onOpenItem }: {
  runId: string | null;
  onOpenRun: (id: string | null) => void;
  onBack: () => void;
  onOpenItem: (id: string) => void;
}) {
  if (runId) return <RunView id={runId} onBack={() => onOpenRun(null)} onOpenRun={onOpenRun} onOpenItem={onOpenItem} />;
  return <RunList onOpenRun={onOpenRun} onBack={onBack} />;
}

function RunList({ onOpenRun, onBack }: { onOpenRun: (id: string) => void; onBack: () => void }) {
  const [runs, setRuns] = useState<ResearchListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [showOld, setShowOld] = useState(false);

  const load = useCallback(() => {
    fetchResearchRuns().then(setRuns).catch(e => setError(errText(e)));
  }, []);
  useEffect(load, [load]);
  // Lopende dossiers: lijst elke 5 s verversen.
  useEffect(() => {
    if (!runs?.some(r => isRunning(r.status))) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [runs, load]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (question.trim().length < 10 || busy) return;
    setBusy(true);
    try {
      const { id } = await createResearchRun(question.trim());
      onOpenRun(id);
    } catch (err) {
      setError(errText(err));
      setBusy(false);
    }
  };

  const visible = (runs ?? []).filter(r => showOld || !r.superseded);
  const nOld = (runs ?? []).filter(r => r.superseded).length;

  return (
    <div className="max-w-4xl mx-auto pt-2">
      <button type="button" onClick={onBack} className={`mb-8 flex items-center gap-2 rounded hover:text-brand-accent ${mono}`}>
        <ArrowLeft size={14} /> Terug
      </button>
      <h1 className="font-display text-5xl md:text-6xl text-brand-ink font-medium tracking-[-0.04em] mb-4">Dossiers</h1>
      <p className="font-serif text-[15px] text-brand-ink/60 mb-8 max-w-2xl">
        Stel een brede vraag aan je hele archief. Stroom zoekt honderden bronnen af, laat elke relevante bron
        uitpluizen, en schrijft er een dossier over met bronverwijzingen — getoetst door een tweede model.
      </p>

      <form onSubmit={submit} className="mb-4 rounded-3xl border border-brand-ink/10 bg-brand-surface p-4 md:p-5 shadow-sm">
        <label htmlFor="research-q" className={`${mono} block mb-2`}>Onderzoeksvraag</label>
        <textarea
          id="research-q"
          value={question}
          onChange={e => setQuestion(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void submit(e); }}
          rows={3}
          maxLength={1500}
          placeholder="Bijvoorbeeld: hoe verandert het inkopen van software, en waar kiezen organisaties voor zelf bouwen?"
          className="w-full resize-y bg-transparent font-serif text-[17px] leading-relaxed text-brand-ink placeholder:text-brand-ink/35 focus:outline-none"
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <span className="text-[12px] text-brand-ink/45">Duurt meestal 5-15 minuten. Je kunt dit scherm gerust sluiten.</span>
          <button type="submit" disabled={busy || question.trim().length < 10}
            className="inline-flex items-center gap-2 rounded-full bg-brand-accent px-5 py-2 text-[13px] font-semibold text-brand-cream shadow-sm disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />} Start dossier
          </button>
        </div>
      </form>
      <div className="mb-12 flex flex-wrap gap-2">
        {EXAMPLES.map(x => (
          <button key={x} type="button" onClick={() => setQuestion(x)}
            className="rounded-full bg-brand-surface-low/60 px-3 py-1 text-left text-[12px] text-brand-ink/60 hover:text-brand-accent">
            {x}
          </button>
        ))}
      </div>

      {error && <p role="alert" className="mb-6 text-sm text-red-700">{error}</p>}
      {runs === null && !error && <Loader2 className="animate-spin text-brand-ink/40" />}
      {runs && runs.length === 0 && (
        <p className="font-serif text-brand-ink/50">Nog geen dossiers. Stel hierboven je eerste vraag.</p>
      )}
      <ul className="space-y-3">
        {visible.map(r => (
          <li key={r.id}>
            <button type="button" onClick={() => onOpenRun(r.id)}
              className="group w-full rounded-2xl border border-brand-ink/8 bg-brand-surface/70 px-5 py-4 text-left transition-colors hover:border-brand-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="font-display text-xl text-brand-ink group-hover:text-brand-accent tracking-[-0.02em]">
                    {r.title || r.question}
                  </div>
                  {r.title && <div className="mt-1 line-clamp-2 font-serif text-[14px] text-brand-ink/55">{r.question}</div>}
                </div>
                <StatusBadge status={r.status} />
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-brand-ink/45">
                <span>{formatDateNL(r.created_at)}</span>
                {r.status === 'done' && <span>{r.n_sources} bronnen</span>}
                {r.parent_id && <span>vernieuwing</span>}
                {r.superseded && <span>vervangen door nieuwere versie</span>}
                {isRunning(r.status) && <MiniProgress status={r.status} done={r.progress?.done} total={r.progress?.total} />}
                {r.status === 'failed' && r.error && <span className="text-red-700/80 line-clamp-1">{r.error}</span>}
              </div>
            </button>
          </li>
        ))}
      </ul>
      {nOld > 0 && (
        <button type="button" onClick={() => setShowOld(v => !v)} className={`mt-4 ${mono} hover:text-brand-accent`}>
          {showOld ? 'Verberg' : 'Toon'} {nOld} oudere versie{nOld === 1 ? '' : 's'}
        </button>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: ResearchStatus }) {
  const cls = status === 'done' ? 'bg-emerald-600/10 text-emerald-700 dark:text-emerald-400'
    : status === 'failed' ? 'bg-red-600/10 text-red-700'
    : status === 'cancelled' ? 'bg-brand-ink/5 text-brand-ink/50'
    : 'bg-brand-accent/10 text-brand-accent';
  return (
    <span className={`shrink-0 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ${cls}`}>
      {isRunning(status) && <Loader2 size={11} className="animate-spin" />}
      {STATUS_LABEL[status]}
    </span>
  );
}

function MiniProgress({ status, done, total }: { status: ResearchStatus; done?: number; total?: number }) {
  const i = stageIndex(status);
  return (
    <span className="inline-flex items-center gap-2">
      <span className="inline-flex gap-0.5" aria-hidden>
        {STAGES.map((s, k) => (
          <span key={s.id} className={`h-1.5 w-4 rounded-full ${k < i ? 'bg-brand-accent' : k === i ? 'bg-brand-accent/50 animate-pulse' : 'bg-brand-ink/10'}`} />
        ))}
      </span>
      {total ? <span>{done ?? 0}/{total}</span> : null}
    </span>
  );
}

// ---------------------------------------------------------------- detail

type Tab = 'dossier' | 'findings' | 'sources' | 'funnel' | 'quality';

function RunView({ id, onBack, onOpenRun, onOpenItem }: {
  id: string; onBack: () => void; onOpenRun: (id: string) => void; onOpenItem: (id: string) => void;
}) {
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('dossier');
  const [activeRef, setActiveRef] = useState<string | null>(null);
  // Escape sluit het bronpaneel (op mobiel dekt het als bottom sheet de tabs af).
  useEffect(() => {
    if (!activeRef) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setActiveRef(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [activeRef]);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const r = await fetchResearchRun(id, signal);
      setRun(r);
      setError(null);
    } catch (e) {
      if (!signal?.aborted) setError(errText(e));
    }
  }, [id]);

  useEffect(() => {
    const c = new AbortController();
    setRun(null);
    setActiveRef(null);
    setTab('dossier');
    void load(c.signal);
    return () => c.abort();
  }, [load]);

  useEffect(() => {
    if (!run || !isRunning(run.status)) return;
    const t = setInterval(() => void load(), 3000);
    return () => clearInterval(t);
  }, [run, load]);

  const sources = run?.sources ?? [];
  const byRef = useMemo(() => new Map(sources.map(s => [s.ref, s])), [sources]);
  const active = activeRef ? byRef.get(activeRef) ?? null : null;

  const act = async (name: string, fn: () => Promise<void>) => {
    setBusy(name);
    setNotice(null);
    try { await fn(); } catch (e) { setNotice(errText(e)); } finally { setBusy(null); }
  };

  if (error && !run) {
    return (
      <div className="max-w-4xl mx-auto pt-2">
        <button type="button" onClick={onBack} className={`mb-8 flex items-center gap-2 ${mono}`}><ArrowLeft size={14} /> Dossiers</button>
        <p role="alert" className="text-red-700">{error}</p>
      </div>
    );
  }
  if (!run) return <div className="max-w-4xl mx-auto pt-10"><Loader2 className="animate-spin text-brand-ink/40" /></div>;

  const done = run.status === 'done';
  const findingsCount = sources.reduce((n, s) => n + s.findings.length, 0);
  const dates = sources.map(s => s.date).filter(Boolean) as string[];

  return (
    <div className="max-w-6xl mx-auto pt-2">
      <button type="button" onClick={onBack} className={`mb-8 flex items-center gap-2 rounded hover:text-brand-accent ${mono}`}>
        <ArrowLeft size={14} /> Dossiers
      </button>

      <header className="mb-8 max-w-4xl">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <StatusBadge status={run.status} />
          {done && <span className={mono}>{sources.length} bronnen · {findingsCount} bevindingen{dates.length ? ` · ${formatDateNL(dates[0])} – ${formatDateNL(dates[dates.length - 1])}` : ''}</span>}
        </div>
        <h1 className="font-display text-4xl md:text-5xl text-brand-ink font-medium tracking-[-0.035em] mb-3">
          {run.title || 'Nieuw dossier'}
        </h1>
        <p className="font-serif text-[16px] text-brand-ink/60">{run.plan?.question || run.question}</p>

        <div className="mt-5 flex flex-wrap gap-2">
          {isRunning(run.status) && (
            <button type="button" className={actionBtn} disabled={busy !== null}
              onClick={() => act('cancel', async () => { await cancelResearchRun(run.id); await load(); })}>
              <Square size={13} /> Stoppen
            </button>
          )}
          {(run.status === 'failed' || run.status === 'cancelled') && (
            <button type="button" className={actionBtn} disabled={busy !== null}
              onClick={() => act('resume', async () => { await resumeResearchRun(run.id); await load(); })}>
              <Play size={13} /> Verder vanaf laatste stap
            </button>
          )}
          {done && (
            <>
              <button type="button" className={actionBtn} disabled={busy !== null}
                title="Zoekt nieuwe items sinds dit dossier; hergebruikt wat al gelezen is"
                onClick={() => act('refresh', async () => { const r = await refreshResearchRun(run.id); onOpenRun(r.id); })}>
                {busy === 'refresh' ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Vernieuwen
              </button>
              <button type="button" className={actionBtn} disabled={busy !== null}
                onClick={() => act('obsidian', async () => { const r = await exportResearchToObsidian(run.id); setNotice(`Opgeslagen in Obsidian: ${r.path}`); })}>
                {busy === 'obsidian' ? <Loader2 size={13} className="animate-spin" /> : <NotebookPen size={13} />} Naar Obsidian
              </button>
              <button type="button" className={actionBtn} disabled={busy !== null}
                onClick={() => act('md', async () => {
                  const md = await fetchResearchMarkdown(run.id);
                  const a = document.createElement('a');
                  a.href = URL.createObjectURL(new Blob([md], { type: 'text/markdown' }));
                  a.download = `${(run.title || 'dossier').replace(/[^\w\s-]/g, '').trim() || 'dossier'}.md`;
                  a.click();
                  URL.revokeObjectURL(a.href);
                })}>
                <Download size={13} /> Markdown
              </button>
            </>
          )}
          {!isRunning(run.status) && (
            <button type="button" className={actionBtn} disabled={busy !== null}
              onClick={() => { if (window.confirm('Dit dossier verwijderen?')) void act('delete', async () => { await deleteResearchRun(run.id); onBack(); }); }}>
              <Trash2 size={13} /> Verwijderen
            </button>
          )}
        </div>
        {notice && <p role="status" className="mt-3 text-[13px] text-brand-ink/60">{notice}</p>}
      </header>

      {!done && <Pipeline run={run} />}

      {done && (
        <>
          <nav className="mb-8 flex flex-wrap gap-2 border-b border-brand-ink/8 pb-3" aria-label="Dossier-onderdelen">
            {([
              ['dossier', 'Dossier'], ['findings', `Bevindingen ${findingsCount}`], ['sources', `Bronnen ${sources.length}`],
              ['funnel', 'Trechter'], ['quality', 'Kwaliteit'],
            ] as [Tab, string][]).map(([t, label]) => (
              <button key={t} type="button" onClick={() => setTab(t)} aria-pressed={tab === t} className={chip(tab === t)}>{label}</button>
            ))}
          </nav>
          <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div className="min-w-0">
              {tab === 'dossier' && <Report run={run} onCite={setActiveRef} />}
              {tab === 'findings' && <Findings run={run} onCite={setActiveRef} />}
              {tab === 'sources' && <Sources sources={sources} onCite={setActiveRef} onOpenItem={onOpenItem} />}
              {tab === 'funnel' && <Funnel id={run.id} onOpenItem={onOpenItem} />}
              {tab === 'quality' && <Quality run={run} />}
              {tab === 'dossier' && <FollowUps run={run} onCite={setActiveRef} onAsked={() => void load()} />}
            </div>
            <aside className="hidden lg:block">
              <div className="sticky top-24">
                {active ? <SourcePanel source={active} onClose={() => setActiveRef(null)} onOpenItem={onOpenItem} />
                  : <Timeline sources={sources} />}
              </div>
            </aside>
          </div>
          {active && (
            <div className="lg:hidden fixed inset-x-0 bottom-0 z-40 max-h-[70vh] overflow-y-auto rounded-t-3xl border-t border-brand-ink/10 bg-brand-cream p-5 shadow-2xl">
              <SourcePanel source={active} onClose={() => setActiveRef(null)} onOpenItem={onOpenItem} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Pipeline({ run }: { run: ResearchRun }) {
  const i = stageIndex(run.status);
  const p = run.progress ?? {};
  return (
    <section className="max-w-3xl rounded-3xl border border-brand-ink/8 bg-brand-surface/70 p-5 md:p-7">
      <ol className="space-y-4">
        {STAGES.map((s, k) => {
          const state = run.status === 'failed' || run.status === 'cancelled'
            ? (k < i ? 'done' : k === i ? 'stopped' : 'todo')
            : k < i ? 'done' : k === i ? 'active' : 'todo';
          const pct = state === 'active' && p.total ? Math.round(((p.done ?? 0) / p.total) * 100) : null;
          return (
            <li key={s.id} className="flex gap-4">
              <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${
                state === 'done' ? 'bg-brand-accent text-brand-cream'
                  : state === 'active' ? 'bg-brand-accent/15 text-brand-accent'
                  : state === 'stopped' ? 'bg-red-600/10 text-red-700' : 'bg-brand-ink/5 text-brand-ink/30'}`}>
                {state === 'done' ? <Check size={13} /> : state === 'active' ? <Loader2 size={13} className="animate-spin" /> : state === 'stopped' ? <X size={13} /> : k + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className={`text-[14px] font-semibold ${state === 'todo' ? 'text-brand-ink/35' : 'text-brand-ink'}`}>{s.label}</div>
                <div className="text-[12.5px] text-brand-ink/50">{s.detail}</div>
                {state === 'active' && s.id === 'deepening' && p.step && (
                  <div className="mt-1 text-[12px] text-brand-accent">
                    {{ planning: 'gaten zoeken in de eerste ronde…', recall: 'gericht zoeken…', screening: 'nieuwe bronnen screenen…', extracting: 'nieuwe bronnen lezen…' }[p.step]}
                  </div>
                )}
                {pct !== null && (
                  <div className="mt-2 flex items-center gap-3">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-brand-ink/8">
                      <div className="h-full rounded-full bg-brand-accent transition-all" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="font-mono text-[11px] text-brand-ink/50">{p.done}/{p.total}</span>
                  </div>
                )}
                {s.id === 'deepening' && state === 'done' && run.plan?.deepen?.gaps && (
                  <p className="mt-1 font-serif text-[13px] italic text-brand-ink/55">{run.plan.deepen.gaps}</p>
                )}
                {s.id === 'planning' && state === 'done' && run.plan && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {run.plan.aspects.map(a => (
                      <span key={a.id} title={a.description} className="rounded-full bg-brand-surface-low px-2.5 py-0.5 text-[11.5px] text-brand-ink/65">{a.name}</span>
                    ))}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      {run.status === 'failed' && run.error && <p role="alert" className="mt-6 text-[13px] text-red-700">{run.error}</p>}
      {run.stats?.llm_calls ? <p className={`mt-6 ${mono}`}>{run.stats.llm_calls} modelaanroepen tot nu toe</p> : null}
    </section>
  );
}

// ---- rapport met klikbare bronverwijzingen

const PROSE_TAGS = ['p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'a', 'blockquote', 'code',
  'pre', 'span', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td'];

function useCiteClick(onCite: (ref: string) => void) {
  return (e: ReactMouseEvent<HTMLDivElement>) => {
    const el = (e.target as HTMLElement).closest('[data-ref]');
    if (el) {
      e.preventDefault();
      onCite(el.getAttribute('data-ref')!);
    }
  };
}

function Markdown({ text, onCite, size = 'md', dropTitle = false }: {
  text: string; onCite: (ref: string) => void; size?: 'sm' | 'md'; dropTitle?: boolean;
}) {
  const html = useMemo(() => {
    const src = dropTitle ? text.replace(/^\s*#\s+.+\n/, '') : text;
    const raw = marked.parse(src, { async: false, gfm: true }) as string;
    const clean = DOMPurify.sanitize(raw, { ALLOWED_TAGS: PROSE_TAGS, ALLOWED_ATTR: ['href'] });
    return citationsToButtons(clean);
  }, [text, dropTitle]);
  return (
    <div
      onClick={useCiteClick(onCite)}
      className={`prose-stroom dossier-prose font-serif text-brand-ink/85 max-w-none ${size === 'sm' ? 'text-[15px] leading-[1.6]' : 'text-[17px] leading-[1.7]'}`}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function Report({ run, onCite }: { run: ResearchRun; onCite: (ref: string) => void }) {
  return <article className="max-w-3xl"><Markdown text={run.report ?? ''} onCite={onCite} dropTitle /></article>;
}

function FollowUps({ run, onCite, onAsked }: { run: ResearchRun; onCite: (r: string) => void; onAsked: () => void }) {
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const items = run.followups ?? [];
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (q.trim().length < 3 || busy) return;
    setBusy(true);
    setError(null);
    setPending(q.trim());
    try {
      await askResearchRun(run.id, q.trim());
      setQ('');
      onAsked();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
      setPending(null);
    }
  };
  return (
    <section className="mt-16 max-w-3xl border-t border-brand-ink/10 pt-10">
      <h2 className="mb-1 flex items-center gap-2 font-display text-2xl text-brand-ink"><MessageSquare size={18} /> Doorvragen</h2>
      <p className="mb-6 font-serif text-[14px] text-brand-ink/55">Vragen over dit dossier worden beantwoord uit dezelfde {run.sources?.length ?? 0} bronnen.</p>
      <div className="space-y-8">
        {items.map((f, k) => (
          <div key={k}>
            <div className="mb-2 font-semibold text-brand-ink">{f.question}</div>
            <Markdown text={f.answer} onCite={onCite} size="sm" />
            <div className={`mt-1 ${mono} !text-[10px]`}>{f.model}</div>
          </div>
        ))}
        {pending && (
          <div>
            <div className="mb-2 font-semibold text-brand-ink">{pending}</div>
            <Loader2 size={16} className="animate-spin text-brand-ink/40" />
          </div>
        )}
      </div>
      <form onSubmit={submit} className="mt-6 flex items-end gap-2 rounded-2xl border border-brand-ink/10 bg-brand-surface p-2 pl-4">
        <textarea value={q} onChange={e => setQ(e.target.value)} rows={1} maxLength={800}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) void submit(e); }}
          placeholder="Bijv. welke Nederlandse overheden kiezen voor eigen software?"
          aria-label="Vervolgvraag"
          className="min-h-[40px] flex-1 resize-none bg-transparent py-2 font-serif text-[15px] text-brand-ink placeholder:text-brand-ink/35 focus:outline-none" />
        <button type="submit" disabled={busy || q.trim().length < 3} aria-label="Vraag versturen"
          className="mb-0.5 flex h-10 w-10 items-center justify-center rounded-full bg-brand-accent text-brand-cream disabled:opacity-40">
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
        </button>
      </form>
      {error && <p role="alert" className="mt-2 text-[13px] text-red-700">{error}</p>}
    </section>
  );
}

// ---- bevindingen

function Findings({ run, onCite }: { run: ResearchRun; onCite: (ref: string) => void }) {
  const aspects = run.plan?.aspects ?? [];
  const [aspect, setAspect] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const rows = useMemo(() => {
    const out: { s: ResearchSource; f: ResearchFinding }[] = [];
    for (const s of run.sources ?? []) for (const f of s.findings) out.push({ s, f });
    return out;
  }, [run.sources]);
  const needle = q.trim().toLowerCase();
  const shown = rows.filter(({ s, f }) =>
    (!aspect || f.aspect === aspect) && (!evidence || f.evidence === evidence) &&
    (!needle || `${f.claim} ${f.actors.join(' ')} ${f.sector} ${s.title} ${s.source}`.toLowerCase().includes(needle)));
  const count = (id: string) => rows.filter(r => r.f.aspect === id).length;
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2">
        <button type="button" className={chip(aspect === null)} onClick={() => setAspect(null)}>Alle aspecten</button>
        {aspects.map(a => (
          <button key={a.id} type="button" title={a.description} className={chip(aspect === a.id)} onClick={() => setAspect(a.id)}>
            {a.name} <span className="opacity-60">{count(a.id)}</span>
          </button>
        ))}
        {count('other') > 0 && <button type="button" className={chip(aspect === 'other')} onClick={() => setAspect('other')}>Overig <span className="opacity-60">{count('other')}</span></button>}
      </div>
      <div className="mb-6 flex flex-wrap items-center gap-2">
        <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Filter op bedrijf, sector, woord…" aria-label="Filter bevindingen"
          className="w-full sm:w-64 rounded-full border border-brand-ink/10 bg-brand-surface px-4 py-1.5 text-[13px] text-brand-ink focus:outline-none focus:border-brand-accent" />
        {Object.entries(EVIDENCE_LABEL).map(([k, label]) => (
          <button key={k} type="button" className={chip(evidence === k)} onClick={() => setEvidence(evidence === k ? null : k)}>{label}</button>
        ))}
        <span className={`ml-auto ${mono}`}>{shown.length} getoond</span>
      </div>
      <ul className="space-y-3">
        {shown.map(({ s, f }, k) => (
          <li key={`${s.ref}-${k}`} className="rounded-2xl border border-brand-ink/8 bg-brand-surface/60 p-4">
            <p className="font-serif text-[15.5px] leading-relaxed text-brand-ink/90">{f.claim}</p>
            {f.quote && <p className="mt-2 border-l-2 border-brand-accent/40 pl-3 font-serif text-[14px] italic text-brand-ink/60">“{f.quote}”{f.speaker ? ` — ${f.speaker}` : ''}</p>}
            <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[11.5px]">
              <button type="button" onClick={() => onCite(s.ref)} className="rounded-full bg-brand-accent/10 px-2 py-0.5 font-semibold text-brand-accent hover:bg-brand-accent/20">{s.ref}</button>
              <span className="text-brand-ink/50">{s.source} · {formatDateNL(s.date)}</span>
              {f.stance && <Tag>{f.stance}</Tag>}
              {f.evidence && <Tag>{EVIDENCE_LABEL[f.evidence] ?? f.evidence}</Tag>}
              {f.region && <Tag>{f.region}</Tag>}
              {f.sector && f.sector !== 'algemeen' && <Tag>{f.sector}</Tag>}
              {f.actors.slice(0, 4).map(a => <Tag key={a} strong>{a}</Tag>)}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Tag({ children, strong = false }: { children: ReactNode; strong?: boolean }) {
  return <span className={`rounded-full px-2 py-0.5 ${strong ? 'bg-brand-ink/8 text-brand-ink/75' : 'bg-brand-surface-low text-brand-ink/55'}`}>{children}</span>;
}

// ---- bronnen, tijdlijn, trechter, kwaliteit

function Sources({ sources, onCite, onOpenItem }: { sources: ResearchSource[]; onCite: (r: string) => void; onOpenItem: (id: string) => void }) {
  const [sort, setSort] = useState<'date' | 'relevance'>('date');
  const list = [...sources].sort((a, b) => sort === 'date'
    ? (b.date ?? '').localeCompare(a.date ?? '')
    : b.relevance - a.relevance || b.findings.length - a.findings.length);
  return (
    <div>
      <div className="mb-5 flex gap-2">
        <button type="button" className={chip(sort === 'date')} onClick={() => setSort('date')}>Nieuwste eerst</button>
        <button type="button" className={chip(sort === 'relevance')} onClick={() => setSort('relevance')}>Meest relevant</button>
      </div>
      <ul className="divide-y divide-brand-ink/8">
        {list.map(s => (
          <li key={s.ref} className="flex items-start gap-3 py-3">
            <button type="button" onClick={() => onCite(s.ref)} className="mt-0.5 w-11 shrink-0 rounded-full bg-brand-accent/10 py-0.5 text-center text-[11.5px] font-semibold text-brand-accent hover:bg-brand-accent/20">{s.ref}</button>
            <div className="min-w-0 flex-1">
              <button type="button" onClick={() => onOpenItem(s.item_id)} className="text-left font-serif text-[15.5px] text-brand-ink hover:text-brand-accent">{s.title}</button>
              <div className="text-[12px] text-brand-ink/50">
                {s.source} · {formatDateNL(s.date)} · {s.findings.length} bevinding{s.findings.length === 1 ? '' : 'en'}
                {s.cited === false && ' · niet geciteerd'}
              </div>
            </div>
            <span className="shrink-0 text-[12px] tracking-widest text-brand-accent" title={`relevantie ${s.relevance}/3`}>{'●'.repeat(s.relevance)}<span className="text-brand-ink/15">{'●'.repeat(3 - s.relevance)}</span></span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Timeline({ sources }: { sources: ResearchSource[] }) {
  const bins = monthHistogram(sources.map(s => s.date));
  if (!bins.length) return null;
  const max = Math.max(...bins.map(b => b.n));
  return (
    <div className="rounded-2xl border border-brand-ink/8 bg-brand-surface/60 p-4">
      <div className={`${mono} mb-3`}>Bronnen door de tijd</div>
      <div className="flex h-24 items-end gap-[3px]" role="img" aria-label="Aantal bronnen per maand">
        {bins.map(b => (
          <div key={b.month} title={`${b.label}: ${b.n}`} className="flex-1 rounded-t bg-brand-accent/70" style={{ height: `${Math.max(4, (b.n / max) * 100)}%` }} />
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[10.5px] text-brand-ink/45">
        <span>{bins[0].label}</span><span>{bins[bins.length - 1].label}</span>
      </div>
      <p className="mt-4 text-[12.5px] leading-relaxed text-brand-ink/55">Klik op een bronverwijzing in de tekst om de bevindingen en citaten van die bron hier te zien.</p>
    </div>
  );
}

function SourcePanel({ source, onClose, onOpenItem }: { source: ResearchSource; onClose: () => void; onOpenItem: (id: string) => void }) {
  return (
    <div className="rounded-2xl border border-brand-ink/10 bg-brand-surface p-4 shadow-sm">
      <div className="mb-2 flex items-start justify-between gap-2">
        <span className="rounded-full bg-brand-accent px-2 py-0.5 text-[11.5px] font-bold text-brand-cream">{source.ref}</span>
        <button type="button" onClick={onClose} aria-label="Sluiten" className="text-brand-ink/40 hover:text-brand-accent"><X size={16} /></button>
      </div>
      <div className="font-display text-[19px] leading-snug text-brand-ink">{source.title}</div>
      <div className="mt-1 text-[12px] text-brand-ink/50">{source.source} · {formatDateNL(source.date)}</div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={() => onOpenItem(source.item_id)} className={actionBtn}><FileText size={13} /> Open in Stroom</button>
        {source.url && <a href={source.url} target="_blank" rel="noreferrer" className={actionBtn}><ExternalLink size={13} /> Origineel</a>}
      </div>
      <ul className="mt-4 space-y-3 max-h-[55vh] overflow-y-auto pr-1">
        {source.findings.map((f, k) => (
          <li key={k} className="text-[13.5px] leading-relaxed text-brand-ink/80">
            <p className="font-serif">{f.claim}</p>
            {f.quote && <p className="mt-1 border-l-2 border-brand-accent/40 pl-2 font-serif text-[13px] italic text-brand-ink/55">“{f.quote}”</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Funnel({ id, onOpenItem }: { id: string; onOpenItem: (id: string) => void }) {
  const [rows, setRows] = useState<ResearchFunnelRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'used' | 'dropped'>('all');
  const ref = useRef(id);
  useEffect(() => {
    ref.current = id;
    fetchResearchFunnel(id).then(r => { if (ref.current === id) setRows(r); }).catch(e => setError(errText(e)));
  }, [id]);
  if (error) return <p role="alert" className="text-red-700">{error}</p>;
  if (!rows) return <Loader2 className="animate-spin text-brand-ink/40" />;
  const screened = rows.filter(r => r.screen_score !== null);
  const used = rows.filter(r => r.n_findings > 0);
  const shown = rows.filter(r => filter === 'all' || (filter === 'used' ? r.n_findings > 0 : r.screen_score !== null && r.n_findings === 0));
  const stages = [
    { label: 'Gevonden door de zoekvragen', n: rows.length },
    { label: 'Gescreend op titel en teaser', n: screened.length },
    { label: 'Relevant genoeg om te lezen', n: screened.filter(r => (r.screen_score ?? 0) >= 2).length },
    { label: 'Leverden bevindingen op', n: used.length },
  ];
  return (
    <div>
      <div className="mb-8 space-y-2">
        {stages.map(s => (
          <div key={s.label} className="flex items-center gap-3">
            <div className="h-7 rounded-lg bg-brand-accent/70" style={{ width: `${Math.max(3, (s.n / Math.max(1, rows.length)) * 100)}%` }} />
            <span className="shrink-0 text-[13px] text-brand-ink/70"><strong className="text-brand-ink">{s.n}</strong> {s.label.toLowerCase()}</span>
          </div>
        ))}
      </div>
      <div className="mb-4 flex gap-2">
        {(['all', 'used', 'dropped'] as const).map(f => (
          <button key={f} type="button" className={chip(filter === f)} onClick={() => setFilter(f)}>
            {f === 'all' ? 'Alles' : f === 'used' ? 'Gebruikt' : 'Afgevallen na screening'}
          </button>
        ))}
      </div>
      <ul className="divide-y divide-brand-ink/8 text-[13.5px]">
        {shown.slice(0, 300).map(r => (
          <li key={r.item_id} className="flex items-center gap-3 py-2">
            <span className="w-8 shrink-0 text-center font-mono text-[11px] text-brand-ink/45" title="screening-score 0-3">{r.screen_score ?? '–'}</span>
            <button type="button" onClick={() => onOpenItem(r.item_id)} className="min-w-0 flex-1 truncate text-left text-brand-ink/80 hover:text-brand-accent">{r.title}</button>
            <span className="hidden shrink-0 text-[11.5px] text-brand-ink/45 sm:inline">{r.source} · {formatDateNL(r.date)}</span>
            <span className="w-14 shrink-0 text-right text-[11.5px] text-brand-ink/45" title={r.queries.join('\n')}>{r.queries.length}× gevonden</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Quality({ run }: { run: ResearchRun }) {
  const issues = run.critique?.issues ?? [];
  const byModel = run.stats?.by_model ?? {};
  const roles: [string, string][] = [['plan', 'Plan & zoekvragen'], ['deepen', 'Verdieping'], ['write', 'Eerste versie'], ['critique', 'Kritische review'], ['revise', 'Herziening']];
  return (
    <div className="max-w-3xl space-y-10">
      <section>
        <h2 className="mb-3 font-display text-2xl text-brand-ink">Wie deed wat</h2>
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-[14px]">
          {roles.filter(([k]) => run.models?.[k]).map(([k, label]) => (
            <Fragment key={k}><dt className="text-brand-ink/55">{label}</dt><dd className="font-mono text-[13px] text-brand-ink">{run.models![k]}</dd></Fragment>
          ))}
        </dl>
        <table className="mt-5 w-full text-[13px]">
          <thead><tr className="text-left text-brand-ink/50"><th className="py-1 font-medium">Model</th><th className="font-medium">Aanroepen</th><th className="font-medium">Mislukt</th><th className="font-medium">Rekentijd</th></tr></thead>
          <tbody>
            {Object.entries(byModel).sort((a, b) => b[1].calls - a[1].calls).map(([m, s]) => (
              <tr key={m} className="border-t border-brand-ink/8"><td className="py-1.5 font-mono">{m}</td><td>{s.calls}</td><td>{s.failures}</td><td>{Math.round(s.secs)} s</td></tr>
            ))}
          </tbody>
        </table>
        {run.stats?.secs ? <p className={`mt-3 ${mono}`}>Doorlooptijd {Math.round(run.stats.secs / 60)} min</p> : null}
      </section>
      <section>
        <h2 className="mb-1 font-display text-2xl text-brand-ink">Review van de eerste versie</h2>
        {run.critique?.verdict && <p className="mb-4 font-serif text-[15px] text-brand-ink/65">{run.critique.verdict}</p>}
        {run.critique?.text && <pre className="mb-4 whitespace-pre-wrap font-serif text-[14px] leading-relaxed text-brand-ink/70">{run.critique.text}</pre>}
        <ul className="space-y-3">
          {issues.map((i, k) => (
            <li key={k} className="rounded-2xl border border-brand-ink/8 bg-brand-surface/60 p-4 text-[14px]">
              <div className="mb-1 flex items-center gap-2"><Tag strong>{i.type}</Tag><span className="text-brand-ink/50 line-clamp-1">{i.where}</span></div>
              <p className="text-brand-ink/80">{i.problem}</p>
              <p className="mt-1 text-brand-ink/55">→ {i.fix}</p>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-[12.5px] text-brand-ink/45">Het schrijfmodel heeft deze punten verwerkt in de versie die je bij Dossier leest.</p>
      </section>
      {run.plan && (
        <section>
          <h2 className="mb-3 font-display text-2xl text-brand-ink">Zoekvragen ({run.plan.queries.length})</h2>
          <div className="flex flex-wrap gap-1.5">{run.plan.queries.map(q => <Tag key={q}>{q}</Tag>)}</div>
          {run.plan.deepen && run.plan.deepen.queries.length > 0 && (
            <>
              <h3 className="mb-2 mt-6 font-display text-xl text-brand-ink">Verdiepingsronde ({run.plan.deepen.queries.length})</h3>
              {run.plan.deepen.gaps && <p className="mb-3 font-serif text-[14px] text-brand-ink/60">{run.plan.deepen.gaps}</p>}
              <div className="flex flex-wrap gap-1.5">{run.plan.deepen.queries.map(q => <Tag key={q} strong>{q}</Tag>)}</div>
            </>
          )}
        </section>
      )}
    </div>
  );
}
