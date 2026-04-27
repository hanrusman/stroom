import React, { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { marked } from 'marked';
import { Search, User as UserIcon, Settings, ArrowRight, PlayCircle, Headphones, FileText, MessageSquare, ArrowLeft, ExternalLink, Bookmark, Clock, Archive, Sparkles, Mic, Loader2, Check, X, CalendarClock, Sun, Moon, Newspaper, RefreshCw } from 'lucide-react';
import { AdminPage } from './AdminPage';
import { fetchTopics, fetchHuygens, fetchItem, setItemStatus, summarizeItem, transcribeItem,
         scheduleItem, fetchLessons, rateLesson, fetchFilteredItems,
         fetchTopicDigest, regenerateTopicDigest,
         fetchMe, login as apiLogin, logout as apiLogout, ApiError,
         Topic, HuygensTopic, HuygensItem, ItemDetail, ItemFormat, ItemStatus, User, Lesson, ItemFilter, ItemWindow, TopicDigest, DigestModel } from './api';

const RAIL_META: Record<ItemFormat, { label: string; icon: React.ComponentType<{ size?: number }> }> = {
  article: { label: 'Articles',   icon: FileText },
  podcast: { label: 'Podcasts',   icon: Headphones },
  video:   { label: 'Videos',     icon: PlayCircle },
  short:   { label: 'Short-form', icon: MessageSquare },
};

const stripHtml = (s: string | null) =>
  (s ?? '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();

const TopicChip = ({ topic, active, onClick }: {
  key?: React.Key; topic: Topic; active: boolean; onClick: () => void;
}) => (
  <button
    onClick={onClick}
    disabled={topic.item_count === 0}
    className={`px-6 py-2.5 rounded-full text-[13px] font-medium whitespace-nowrap shrink-0 transition-all ${
      active ? 'bg-brand-accent text-brand-cream shadow-sm'
      : topic.item_count === 0 ? 'bg-brand-surface text-brand-ink/30 cursor-not-allowed'
      : 'bg-brand-surface hover:bg-brand-surface-low text-brand-ink/70'
    }`}
  >
    {topic.name}
    <span className="ml-2 opacity-50 text-[11px]">{topic.item_count}</span>
  </button>
);

const Meta = ({ item }: { item: HuygensItem }) => (
  <div className="text-brand-ink/40 mt-3 text-[10px] font-mono uppercase tracking-[0.18em] flex items-center gap-2">
    <span className="font-medium">{item.source_name}</span>
    {item.published_at && (<>
      <span className="opacity-30">·</span>
      <span>{new Date(item.published_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}</span>
    </>)}
  </div>
);

const ArticleCard = ({ item, onOpen }: { key?: React.Key; item: HuygensItem; onOpen: (id: string) => void }) => {
  const summary = stripHtml(item.description);
  const img = item.thumbnail_url ?? item.source_image_url;
  return (
    <motion.article
      onClick={() => onOpen(item.id)}
      initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
      className="snap-start shrink-0 w-[85vw] md:w-[340px] h-[400px] rounded-3xl overflow-hidden flex flex-col bg-brand-surface border border-brand-ink/5 hover:shadow-md transition-all cursor-pointer group"
    >
      {img ? (
        <div className="w-full h-32 overflow-hidden bg-brand-surface-low shrink-0">
          <img src={img} alt={item.title} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-700 ease-out" />
        </div>
      ) : (
        <div className="w-full h-2 bg-brand-accent/30 shrink-0" />
      )}
      <div className="p-6 flex flex-col flex-1 min-h-0">
        <h3 className="font-serif font-semibold text-[22px] text-brand-ink group-hover:text-brand-accent transition-colors line-clamp-3 leading-[1.2] tracking-[-0.01em] mb-3">
          {item.title}
        </h3>
        <p className="text-brand-ink/70 line-clamp-[6] text-[13px] leading-[1.55] flex-1">{summary}</p>
        <Meta item={item} />
      </div>
    </motion.article>
  );
};

const MediaCard = ({ item, format, onOpen }: { key?: React.Key; item: HuygensItem; format: 'podcast' | 'video'; onOpen: (id: string) => void }) => {
  const summary = stripHtml(item.description);
  const isVideo = format === 'video';
  const img = item.thumbnail_url ?? item.source_image_url;

  // Podcasts: compact horizontaal — thumbnail links, tekst rechts.
  if (!isVideo) {
    return (
      <motion.article
        onClick={() => onOpen(item.id)}
        initial={{ opacity: 0, y: 10 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
        className="snap-start shrink-0 w-[85vw] md:w-[360px] h-[140px] rounded-2xl overflow-hidden flex gap-3 p-3 bg-brand-surface border border-brand-ink/5 hover:shadow-sm transition-all cursor-pointer group"
      >
        <div className="w-28 h-28 shrink-0 rounded-xl overflow-hidden bg-brand-surface-low">
          {img ? (
            <img src={img} alt={item.title} className="w-full h-full object-cover" />
          ) : (
            <div className="w-full h-full flex items-center justify-center"><Headphones size={24} className="text-brand-ink/30" /></div>
          )}
        </div>
        <div className="flex flex-col flex-1 min-w-0">
          <h3 className="font-serif font-semibold text-[15px] text-brand-ink group-hover:text-brand-accent transition-colors line-clamp-3 leading-[1.25] mb-1">
            {item.title}
          </h3>
          <Meta item={item} />
        </div>
      </motion.article>
    );
  }

  // Videos: groter, aspect-video met play-icoon.
  return (
    <motion.article
      onClick={() => onOpen(item.id)}
      initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
      className="snap-start shrink-0 w-[85vw] md:w-[360px] flex flex-col gap-3 group cursor-pointer"
    >
      <div className="w-full aspect-video rounded-2xl overflow-hidden relative bg-brand-surface">
        {img ? (
          <img src={img} alt={item.title} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-700 ease-out" />
        ) : (
          <div className="w-full h-full bg-gradient-to-br from-brand-surface to-brand-surface-low" />
        )}
        <div className="absolute top-3 left-3 flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[9px] font-bold uppercase tracking-[0.2em] backdrop-blur-md bg-brand-accent text-white">
          <PlayCircle size={10} /> video
        </div>
      </div>
      <div className="flex flex-col gap-1 px-1">
        <h3 className="font-serif font-semibold text-[18px] text-brand-ink group-hover:text-brand-accent transition-colors line-clamp-2 leading-[1.25]">
          {item.title}
        </h3>
        <p className="text-brand-ink/65 line-clamp-2 text-[13px] leading-[1.45]">{summary}</p>
        <Meta item={item} />
      </div>
    </motion.article>
  );
};

const ShortCard = ({ item, onOpen }: { key?: React.Key; item: HuygensItem; onOpen: (id: string) => void }) => {
  const summary = stripHtml(item.description);
  return (
    <motion.article
      onClick={() => onOpen(item.id)}
      initial={{ opacity: 0, y: 10 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
      className="snap-start shrink-0 w-[75vw] md:w-[320px] rounded-3xl p-6 flex flex-col gap-4 bg-brand-surface border border-brand-ink/5 hover:shadow-sm transition-all cursor-pointer"
    >
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] font-medium text-brand-ink">{item.author ?? item.source_name}</div>
      <p className="font-serif text-[15px] leading-[1.55] text-brand-ink/80 line-clamp-5">{summary}</p>
      <div className="font-mono text-[9px] uppercase tracking-[0.18em] text-brand-ink/40 mt-auto pt-2 border-t border-brand-ink/5">
        {item.source_name}
      </div>
    </motion.article>
  );
};

const ItemCard = ({ item, format, onOpen }: { key?: React.Key; item: HuygensItem; format: ItemFormat; onOpen: (id: string) => void }) => {
  if (format === 'article') return <ArticleCard item={item} onOpen={onOpen} />;
  if (format === 'short')   return <ShortCard item={item} onOpen={onOpen} />;
  return <MediaCard item={item} format={format} onOpen={onOpen} />;
};

const Rail = ({ format, items, onOpen }: { key?: React.Key; format: ItemFormat; items: HuygensItem[]; onOpen: (id: string) => void }) => {
  const meta = RAIL_META[format];
  const Icon = meta.icon;
  return (
    <section className="mb-20">
      <div className="flex justify-between items-end mb-10 border-b border-brand-ink/10 pb-6">
        <h2 className="font-display text-[32px] md:text-[40px] text-brand-ink font-light flex items-baseline gap-4 tracking-[-0.02em] leading-none">
          <Icon size={22} />
          <span>{meta.label}</span>
          <span className="font-mono text-[12px] font-medium text-brand-ink/40 tracking-[0.1em]">{items.length}</span>
        </h2>
        {items.length > 0 && (
          <a className="font-mono text-[10px] font-medium text-brand-accent hover:opacity-70 flex items-center gap-1.5 uppercase tracking-[0.2em]" href="#">
            View All <ArrowRight size={12} />
          </a>
        )}
      </div>
      {items.length === 0 ? (
        <div className="text-sm text-brand-ink/30 italic px-2 pb-12">Nog geen items voor deze rail.</div>
      ) : (
        <div className="flex overflow-x-auto hide-scrollbar gap-8 pb-12 -mx-6 px-6 md:-mx-12 md:px-12 snap-x">
          {items.map(item => <ItemCard key={item.id} item={item} format={format} onOpen={onOpen} />)}
        </div>
      )}
    </section>
  );
};

const FORMAT_BADGE: Record<ItemFormat, { label: string; className: string }> = {
  article: { label: 'Article',    className: 'bg-brand-cream/90 text-brand-ink shadow-sm' },
  podcast: { label: 'Podcast',    className: 'bg-brand-cream/90 text-brand-ink shadow-sm' },
  video:   { label: 'Video',      className: 'bg-brand-accent text-white' },
  short:   { label: 'Short-form', className: 'bg-brand-cream/90 text-brand-ink shadow-sm' },
};

const ActionButton = ({ icon: Icon, label, active, busy, onClick, disabled }: {
  icon: React.ComponentType<{ size?: number }>; label: string;
  active?: boolean; busy?: boolean; disabled?: boolean; onClick: () => void;
}) => (
  <button
    onClick={onClick} disabled={busy || disabled}
    title={label}
    className={`flex items-center gap-2 px-3 py-2 rounded-full font-mono text-[10px] uppercase tracking-[0.18em] transition-all ${
      busy || disabled ? 'opacity-40 cursor-not-allowed' :
      active ? 'bg-brand-accent text-white shadow-sm' :
      'bg-brand-surface hover:bg-brand-surface-low text-brand-ink/70'
    }`}
  >
    {busy ? <Loader2 size={14} className="animate-spin" /> : <Icon size={14} />}
    <span className="hidden md:inline">{label}</span>
  </button>
);

const LessonsSection = ({ itemId }: { itemId: string }) => {
  const [lessons, setLessons] = useState<Lesson[] | null>(null);
  useEffect(() => {
    setLessons(null);
    fetchLessons(itemId).then(setLessons).catch(() => setLessons([]));
  }, [itemId]);

  const setRating = async (lid: string, r: 1 | -1 | null) => {
    setLessons(prev => prev?.map(l => l.id === lid ? { ...l, rating: r } : l) ?? prev);
    try {
      const updated = await rateLesson(lid, r);
      setLessons(prev => prev?.map(l => l.id === lid ? updated : l) ?? prev);
    } catch {
      fetchLessons(itemId).then(setLessons).catch(() => {});
    }
  };

  if (!lessons || lessons.length === 0) return null;
  return (
    <details open className="mb-8 border-t border-brand-ink/10 pt-6">
      <summary className="font-mono text-[11px] uppercase tracking-[0.18em] text-brand-accent cursor-pointer">
        Kernlessen · {lessons.length}
      </summary>
      <ul className="mt-6 space-y-4">
        {lessons.map(l => (
          <li key={l.id} className="flex items-start gap-4 group">
            <div className="flex flex-col gap-1 shrink-0 pt-1">
              <button
                onClick={() => setRating(l.id, l.rating === 1 ? null : 1)}
                title="Nuttig"
                className={`w-7 h-7 flex items-center justify-center rounded-full transition-all ${
                  l.rating === 1 ? 'bg-emerald-500 text-white' : 'bg-brand-surface text-brand-ink/40 hover:text-emerald-600 hover:bg-emerald-50'
                }`}
              ><Check size={14} /></button>
              <button
                onClick={() => setRating(l.id, l.rating === -1 ? null : -1)}
                title="Niet nuttig"
                className={`w-7 h-7 flex items-center justify-center rounded-full transition-all ${
                  l.rating === -1 ? 'bg-rose-500 text-white' : 'bg-brand-surface text-brand-ink/40 hover:text-rose-600 hover:bg-rose-50'
                }`}
              ><X size={14} /></button>
            </div>
            <div className={`flex-1 ${l.rating === -1 ? 'opacity-40' : ''}`}>
              <div className="font-serif font-semibold text-[17px] text-brand-ink mb-1">{l.title}</div>
              <div className="font-serif text-[16px] leading-[1.55] text-brand-ink/80">{l.body}</div>
            </div>
          </li>
        ))}
      </ul>
    </details>
  );
};

const ItemDetailView = ({ id, onBack }: { id: string; onBack: () => void }) => {
  const [item, setItem] = useState<ItemDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [scheduleOpen, setScheduleOpen] = useState(false);

  useEffect(() => {
    setItem(null); setError(null);
    fetchItem(id).then(setItem).catch(e => setError(String(e)));
  }, [id]);

  useEffect(() => {
    if (!item) return;
    const proc = item.processing_status;
    if (proc !== 'queued' && proc !== 'transcribing' && proc !== 'summarizing') return;
    const t = setInterval(() => {
      fetchItem(id).then(setItem).catch(() => {});
    }, 8000);
    return () => clearInterval(t);
  }, [id, item?.processing_status]);

  const wrap = async (key: string, fn: () => Promise<ItemDetail>) => {
    setBusy(key); setError(null);
    try { setItem(await fn()); } catch (e) { setError(String(e)); }
    finally { setBusy(null); }
  };

  const toggle = (target: ItemStatus) =>
    wrap(target, () => setItemStatus(id, item?.status === target ? 'new' : target));

  if (error && !item) return <div className="text-red-600 text-sm py-12">Fout: {error}</div>;
  if (!item) return <div className="text-brand-ink/40 italic py-12">Loading…</div>;

  const hero = item.thumbnail_url ?? item.source_image_url;
  const date = item.published_at
    ? new Date(item.published_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'long', year: 'numeric' })
    : null;
  const isMedia = item.format === 'podcast' || item.format === 'video';
  const proc = item.processing_status;

  return (
    <motion.article initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
      className="max-w-3xl mx-auto pt-2">
      <div className="flex items-center justify-between gap-4 mb-12 flex-wrap">
        <button onClick={onBack}
          className="font-mono text-[11px] uppercase tracking-[0.18em] text-brand-ink/50 hover:text-brand-accent flex items-center gap-2">
          <ArrowLeft size={14} /> Back to Flow
        </button>
        <div className="flex items-center gap-2 flex-wrap">
          <ActionButton icon={Bookmark} label="Save"    active={item.status === 'pinned'}   busy={busy === 'pinned'}   onClick={() => toggle('pinned')} />
          <div className="relative">
            <ActionButton
              icon={CalendarClock}
              label={item.scheduled_for ? new Date(item.scheduled_for).toLocaleDateString('nl-NL', { day: '2-digit', month: 'short' }) : 'Later'}
              active={item.status === 'later' || !!item.scheduled_for}
              busy={busy === 'schedule'}
              onClick={() => setScheduleOpen(v => !v)}
            />
            {scheduleOpen && (
              <div className="absolute right-0 top-full mt-2 z-50 bg-brand-cream border border-brand-ink/10 rounded-2xl shadow-lg p-4 w-64">
                <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 mb-2">Plan voor</div>
                <input
                  type="date"
                  defaultValue={item.scheduled_for ? item.scheduled_for.slice(0, 10) : ''}
                  onChange={async e => {
                    const v = e.target.value;
                    setScheduleOpen(false);
                    await wrap('schedule', () => scheduleItem(id, v ? new Date(v).toISOString() : null));
                  }}
                  className="w-full px-3 py-2 border border-brand-ink/10 rounded-lg font-mono text-sm bg-brand-surface text-brand-ink"
                />
                <div className="flex gap-2 mt-3">
                  <button
                    className="flex-1 text-[11px] font-mono uppercase tracking-[0.15em] py-2 rounded-lg bg-brand-surface hover:bg-brand-surface-low"
                    onClick={async () => { setScheduleOpen(false); await wrap('schedule', () => scheduleItem(id, null)); await wrap('later', () => setItemStatus(id, 'new')); }}
                  >Wis</button>
                  <button
                    className="flex-1 text-[11px] font-mono uppercase tracking-[0.15em] py-2 rounded-lg bg-brand-surface hover:bg-brand-surface-low"
                    onClick={async () => { setScheduleOpen(false); await wrap('later', () => setItemStatus(id, item?.status === 'later' ? 'new' : 'later')); }}
                  >Later (geen datum)</button>
                </div>
              </div>
            )}
          </div>
          <ActionButton icon={Archive}  label="Archive" active={item.status === 'archived'} busy={busy === 'archived'} onClick={() => toggle('archived')} />
          <span className="w-px h-5 bg-brand-ink/10 mx-1" />
          <ActionButton icon={Sparkles} label="Summarize"
            busy={busy === 'summarize' || proc === 'summarizing'}
            disabled={!(item.transcript || item.description)}
            onClick={() => wrap('summarize', () => summarizeItem(id))} />
          {isMedia && (() => {
            const hasTranscript = !!(item.transcript && item.transcript.trim());
            const isQueued = proc === 'queued';
            const isTranscribing = proc === 'transcribing';
            const label = hasTranscript ? 'Transcribed'
                        : isQueued ? (item.queue_position ? `Queued #${item.queue_position}` : 'Queued…')
                        : isTranscribing ? 'Transcribing…'
                        : 'Transcribe';
            return (
              <ActionButton icon={Mic} label={label}
                busy={busy === 'transcribe' || isQueued || isTranscribing}
                disabled={!item.media_url || hasTranscript || isQueued || isTranscribing}
                active={hasTranscript}
                onClick={() => wrap('transcribe', () => transcribeItem(id))} />
            );
          })()}
        </div>
      </div>

      {error && <div className="bg-red-50 text-red-700 text-sm rounded-2xl px-4 py-3 mb-6">{error}</div>}
      {proc === 'failed' && (
        <div className="bg-amber-50 text-amber-800 text-sm rounded-2xl px-4 py-3 mb-6 font-mono uppercase tracking-[0.15em] text-[11px]">
          Processing failed — check logs
        </div>
      )}

      <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-brand-accent mb-4 flex items-center gap-3">
        <span className={`px-2.5 py-1 rounded-full ${FORMAT_BADGE[item.format].className}`}>
          {FORMAT_BADGE[item.format].label}
        </span>
        {item.topics.map(t => <span key={t} className="text-brand-ink/40">{t}</span>)}
      </div>

      <h1 className="font-display font-medium text-4xl md:text-6xl text-brand-ink tracking-[-0.03em] leading-[1.05] mb-8">
        {item.title}
      </h1>

      <div className="flex items-center gap-4 mb-12 pb-8 border-b border-brand-ink/10">
        {item.source_image_url && (
          <img src={item.source_image_url} alt={item.source_name}
               className="w-12 h-12 rounded-lg object-cover" />
        )}
        <div className="flex flex-col gap-0.5">
          <div className="font-serif font-semibold text-brand-ink">{item.author ?? item.source_name}</div>
          <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/50">
            {item.author && <>{item.source_name} · </>}{date}
          </div>
        </div>
      </div>

      {hero && item.format !== 'article' && (
        <div className={`rounded-3xl overflow-hidden mb-12 bg-brand-surface ${item.format === 'video' ? 'aspect-video' : 'aspect-square max-w-md mx-auto'}`}>
          <img src={hero} alt={item.title} className="w-full h-full object-cover" />
        </div>
      )}

      {item.summary && (
        <details open className="mb-8 border-t border-brand-ink/10 pt-6">
          <summary className="font-mono text-[11px] uppercase tracking-[0.18em] text-brand-accent cursor-pointer">
            Samenvatting{item.summary_model ? ` · ${item.summary_model}` : ''} · {item.summary.length} chars
          </summary>
          <div className="font-serif italic text-[20px] leading-[1.5] text-brand-ink/80 border-l-2 border-brand-accent/40 pl-6 mt-6 whitespace-pre-wrap">
            {item.summary}
          </div>
        </details>
      )}

      <LessonsSection itemId={id} />

      {item.description && (
        <details className="mb-8 border-t border-brand-ink/10 pt-6">
          <summary className="font-mono text-[11px] uppercase tracking-[0.18em] text-brand-accent cursor-pointer">
            Beschrijving (RSS)
          </summary>
          <div
            className="prose-stroom font-sans text-[16px] leading-[1.7] text-brand-ink/85 max-w-none mt-6"
            dangerouslySetInnerHTML={{ __html: item.description }}
          />
        </details>
      )}

      {item.transcript && (
        <details className="mt-8 border-t border-brand-ink/10 pt-6">
          <summary className="font-mono text-[11px] uppercase tracking-[0.18em] text-brand-accent cursor-pointer">
            Transcript · {item.transcript.length} chars
          </summary>
          <pre className="font-serif text-[15px] leading-[1.7] text-brand-ink/80 whitespace-pre-wrap mt-6">{item.transcript}</pre>
        </details>
      )}

      {item.media_url && (
        <a href={item.media_url} target="_blank" rel="noreferrer"
           className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em] text-brand-accent hover:opacity-70 mt-16 pt-8 border-t border-brand-ink/10 w-full">
          View original at {item.source_name} <ExternalLink size={12} />
        </a>
      )}
    </motion.article>
  );
};

const readUrl = (): { itemId: string | null; topic: string | null; admin: boolean } => {
  const p = new URLSearchParams(window.location.search);
  return { itemId: p.get('item'), topic: p.get('topic'), admin: p.get('admin') === '1' };
};

const LoginScreen = ({ onLoggedIn }: { onLoggedIn: (u: User) => void }) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try { onLoggedIn(await apiLogin(email, password)); }
    catch (err) { setError(err instanceof ApiError ? err.detail : String(err)); }
    finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-brand-cream p-6">
      <form onSubmit={submit}
        className="w-full max-w-sm bg-brand-surface/80 backdrop-blur rounded-3xl p-10 shadow-sm border border-brand-ink/10">
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-lg bg-brand-blue flex items-center justify-center text-brand-cream font-display italic font-semibold text-xl">S</div>
          <span className="font-display italic font-light text-brand-ink text-2xl tracking-[-0.02em]">Stroom</span>
        </div>
        <label className="block mb-4">
          <span className="block font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/60 mb-2">E-mail</span>
          <input type="email" autoComplete="username" value={email} onChange={e => setEmail(e.target.value)}
            className="w-full px-4 py-3 rounded-xl border border-brand-ink/10 bg-brand-cream focus:outline-none focus:border-brand-blue text-brand-ink" />
        </label>
        <label className="block mb-6">
          <span className="block font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/60 mb-2">Wachtwoord</span>
          <input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)}
            className="w-full px-4 py-3 rounded-xl border border-brand-ink/10 bg-brand-cream focus:outline-none focus:border-brand-blue text-brand-ink" />
        </label>
        {error && <div className="text-red-600 text-sm mb-4">{error}</div>}
        <button type="submit" disabled={busy}
          className="w-full py-3 rounded-xl bg-brand-blue text-brand-cream font-medium hover:opacity-90 transition disabled:opacity-50 flex items-center justify-center gap-2">
          {busy ? <Loader2 size={16} className="animate-spin" /> : null}
          Inloggen
        </button>
      </form>
    </div>
  );
};


function useDarkMode(): [boolean, () => void] {
  const [dark, setDark] = useState<boolean>(() => localStorage.getItem('stroom-theme') === 'dark');
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    localStorage.setItem('stroom-theme', dark ? 'dark' : 'light');
  }, [dark]);
  return [dark, () => setDark(d => !d)];
}

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    fetchMe().then(setUser).catch(() => setUser(null));
  }, []);

  if (user === undefined) {
    return <div className="min-h-screen flex items-center justify-center text-brand-ink/40 italic">Loading…</div>;
  }
  if (user === null) {
    return <LoginScreen onLoggedIn={setUser} />;
  }
  return <AuthedApp user={user} onLogout={() => { apiLogout().finally(() => setUser(null)); }} />;
}


const DIGEST_MODEL_LABELS: Record<DigestModel, string> = {
  qwen: 'Qwen (lokaal)',
  sonnet: 'Sonnet',
  opus: 'Opus',
};

function DigestPanel({ slug, topicName }: { slug: string; topicName: string }) {
  const [digest, setDigest] = useState<TopicDigest | null | undefined>(undefined);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [model, setModel] = useState<DigestModel>(() =>
    (localStorage.getItem('stroom-digest-model') as DigestModel) || 'opus'
  );

  useEffect(() => {
    setDigest(undefined); setErr(null); setOpen(false);
    fetchTopicDigest(slug).then(setDigest).catch(() => setDigest(null));
  }, [slug]);

  useEffect(() => { localStorage.setItem('stroom-digest-model', model); }, [model]);

  const regen = async () => {
    setBusy(true); setErr(null);
    try {
      const fresh = await regenerateTopicDigest(slug, model);
      setDigest(fresh);
      setOpen(true);
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  };

  const ago = digest ? new Date(digest.generated_at).toLocaleString('nl-NL', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : null;

  return (
    <section className="mb-12 border border-brand-ink/10 rounded-3xl bg-brand-surface/40 p-6">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <Newspaper size={20} className="text-brand-accent" />
          <div>
            <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-brand-accent">Dagdigest · {topicName}</div>
            {digest && (
              <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-brand-ink/50 mt-1">
                {digest.item_count} items · {digest.window_hours}u · {ago}
              </div>
            )}
            {digest === null && (
              <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-brand-ink/50 mt-1">Nog geen digest</div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {digest && (
            <button onClick={() => setOpen(o => !o)}
              className="flex items-center gap-2 px-4 py-2 rounded-full font-mono text-[10px] uppercase tracking-[0.18em] bg-brand-surface hover:bg-brand-surface-low text-brand-ink/70">
              {open ? 'Verberg' : 'Toon'}
            </button>
          )}
          <select value={model} onChange={e => setModel(e.target.value as DigestModel)} disabled={busy}
            className="px-3 py-2 rounded-full font-mono text-[10px] uppercase tracking-[0.18em] bg-brand-surface text-brand-ink/70 border border-brand-ink/10 cursor-pointer disabled:opacity-50">
            {(['qwen', 'sonnet', 'opus'] as DigestModel[]).map(m => (
              <option key={m} value={m}>{DIGEST_MODEL_LABELS[m]}</option>
            ))}
          </select>
          <button onClick={regen} disabled={busy}
            className={`flex items-center gap-2 px-4 py-2 rounded-full font-mono text-[10px] uppercase tracking-[0.18em] transition-all ${
              busy ? 'opacity-50 cursor-wait bg-brand-surface text-brand-ink/60'
                   : 'bg-brand-accent text-brand-cream hover:opacity-90'
            }`}>
            {busy ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            {digest ? 'Ververs' : 'Genereer'}
          </button>
        </div>
      </div>
      {err && <div className="mt-4 text-red-600 text-sm">{err}</div>}
      {open && digest && (
        <div
          className="mt-6 pt-6 border-t border-brand-ink/10 prose-stroom font-serif text-[16px] leading-[1.65] text-brand-ink/85 max-w-none"
          dangerouslySetInnerHTML={{ __html: marked.parse(digest.markdown, { async: false, breaks: true }) as string }}
        />
      )}
    </section>
  );
}

const FILTER_LABELS: Record<ItemFilter, string> = {
  all: 'Alles',
  saved: 'Opgeslagen',
  summarized: 'Met samenvatting',
  scheduled: 'Gepland',
};

const WINDOW_LABELS: Record<ItemWindow, string> = {
  all: 'Altijd',
  '24h': '24 uur',
  '7d': '7 dagen',
  '30d': '30 dagen',
};

function FilterView({ filter, window, topicSlug, topicName, onOpen }: {
  filter: ItemFilter; window: ItemWindow; topicSlug: string; topicName: string;
  onOpen: (id: string) => void;
}) {
  const [items, setItems] = useState<HuygensItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setItems(null); setErr(null);
    fetchFilteredItems({ filter, window, topic: topicSlug })
      .then(setItems).catch(e => setErr(e instanceof ApiError ? e.detail : String(e)));
  }, [filter, window, topicSlug]);
  if (err) return <div className="text-red-600 text-sm py-12">Fout: {err}</div>;
  if (!items) return <div className="text-brand-ink/40 italic py-12">Loading…</div>;
  const subtitle = [
    filter !== 'all' && FILTER_LABELS[filter],
    window !== 'all' && `laatste ${WINDOW_LABELS[window]}`,
  ].filter(Boolean).join(' · ');
  return (
    <>
      <h1 className="font-display text-5xl md:text-7xl text-brand-ink font-medium tracking-[-0.04em] leading-[0.95] mb-3">
        {topicName} <span className="font-mono text-[14px] text-brand-ink/40 align-middle ml-4">{items.length}</span>
      </h1>
      {subtitle && (
        <div className="font-mono text-[11px] uppercase tracking-[0.22em] text-brand-ink/50 mb-12">{subtitle}</div>
      )}
      {items.length === 0 ? (
        <div className="text-brand-ink/40 italic py-12">Geen items in deze view.</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {items.map(it => (
            <button key={it.id} onClick={() => onOpen(it.id)}
              className="text-left p-6 rounded-2xl bg-brand-surface hover:shadow-md transition-all border border-brand-ink/5">
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 mb-3">{it.source_name}</div>
              <h3 className="font-serif font-semibold text-[18px] text-brand-ink leading-[1.25] line-clamp-3">{it.title}</h3>
              {it.published_at && (
                <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/40 mt-3">
                  {new Date(it.published_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}
                </div>
              )}
            </button>
          ))}
        </div>
      )}
    </>
  );
}

function AuthedApp({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [dark, toggleDark] = useDarkMode();
  const [adminMode, setAdminMode] = useState<boolean>(() => readUrl().admin);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [activeSlug, setActiveSlug] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<ItemFilter>('all');
  const [activeWindow, setActiveWindow] = useState<ItemWindow>('all');
  const [data, setData] = useState<HuygensTopic | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [itemId, setItemId] = useState<string | null>(() => readUrl().itemId);

  useEffect(() => {
    const onPop = () => {
      const { itemId, topic, admin } = readUrl();
      setItemId(itemId);
      setAdminMode(admin);
      if (topic) setActiveSlug(topic);
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const openAdmin = () => {
    const url = new URL(window.location.href);
    url.searchParams.set('admin', '1');
    url.searchParams.delete('item');
    window.history.pushState({}, '', url.toString());
    setAdminMode(true);
    setItemId(null);
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
  };

  const closeAdmin = () => {
    const url = new URL(window.location.href);
    url.searchParams.delete('admin');
    window.history.pushState({}, '', url.toString());
    setAdminMode(false);
  };

  const openItem = (id: string) => {
    const url = new URL(window.location.href);
    url.searchParams.set('item', id);
    window.history.pushState({}, '', url.toString());
    setItemId(id);
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
  };

  const closeItem = () => {
    const url = new URL(window.location.href);
    url.searchParams.delete('item');
    window.history.pushState({}, '', url.toString());
    setItemId(null);
  };

  const selectTopic = (slug: string) => {
    setActiveSlug(slug);
    const url = new URL(window.location.href);
    url.searchParams.set('topic', slug);
    url.searchParams.delete('item');
    window.history.replaceState({}, '', url.toString());
  };

  useEffect(() => {
    fetchTopics().then(ts => {
      setTopics(ts);
      const fromUrl = readUrl().topic;
      const first = (fromUrl && ts.find(t => t.slug === fromUrl)) || ts.find(t => t.item_count > 0);
      if (first) setActiveSlug(first.slug);
    }).catch(e => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!activeSlug) return;
    setData(null);
    fetchHuygens(activeSlug).then(setData).catch(e => setError(String(e)));
  }, [activeSlug]);

  return (
    <div className="min-h-screen relative selection:bg-brand-blue selection:text-brand-cream">
      <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden opacity-40">
        <div className="absolute top-[-10%] left-[-10%] w-[60vw] h-[614px] bg-brand-blue/5 rounded-[40%_60%_70%_30%/40%_50%_60%_50%] blur-3xl transform rotate-12" />
        <div className="absolute top-[20%] right-[-20%] w-[70vw] h-[819px] bg-brand-blue/[0.03] rounded-[60%_40%_30%_70%/50%_40%_60%_50%] blur-3xl transform -rotate-12" />
      </div>

      <nav className="sticky top-0 z-40 bg-brand-cream/95 backdrop-blur-md w-full border-b border-brand-ink/10">
        <div className="flex justify-between items-center px-6 md:px-12 py-6 w-full max-w-screen-2xl mx-auto">
          <div className="text-3xl text-brand-ink flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-brand-blue flex items-center justify-center text-brand-cream font-display italic font-semibold text-xl">S</div>
            <span className="pt-1 font-display italic font-light text-brand-ink tracking-[-0.02em]">Stroom <span className="text-brand-ink/40 not-italic font-mono text-base align-middle ml-2 tracking-[0.15em] uppercase">Huygens</span></span>
          </div>
          <div className="flex gap-6 items-center text-brand-ink/40">
            <button className="hover:text-brand-accent transition-colors"><Search size={20} strokeWidth={2.5} /></button>
            <button onClick={toggleDark} title={dark ? 'Lichtmodus' : 'Donkermodus'}
                    className="hover:text-brand-accent transition-colors">
              {dark ? <Sun size={20} strokeWidth={2.5} /> : <Moon size={20} strokeWidth={2.5} />}
            </button>
            <button onClick={openAdmin} title="Sources beheren"
                    className="hover:text-brand-accent transition-colors">
              <Settings size={20} strokeWidth={2.5} />
            </button>
            <button onClick={onLogout} title={`Uitloggen (${user.email})`}
                    className="hover:text-brand-accent transition-colors flex items-center gap-2 text-[12px] font-mono uppercase tracking-[0.15em]">
              <UserIcon size={20} strokeWidth={2.5} />
              <span className="hidden md:inline">Uitloggen</span>
            </button>
          </div>
        </div>
      </nav>

      <main className="relative z-10 w-full max-w-screen-2xl mx-auto px-6 md:px-12 pb-32 pt-10">
        {adminMode ? (
          <AdminPage onBack={closeAdmin} />
        ) : itemId ? (
          <ItemDetailView id={itemId} onBack={closeItem} />
        ) : (
          <>
            <section className="mb-8 space-y-3">
              <div className="flex items-center gap-4 overflow-x-auto hide-scrollbar pb-1">
                <span className="font-mono text-[11px] font-medium text-brand-ink/40 uppercase tracking-[0.22em] mr-6 shrink-0">Topics</span>
                {topics.map(t => (
                  <TopicChip key={t.slug} topic={t} active={t.slug === activeSlug} onClick={() => selectTopic(t.slug)} />
                ))}
              </div>
              <div className="flex items-center gap-3 overflow-x-auto hide-scrollbar pb-1">
                <span className="font-mono text-[11px] font-medium text-brand-ink/40 uppercase tracking-[0.22em] mr-4 shrink-0">Filter</span>
                {(['all', 'saved', 'summarized', 'scheduled'] as ItemFilter[]).map(f => (
                  <button key={f}
                    onClick={() => setActiveFilter(f)}
                    className={`px-4 py-1.5 rounded-full text-[12px] font-medium whitespace-nowrap shrink-0 transition-all ${
                      activeFilter === f ? 'bg-brand-accent text-brand-cream shadow-sm'
                      : 'bg-brand-surface hover:bg-brand-surface-low text-brand-ink/70'
                    }`}
                  >{FILTER_LABELS[f]}</button>
                ))}
                <span className="w-px h-5 bg-brand-ink/10 mx-2 shrink-0" />
                {(['all', '24h', '7d', '30d'] as ItemWindow[]).map(w => (
                  <button key={w}
                    onClick={() => setActiveWindow(w)}
                    className={`px-4 py-1.5 rounded-full text-[12px] font-medium whitespace-nowrap shrink-0 transition-all ${
                      activeWindow === w ? 'bg-brand-accent text-brand-cream shadow-sm'
                      : 'bg-brand-surface hover:bg-brand-surface-low text-brand-ink/70'
                    }`}
                  >{WINDOW_LABELS[w]}</button>
                ))}
              </div>
            </section>

            {error && <div className="text-red-600 text-sm mb-8">Fout: {error}</div>}

            {activeSlug && (activeFilter !== 'all' || activeWindow !== 'all') ? (
              <FilterView
                filter={activeFilter}
                window={activeWindow}
                topicSlug={activeSlug}
                topicName={topics.find(t => t.slug === activeSlug)?.name ?? activeSlug}
                onOpen={openItem}
              />
            ) : data ? (
              <>
                <h1 className="font-display text-6xl md:text-8xl text-brand-ink font-medium tracking-[-0.04em] leading-[0.95] mb-10">{data.name}</h1>
                <DigestPanel slug={data.slug} topicName={data.name} />
                {data.rails.map(rail => <Rail key={rail.format} format={rail.format} items={rail.items} onOpen={openItem} />)}
              </>
            ) : (
              !error && <div className="text-brand-ink/40 italic">Loading…</div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
