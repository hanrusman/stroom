import React, { useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { Search, User as UserIcon, Settings, ArrowRight, PlayCircle, Headphones, FileText, MessageSquare, ArrowLeft, ExternalLink, Bookmark, Clock, Archive, Sparkles, Mic, Loader2, Check, X, CalendarClock, Sun, Moon, Newspaper, RefreshCw, BookOpen, ChevronDown, ChevronUp, Plus, Inbox as InboxIcon } from 'lucide-react';
import { AdminPage } from './AdminPage';
import { SettingsProvider, useSettings } from './settings';
import { GlobalAudioProvider, useGlobalAudio } from './GlobalAudioContext';
import StickyPlayer from './StickyPlayer';
import { InterestLearner } from './InterestLearner';
import { fetchTopics, fetchHuygens, fetchItem, setItemStatus, summarizeItem, transcribeItem,
         scheduleItem, fetchLessons, rateLesson, fetchAllLessons, fetchFilteredItems,
         fetchTopicDigest, regenerateTopicDigest, fetchTopicDigestHistory, TopicDigestRun,
         distillMoreLessons, expandLesson, fetchLessonsDigest, regenerateLessonsDigest,
         askItem, fetchItemQuestions, deleteQuestion, AskAnswer,
         fetchMe, login as apiLogin, logout as apiLogout, ApiError,
         submitToInbox, fetchInboxMetadata, fetchInboxTopics,
         addItemToTopic, removeItemTopic, updateItemQualityScore, sendLessonToVikunja,
         Topic, HuygensTopic, HuygensItem, ItemDetail, ItemFormat, ItemStatus, User, Lesson, ItemFilter, ItemWindow, TopicDigest, DigestModel, DigestWindow,
         LessonsDigest, LessonsDigestFilter, QualityScoreUpdate } from './api';

const RAIL_META: Record<ItemFormat, { label: string; icon: React.ComponentType<{ size?: number }> }> = {
  article: { label: 'Articles',   icon: FileText },
  podcast: { label: 'Podcasts',   icon: Headphones },
  video:   { label: 'Videos',     icon: PlayCircle },
  short:   { label: 'Short-form', icon: MessageSquare },
};

const stripHtml = (s: string | null) =>
  (s ?? '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();

// Security: sanitize markdown output before rendering with dangerouslySetInnerHTML
const sanitizeMarkdown = (content: string | null | undefined, options?: { async?: boolean; breaks?: boolean }): string => {
  if (!content) return '';
  const html = marked.parse(content, { async: false, breaks: options?.breaks ?? true }) as string;
  return DOMPurify.sanitize(html, { ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'blockquote', 'code', 'pre', 'span'], ALLOWED_ATTR: ['href', 'target', 'class'] });
};

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

// Gedeelde score-color helper
const scoreColorClass = (s: number | null | undefined) =>
  !s ? '' : s >= 8 ? 'text-green-600' : s >= 6 ? 'text-amber-600' : 'text-rose-600';

const Meta = ({ item }: { item: HuygensItem }) => {
  const score = item.quality_score;
  const scoreColor = scoreColorClass(score);
  return (
    <div className="text-brand-ink/40 mt-3 text-[10px] font-mono uppercase tracking-[0.18em] flex items-center gap-2">
      <span className="font-medium">{item.source_name}</span>
      {item.published_at && (<>
        <span className="opacity-30">·</span>
        <span>{new Date(item.published_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}</span>
      </>)}
      {score ? (<>
        <span className="opacity-30">·</span>
        <span className={`font-bold ${scoreColor}`} title="Kwaliteitsscore (1-10)">{score}/10</span>
      </>) : null}
    </div>
  );
};

const QualityScoreEditor = ({ itemId, score, onUpdate, title, summary }: { itemId: string; score: number | null; onUpdate: (s: number | null) => void; title?: string; summary?: string }) => {
  const [isEditing, setIsEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [newScore, setNewScore] = useState<number | null>(score);
  const [reason, setReason] = useState<string>('personal_interest');
  const [note, setNote] = useState<string>('');
  const [showInterestLearner, setShowInterestLearner] = useState(false);

  const scoreColor = scoreColorClass(score) || 'text-brand-ink/40';

  const reasonLabels: Record<string, string> = {
    'wrong_topic': 'Verkeerd onderwerp',
    'too_many_ads': 'Te veel reclame',
    'low_quality': 'Lage kwaliteit',
    'high_quality': 'Hoge kwaliteit (moet hoger)',
    'personal_interest': 'Persoonlijke interesse',
    'not_interesting': 'Niet interessant',
    'other': 'Anders',
  };

  const handleSave = async () => {
    setBusy(true);
    try {
      const updated = await updateItemQualityScore(itemId, {
        quality_score: newScore,
        reason: reason as any,
        note: note || undefined,
      });
      onUpdate(updated.quality_score);
      setIsEditing(false);
    } catch (e) {
      console.error('Failed to update quality score:', e);
    } finally {
      setBusy(false);
    }
  };

  const handleCancel = () => {
    setIsEditing(false);
    setNewScore(score);
    setNote('');
  };

  if (isEditing) {
    return (
      <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6">
          <h3 className="text-lg font-semibold mb-4 text-brand-ink">Kwaliteitsscore aanpassen</h3>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-brand-ink/70 mb-1">Score (1-10)</label>
              <select
                value={newScore ?? ''}
                onChange={(e) => setNewScore(e.target.value === '' ? null : parseInt(e.target.value, 10))}
                className="w-full border border-brand-ink/20 rounded px-3 py-2 text-brand-ink"
              >
                <option value="">— Geen score —</option>
                {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(n => (
                  <option key={n} value={n}>{n}/10</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-brand-ink/70 mb-1">Reden</label>
              <select
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className="w-full border border-brand-ink/20 rounded px-3 py-2 text-brand-ink"
              >
                {Object.entries(reasonLabels).map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
            </div>

            {reason === 'personal_interest' && title && (
              <div className="bg-amber-50 border border-amber-200 rounded p-3">
                <p className="text-sm text-amber-800 mb-2">
                  Ontdek waarom dit item interessant is voor jou
                </p>
                <button
                  onClick={() => setShowInterestLearner(true)}
                  className="text-sm px-3 py-1.5 bg-amber-500 text-white rounded hover:bg-amber-600 transition-colors flex items-center gap-1"
                >
                  <span>Ontdek interesses</span>
                  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
                </button>
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-brand-ink/70 mb-1">Notitie (optioneel)</label>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Waarom deze score?"
                className="w-full border border-brand-ink/20 rounded px-3 py-2 text-brand-ink text-sm"
                rows={3}
              />
            </div>
          </div>

          <div className="flex gap-3 mt-6">
            <button
              onClick={handleCancel}
              disabled={busy}
              className="flex-1 px-4 py-2 border border-brand-ink/20 rounded text-brand-ink hover:bg-brand-surface transition-colors"
            >
              Annuleren
            </button>
            <button
              onClick={handleSave}
              disabled={busy || newScore === null}
              className="flex-1 px-4 py-2 bg-brand-accent text-white rounded hover:opacity-90 transition-colors disabled:opacity-50"
            >
              {busy ? 'Opslaan...' : 'Opslaan'}
            </button>
          </div>
        </div>

        {showInterestLearner && title && (
          <InterestLearner
            itemId={itemId}
            title={title}
            summary={summary}
            onClose={() => setShowInterestLearner(false)}
          />
        )}
      </div>
    );
  }

  return (
    <button
      onClick={() => setIsEditing(true)}
      title="Klik om kwaliteitsscore aan te passen"
      className={`font-bold ${scoreColor} hover:opacity-70 cursor-pointer`}
    >
      {score ? `${score}/10` : '—'}
    </button>
  );
};

type CardAction = 'archived' | 'later' | 'summarize' | 'transcribe';

const IconBtn = ({ icon: Icon, title, active, busy, disabled, onClick }: {
  icon: React.ComponentType<{ size?: number }>; title: string;
  active?: boolean; busy?: boolean; disabled?: boolean;
  onClick: (e: React.MouseEvent) => void;
}) => (
  <button onClick={onClick} disabled={busy || disabled} title={title}
    className={`w-7 h-7 flex items-center justify-center rounded-full transition-all ${
      busy || disabled ? 'opacity-30 cursor-not-allowed' :
      active ? 'bg-brand-accent text-white shadow-sm' :
      'bg-brand-cream/60 hover:bg-brand-cream text-brand-ink/60 hover:text-brand-ink'
    }`}>
    {busy ? <Loader2 size={12} className="animate-spin" /> : <Icon size={12} />}
  </button>
);

const CardActions = ({ item, onUpdate, onArchive }: {
  item: HuygensItem; onUpdate?: (updated: Partial<HuygensItem>) => void; onArchive?: () => void;
}) => {
  const [busy, setBusy] = useState<CardAction | null>(null);

  const run = async (key: CardAction, fn: () => Promise<ItemDetail>, e: React.MouseEvent) => {
    e.stopPropagation(); e.preventDefault();
    if (busy) return;
    setBusy(key);
    try {
      const d = await fn();
      onUpdate?.({
        status: d.status, processing_status: d.processing_status,
        has_summary: !!(d.summary && d.summary.trim()),
        has_transcript: !!(d.transcript && d.transcript.trim()),
        scheduled_for: d.scheduled_for,
      });
      // If archiving, trigger onArchive callback to remove from list
      if (key === 'archived' && d.status === 'archived') {
        onArchive?.();
      }
    } catch {
      // stil — gebruiker ziet dat de status niet flipt
    } finally {
      setBusy(null);
    }
  };

  const isArchived = item.status === 'archived';
  const isLater = item.status === 'later' || !!item.scheduled_for;
  const proc = item.processing_status;
  const isMedia = item.format === 'podcast' || item.format === 'video';
  const transcribing = proc === 'queued' || proc === 'transcribe_queued' || proc === 'transcribing';
  const summarizing = proc === 'summarize_queued' || proc === 'summarizing';

  return (
    <div className="flex items-center gap-1.5 mt-3 pt-3 border-t border-brand-ink/5"
         onClick={e => e.stopPropagation()}>
      <IconBtn icon={Archive} title={isArchived ? 'Uit archief' : 'Archiveer'}
        active={isArchived} busy={busy === 'archived'}
        onClick={e => run('archived', () => setItemStatus(item.id, isArchived ? 'new' : 'archived'), e)} />
      <IconBtn icon={CalendarClock} title={isLater ? 'Niet later' : 'Later lezen'}
        active={isLater} busy={busy === 'later'}
        onClick={e => run('later', () => setItemStatus(item.id, isLater ? 'new' : 'later'), e)} />
      <span className="w-px h-4 bg-brand-ink/10 mx-0.5" />
      <IconBtn icon={Sparkles} title={item.has_summary ? 'Samenvatting bestaat' : 'Samenvatten'}
        active={item.has_summary} busy={busy === 'summarize' || summarizing}
        disabled={item.has_summary || !!busy}
        onClick={e => run('summarize', () => summarizeItem(item.id), e)} />
      {isMedia && (
        <IconBtn icon={Mic}
          title={item.has_transcript ? 'Transcript bestaat' : transcribing ? 'In de queue…' : 'Transcribeer'}
          active={item.has_transcript}
          busy={busy === 'transcribe' || transcribing}
          disabled={!item.media_url || item.has_transcript || transcribing}
          onClick={e => run('transcribe', () => transcribeItem(item.id), e)} />
      )}
    </div>
  );
};

type CardProps = { item: HuygensItem; onOpen: (id: string) => void; onUpdate?: (u: Partial<HuygensItem>) => void; onArchive?: () => void };

const ArticleCard = ({ item, onOpen, onUpdate, onArchive }: { key?: React.Key } & CardProps) => {
  const summary = stripHtml(item.description);
  const img = item.thumbnail_url ?? item.source_image_url;
  return (
    <motion.article
      onClick={() => onOpen(item.id)}
      initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
      className="snap-start shrink-0 w-[85vw] md:w-[340px] h-[480px] rounded-3xl overflow-hidden flex flex-col bg-brand-surface border border-brand-ink/5 hover:shadow-md transition-all cursor-pointer group"
    >
      {img ? (
        <div className="w-full aspect-[16/9] overflow-hidden bg-brand-surface-low shrink-0">
          <img src={img} alt={item.title} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-700 ease-out" />
        </div>
      ) : (
        <div className="w-full h-2 bg-brand-accent/30 shrink-0" />
      )}
      <div className="p-6 flex flex-col flex-1 min-h-0">
        <h3 className="font-serif font-semibold text-[22px] text-brand-ink group-hover:text-brand-accent transition-colors line-clamp-3 leading-[1.2] tracking-[-0.01em] mb-3">
          {item.title}
        </h3>
        <p className="text-brand-ink/70 line-clamp-[5] text-[13px] leading-[1.55] flex-1">{summary}</p>
        <Meta item={item} />
        <CardActions item={item} onUpdate={onUpdate} onArchive={onArchive} />
      </div>
    </motion.article>
  );
};

const MediaCard = ({ item, format, onOpen, onUpdate, onArchive }: { key?: React.Key; format: 'podcast' | 'video' } & CardProps) => {
  const summary = stripHtml(item.description);
  const isVideo = format === 'video';
  const img = item.thumbnail_url ?? item.source_image_url;

  // Podcasts: compact horizontaal — thumbnail links, tekst rechts.
  if (!isVideo) {
    return (
      <motion.article
        onClick={() => onOpen(item.id)}
        initial={{ opacity: 0, y: 10 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
        className="snap-start shrink-0 w-[85vw] md:w-[360px] rounded-2xl overflow-hidden p-3 bg-brand-surface border border-brand-ink/5 hover:shadow-sm transition-all cursor-pointer group"
      >
        <div className="flex gap-3">
          <div className="w-24 h-24 shrink-0 rounded-xl overflow-hidden bg-brand-surface-low">
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
        </div>
        <CardActions item={item} onUpdate={onUpdate} onArchive={onArchive} />
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
        <CardActions item={item} onUpdate={onUpdate} onArchive={onArchive} />
      </div>
    </motion.article>
  );
};

const ShortCard = ({ item, onOpen, onUpdate, onArchive }: { key?: React.Key } & CardProps) => {
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
      <CardActions item={item} onUpdate={onUpdate} onArchive={onArchive} />
    </motion.article>
  );
};

const ItemCard = ({ item, format, onOpen, onUpdate, onArchive }: { key?: React.Key; format: ItemFormat } & CardProps) => {
  if (format === 'article') return <ArticleCard item={item} onOpen={onOpen} onUpdate={onUpdate} onArchive={onArchive} />;
  if (format === 'short')   return <ShortCard item={item} onOpen={onOpen} onUpdate={onUpdate} onArchive={onArchive} />;
  return <MediaCard item={item} format={format} onOpen={onOpen} onUpdate={onUpdate} onArchive={onArchive} />;
};

const Rail = ({ format, items, onOpen, onUpdate, onArchiveAll, onArchiveItem }: {
  key?: React.Key; format: ItemFormat; items: HuygensItem[];
  onOpen: (id: string) => void;
  onUpdate?: (id: string, u: Partial<HuygensItem>) => void;
  onArchiveAll?: (format: ItemFormat) => Promise<void>;
  onArchiveItem?: (id: string) => void;
}) => {
  const meta = RAIL_META[format];
  const Icon = meta.icon;
  const [archiving, setArchiving] = useState(false);
  const onArchive = async () => {
    if (!onArchiveAll || archiving || items.length === 0) return;
    if (!confirm(`Archiveer alle ${items.length} ${meta.label.toLowerCase()} en laad nieuwe?`)) return;
    setArchiving(true);
    try { await onArchiveAll(format); } finally { setArchiving(false); }
  };
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
          {items.map(item => <ItemCard key={item.id} item={item} format={format} onOpen={onOpen}
            onUpdate={u => onUpdate?.(item.id, u)} onArchive={() => onArchiveItem?.(item.id)} />)}
          {onArchiveAll && (
            <button onClick={onArchive} disabled={archiving}
              className="snap-start shrink-0 w-[260px] rounded-3xl border border-dashed border-brand-ink/20 bg-brand-surface/40 hover:bg-brand-accent hover:text-brand-cream hover:border-brand-accent text-brand-ink/60 transition flex flex-col items-center justify-center gap-3 p-6 disabled:opacity-50 disabled:cursor-wait">
              {archiving ? <Loader2 size={20} className="animate-spin" /> : <Archive size={20} />}
              <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-center leading-relaxed">
                {archiving ? 'Archiveren…' : <>Archiveer alle<br/>en laad nieuwe</>}
              </span>
            </button>
          )}
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

const QuietAction = ({ icon: Icon, label, active, busy, onClick, disabled }: {
  icon: React.ComponentType<{ size?: number }>; label: string;
  active?: boolean; busy?: boolean; disabled?: boolean; onClick: () => void;
}) => (
  <button
    onClick={onClick} disabled={busy || disabled}
    title={label}
    className={`group flex items-center gap-2 px-3 py-2 rounded-full transition-all ${
      busy || disabled ? 'opacity-40 cursor-not-allowed' :
      active ? 'text-brand-accent bg-brand-accent/5' :
      'text-brand-ink/55 hover:text-brand-accent hover:bg-brand-surface'
    }`}
  >
    {busy ? <Loader2 size={12} className="animate-spin" /> : <Icon size={12} />}
    <span className="font-mono text-[10px] uppercase tracking-[0.2em] hidden sm:inline">{label}</span>
  </button>
);

const LessonExpansion = ({ lesson, onUpdate, showSource }: {
  lesson: Lesson; onUpdate: (l: Lesson) => void; showSource?: boolean;
}) => {
  const [open, setOpen] = useState<boolean>(false);
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const { getDefault } = useSettings();
  const hasExpansion = !!lesson.expansion;

  const onClick = async () => {
    if (hasExpansion) { setOpen(o => !o); return; }
    setBusy(true); setError(null);
    try {
      const updated = await expandLesson(lesson.id, getDefault('expand'));
      onUpdate(updated);
      setOpen(true);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="mt-2">
      <button
        onClick={onClick}
        disabled={busy}
        className="font-mono text-[10px] uppercase tracking-[0.15em] text-brand-ink/50 hover:text-brand-accent inline-flex items-center gap-1.5 disabled:opacity-50"
      >
        {busy ? <Loader2 size={11} className="animate-spin" /> :
         hasExpansion ? (open ? <ChevronUp size={11} /> : <ChevronDown size={11} />) :
         <Sparkles size={11} />}
        {busy ? 'Verdiept…' : hasExpansion ? (open ? 'Inklappen' : 'Verdieping tonen') : 'Verdiep deze les'}
      </button>
      {error && <div className="mt-1 text-rose-600 text-[12px]">{error}</div>}
      {open && lesson.expansion && (
        <div className="mt-3 p-4 bg-brand-surface/60 rounded-lg border border-brand-ink/10">
          <div className="font-serif text-[15px] leading-[1.65] text-brand-ink/85 prose prose-sm max-w-none"
            dangerouslySetInnerHTML={{ __html: sanitizeMarkdown(lesson.expansion) }} />
          {showSource && (
            <div className="mt-2 font-mono text-[10px] uppercase tracking-[0.15em] text-brand-ink/40">
              uit: {lesson.source_name} · {lesson.item_title}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const LessonsSection = ({ itemId }: { itemId: string }) => {
  const [lessons, setLessons] = useState<Lesson[] | null>(null);
  const [distilling, setDistilling] = useState(false);
  const [distillError, setDistillError] = useState<string | null>(null);
  const [sendingToVikunja, setSendingToVikunja] = useState<Set<string>>(new Set());
  const { getDefault } = useSettings();
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

  const sendToVikunja = async (lid: string) => {
    setSendingToVikunja(prev => new Set(prev).add(lid));
    try {
      const result = await sendLessonToVikunja(lid);
      if (result.success && result.task_id) {
        setLessons(prev => prev?.map(l => l.id === lid ? { ...l, vikunja_task_id: result.task_id } : l) ?? prev);
      }
    } catch (e) {
      console.error('Failed to send to Vikunja:', e);
    } finally {
      setSendingToVikunja(prev => {
        const next = new Set(prev);
        next.delete(lid);
        return next;
      });
    }
  };

  const onUpdateLesson = (updated: Lesson) =>
    setLessons(prev => prev?.map(l => l.id === updated.id ? updated : l) ?? prev);

  const onDistill = async () => {
    setDistilling(true); setDistillError(null);
    try {
      const updated = await distillMoreLessons(itemId, getDefault('distill'));
      const prevCount = lessons?.length ?? 0;
      setLessons(updated);
      if (updated.length === prevCount) setDistillError('Geen nieuwe lessen gevonden — alles stond er al.');
    } catch (e) { setDistillError(String(e)); }
    finally { setDistilling(false); }
  };

  if (!lessons) return null;
  if (lessons.length === 0) {
    return (
      <details open className="mb-8 border-t border-brand-ink/10 pt-6">
        <summary className="font-mono text-[11px] uppercase tracking-[0.18em] text-brand-accent cursor-pointer">
          Kernlessen
        </summary>
        <div className="mt-4">
          <button onClick={onDistill} disabled={distilling}
            className="px-3 py-1.5 rounded-full font-mono text-[10px] uppercase tracking-[0.18em] bg-brand-accent text-white hover:opacity-90 inline-flex items-center gap-2 disabled:opacity-50">
            {distilling ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
            Destilleer kernlessen
          </button>
          {distillError && <div className="mt-2 text-rose-600 text-[12px]">{distillError}</div>}
        </div>
      </details>
    );
  }
  return (
    <details open className="mb-8 border-t border-brand-ink/10 pt-6">
      <summary className="font-mono text-[11px] uppercase tracking-[0.18em] text-brand-accent cursor-pointer flex items-center justify-between gap-3">
        <span>Kernlessen · {lessons.length}</span>
        <span
          role="button" tabIndex={0}
          onClick={(e) => { e.preventDefault(); onDistill(); }}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); onDistill(); }}}
          aria-disabled={distilling}
          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-brand-surface text-brand-ink/70 hover:bg-brand-accent hover:text-white transition-all ${distilling ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
          title="Destilleer meer lessen uit de bron"
        >
          {distilling ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
          Meer
        </span>
      </summary>
      {distillError && <div className="mt-2 text-rose-600 text-[12px]">{distillError}</div>}
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
              <button
                onClick={() => sendToVikunja(l.id)}
                disabled={sendingToVikunja.has(l.id) || !!l.vikunja_task_id}
                title={l.vikunja_task_id ? 'Verstuurd naar Vikunja' : 'Verstuur naar Vikunja inbox'}
                className={`w-7 h-7 flex items-center justify-center rounded-full transition-all ${
                  l.vikunja_task_id ? 'bg-blue-500 text-white cursor-default' : 'bg-brand-surface text-brand-ink/40 hover:text-blue-600 hover:bg-blue-50'
                } ${sendingToVikunja.has(l.id) ? 'opacity-50' : ''}`}
              >
                {sendingToVikunja.has(l.id) ? <Loader2 size={14} className="animate-spin" /> : l.vikunja_task_id ? <Check size={14} /> : <InboxIcon size={14} />}
              </button>
            </div>
            <div className={`flex-1 ${l.rating === -1 ? 'opacity-40' : ''}`}>
              <div className="font-serif font-semibold text-[17px] text-brand-ink mb-1">{l.title}</div>
              <div className="font-serif text-[16px] leading-[1.55] text-brand-ink/80">{l.body}</div>
              <LessonExpansion lesson={l} onUpdate={onUpdateLesson} />
              <div className="mt-1.5 font-mono text-[10px] uppercase tracking-[0.15em] text-brand-ink/40 flex items-center gap-2 flex-wrap">
                <span>uit: {l.source_name} · {l.item_title}</span>
                {l.media_url && (
                  <a href={l.media_url} target="_blank" rel="noreferrer"
                    className="text-brand-accent hover:underline inline-flex items-center gap-1">
                    <ExternalLink size={10} /> bron
                  </a>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </details>
  );
};

type SummaryBlock =
  | { kind: 'p'; text: string }
  | { kind: 'h'; lead: string; body: string }
  | { kind: 'ul'; items: { term?: string; body: string }[] };

const parseSummary = (summary: string): SummaryBlock[] => {
  const blocks: SummaryBlock[] = [];
  const paragraphs = summary.split(/\n\s*\n/);
  for (const para of paragraphs) {
    const lines = para.split('\n').map(l => l.trimEnd()).filter(Boolean);
    let buffered: string[] = [];
    let bullets: { term?: string; body: string }[] = [];
    const flushBuffer = () => {
      if (!buffered.length) return;
      const joined = buffered.join(' ');
      const m = joined.match(/^\*\*([^*]+)\*\*\s*(.*)$/);
      if (m) blocks.push({ kind: 'h', lead: m[1], body: m[2] });
      else blocks.push({ kind: 'p', text: joined });
      buffered = [];
    };
    const flushBullets = () => {
      if (!bullets.length) return;
      blocks.push({ kind: 'ul', items: bullets });
      bullets = [];
    };
    for (const line of lines) {
      const bm = line.match(/^[-*]\s+(.*)$/);
      if (bm) {
        flushBuffer();
        const inner = bm[1];
        const tm = inner.match(/^\*\*([^*]+)\*\*\s*[—–-]?\s*(.*)$/);
        if (tm) bullets.push({ term: tm[1], body: tm[2] });
        else bullets.push({ body: inner });
      } else {
        flushBullets();
        buffered.push(line);
      }
    }
    flushBuffer();
    flushBullets();
  }
  return blocks;
};

const renderInline = (text: string): React.ReactNode[] => {
  const out: React.ReactNode[] = [];
  let i = 0; let key = 0;
  while (i < text.length) {
    if (text.startsWith('**', i)) {
      const end = text.indexOf('**', i + 2);
      if (end !== -1) {
        out.push(<strong key={key++} className="font-semibold">{text.slice(i + 2, end)}</strong>);
        i = end + 2; continue;
      }
    }
    if (text[i] === '*') {
      const end = text.indexOf('*', i + 1);
      if (end !== -1) {
        out.push(<em key={key++} className="italic">{text.slice(i + 1, end)}</em>);
        i = end + 1; continue;
      }
    }
    let next = text.length;
    const a = text.indexOf('**', i);
    const b = text.indexOf('*', i);
    if (a !== -1) next = Math.min(next, a);
    if (b !== -1) next = Math.min(next, b);
    out.push(text.slice(i, next));
    i = next;
  }
  return out;
};

const initials = (name: string): string =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '·';

const firstParagraph = (item: ItemDetail): string | null => {
  if (item.summary) {
    const blocks = parseSummary(item.summary);
    const first = blocks.find(b => b.kind === 'h' || b.kind === 'p');
    if (first?.kind === 'h') return first.body || first.lead;
    if (first?.kind === 'p') return first.text;
  }
  if (item.transcript && item.format === 'article') {
    const para = item.transcript.split(/\n\s*\n/).find(p => p.trim().length > 40);
    if (para) return stripHtml(para).slice(0, 300);
  }
  if (item.description) {
    const para = stripHtml(item.description);
    if (para.length > 40) return para.slice(0, 300);
  }
  return null;
};

const ArticleBody = ({ item }: { item: ItemDetail }) => {
  const hero = item.thumbnail_url ?? item.source_image_url;
  const html = item.format === 'article' && item.transcript
    ? sanitizeMarkdown(item.transcript)
    : DOMPurify.sanitize(item.description ?? '');
  const excerpt = firstParagraph(item);
  return (
    <div className="max-w-[680px] mx-auto">
      {hero && (
        <div className={`rounded-3xl overflow-hidden mb-10 bg-brand-surface ${item.format === 'video' ? 'aspect-video' : item.format === 'podcast' ? 'aspect-square max-w-sm mx-auto' : 'aspect-[16/9]'}`}>
          <img src={hero} alt={item.title} className="w-full h-full object-cover" />
        </div>
      )}
      {excerpt && (
        <blockquote className="border-l-2 border-brand-accent/40 pl-6 mb-10 font-serif italic text-[20px] leading-[1.5] text-brand-ink/75">
          {excerpt}
        </blockquote>
      )}
      {!html ? (
        <div className="text-brand-ink/40 italic text-center py-8">Geen tekst beschikbaar.</div>
      ) : (
        <div className="prose-stroom font-serif text-[19px] leading-[1.75] text-brand-ink/85 max-w-none"
             dangerouslySetInnerHTML={{ __html: html }} />
      )}
    </div>
  );
};

const SummaryTab = ({ item, onSummarize, busy }: {
  item: ItemDetail; onSummarize: () => void; busy: boolean;
}) => {
  if (!item.summary) {
    return (
      <div className="text-center py-8">
        {busy ? (
          <>
            <Loader2 size={20} className="animate-spin text-brand-accent mx-auto mb-3" />
            <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-brand-accent">Bezig met samenvatten…</div>
            <div className="font-serif text-[13px] text-brand-ink/55 mt-2 leading-[1.55]">Dit kan even duren — het model leest de hele bron.</div>
          </>
        ) : (
          <>
            <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-brand-ink/40 mb-4">Nog geen samenvatting</div>
            <button onClick={onSummarize} disabled={!(item.transcript || item.description)}
              className="px-4 py-2 rounded-full bg-brand-accent text-brand-cream font-mono text-[10px] uppercase tracking-[0.18em] inline-flex items-center gap-2 disabled:opacity-50">
              <Sparkles size={11} />
              Samenvatten
            </button>
          </>
        )}
      </div>
    );
  }
  return (
    <>
      <div className="flex items-center justify-end mb-3">
        <button onClick={onSummarize} disabled={busy || !(item.transcript || item.description)}
          title="Hersamenvatten"
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-brand-surface hover:bg-brand-accent hover:text-brand-cream font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/55 transition disabled:opacity-50">
          {busy ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
          {busy ? 'Bezig…' : 'Hersamenvatten'}
        </button>
      </div>
      <div
        className="prose-stroom font-serif text-[15px] leading-[1.6] text-brand-ink/85 max-w-none"
        dangerouslySetInnerHTML={{ __html: sanitizeMarkdown(item.summary) }}
      />
    </>
  );
};

const isoWeek = (d: Date): number => {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dayNum = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil((((+t - +yearStart) / 86400000) + 1) / 7);
};

const fmtTime = (s: number): string => {
  if (!isFinite(s) || s < 0) return '0:00';
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, '0')}`;
};

const youtubeId = (url: string | null): string | null => {
  if (!url) return null;
  const m = url.match(/(?:youtube\.com\/(?:v|embed|watch\?v=)\/?|youtu\.be\/)([\w-]{11})/);
  return m ? m[1] : null;
};

const MediaBody = ({ item, onTranscribe, busy, transcribeLabel, transcribeDisabled }: {
  item: ItemDetail; onTranscribe: () => void; busy: boolean;
  transcribeLabel: string; transcribeDisabled: boolean;
}) => {
  const mediaRef = useRef<HTMLMediaElement | null>(null);
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1.7);
  const { loadTrack, currentTrack, isPlaying: globalIsPlaying, currentTime: globalCurrentTime, duration: globalDuration, playbackRate: globalPlaybackRate, togglePlay, seek, skip, setPlaybackRate } = useGlobalAudio();
  const isPinned = currentTrack?.itemId === item.id;

  useEffect(() => { setCur(0); setDur(0); setPlaying(false); setRate(1.7); }, [item.id]);

  // Sync local rate with global when pinned
  useEffect(() => {
    if (isPinned) {
      setRate(globalPlaybackRate);
    }
  }, [isPinned, globalPlaybackRate]);

  const onTime = () => { if (mediaRef.current) setCur(mediaRef.current.currentTime); };
  const onMeta = () => { if (mediaRef.current) setDur(mediaRef.current.duration); };

  const toggle = () => {
    if (isPinned) {
      togglePlay();
    } else {
      const m = mediaRef.current; if (!m) return;
      if (m.paused) m.play(); else m.pause();
    }
  };
  const seekDelta = (d: number) => {
    if (isPinned) {
      skip(d);
    } else {
      const m = mediaRef.current; if (!m) return;
      m.currentTime = Math.max(0, Math.min(dur || m.duration || 0, m.currentTime + d));
    }
  };
  const seekTo = (e: React.MouseEvent<HTMLDivElement>) => {
    const totalDur = isPinned ? globalDuration : dur;
    if (!totalDur) return;
    const r = e.currentTarget.getBoundingClientRect();
    const newTime = ((e.clientX - r.left) / r.width) * totalDur;
    if (isPinned) {
      seek(newTime);
    } else {
      const m = mediaRef.current; if (!m) return;
      m.currentTime = newTime;
    }
  };
  const cycleRate = () => {
    const next = rate >= 2.5 ? 1.0 : Math.round((rate + 0.1) * 10) / 10;
    setRate(next);
    if (isPinned) {
      setPlaybackRate(next);
    } else if (mediaRef.current) {
      mediaRef.current.playbackRate = next;
    }
  };

  const transcript = item.transcript;
  const segments = item.transcript_segments ?? null;
  // Use global state when pinned, local state otherwise
  const displayCur = isPinned ? globalCurrentTime : cur;
  const displayDur = isPinned ? globalDuration : dur;
  const displayPlaying = isPinned ? globalIsPlaying : playing;
  const displayRate = isPinned ? globalPlaybackRate : rate;
  const pct = displayDur > 0 ? (displayCur / displayDur) * 100 : 0;
  const remaining = Math.max(0, displayDur - displayCur);
  const isVideo = item.format === 'video';
  const ytId = isVideo ? youtubeId(item.media_url) : null;

  const seekToSec = (s: number) => {
    if (isPinned) {
      seek(Math.max(0, s));
    } else {
      const m = mediaRef.current;
      if (!m) return;
      m.currentTime = Math.max(0, s);
      if (m.paused) m.play().catch(() => {});
    }
  };
  const activeIdx = segments
    ? segments.findIndex(s => displayCur >= s.start && displayCur < s.end)
    : -1;
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (activeIdx < 0 || !transcriptRef.current) return;
    const el = transcriptRef.current.querySelector<HTMLButtonElement>(`[data-seg-idx="${activeIdx}"]`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [activeIdx]);

  return (
    <>
      {/* Player */}
      <div className="rounded-3xl bg-brand-surface overflow-hidden mb-10">
        {ytId ? (
          <div className="aspect-video bg-brand-ink">
            <iframe
              src={`https://www.youtube.com/embed/${ytId}`}
              title={item.title}
              className="w-full h-full"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowFullScreen
            />
          </div>
        ) : isVideo && item.media_url ? (
          <video ref={mediaRef as React.Ref<HTMLVideoElement>} src={item.media_url}
            onTimeUpdate={onTime} onLoadedMetadata={onMeta}
            onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
            controls
            className="w-full bg-brand-ink aspect-video" />
        ) : item.thumbnail_url ? (
          <div className="aspect-[16/9] overflow-hidden bg-brand-ink">
            <img src={item.thumbnail_url} alt="" className="w-full h-full object-cover" />
          </div>
        ) : null}
        {/* Inline audio alleen renderen als niet gepinned */}
        {!isVideo && item.media_url && !isPinned && (
          <audio ref={mediaRef as React.Ref<HTMLAudioElement>} src={item.media_url}
            onTimeUpdate={onTime} onLoadedMetadata={onMeta}
            onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} />
        )}

        {!isVideo && item.media_url && (
          <div className="p-5 md:p-6">
            <div className="mb-3">
              <div onClick={seekTo}
                className="h-1 bg-brand-ink/10 rounded-full overflow-hidden cursor-pointer">
                <div className="h-full bg-brand-accent" style={{ width: `${pct}%` }} />
              </div>
              <div className="flex justify-between mt-2 font-mono text-[10px] tracking-[0.1em] text-brand-ink/50">
                <span>{fmtTime(displayCur)}</span>
                <span>−{fmtTime(remaining)}</span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <button onClick={() => seekDelta(-15)} className="w-10 h-10 rounded-full hover:bg-brand-ink/5 flex items-center justify-center text-brand-ink/65 font-mono text-[11px]">−15</button>
              <button onClick={toggle}
                className="w-14 h-14 rounded-full bg-brand-accent text-brand-cream flex items-center justify-center text-xl shadow-sm hover:opacity-90">
                {displayPlaying ? '❚❚' : '▶'}
              </button>
              <button onClick={() => seekDelta(30)} className="w-10 h-10 rounded-full hover:bg-brand-ink/5 flex items-center justify-center text-brand-ink/65 font-mono text-[11px]">+30</button>
              <button onClick={cycleRate} className="w-10 h-10 rounded-full hover:bg-brand-ink/5 flex items-center justify-center font-mono text-[10px] text-brand-ink/65">{displayRate.toFixed(1)}×</button>
            </div>
            <button
              onClick={() => {
                loadTrack({
                  itemId: item.id,
                  title: item.title,
                  sourceName: item.source_name,
                  mediaUrl: item.media_url,
                  format: item.format === 'podcast' ? 'podcast' : 'video',
                  thumbnailUrl: item.thumbnail_url || undefined,
                }, cur); // Pin vanaf huidige positie
              }}
              disabled={isPinned}
              className={`mt-4 w-full py-2.5 rounded-full font-mono text-[11px] uppercase tracking-[0.15em] flex items-center justify-center gap-2 transition ${
                isPinned
                  ? 'bg-brand-accent text-brand-cream cursor-default'
                  : 'bg-brand-surface hover:bg-brand-accent hover:text-brand-cream text-brand-ink/70'
              }`}
            >
              {isPinned ? (
                <>Vastgezet aan speler</>
              ) : (
                <>Vastzetten aan speler</>
              )}
            </button>
          </div>
        )}
        {!item.media_url && (
          <div className="p-6 text-center text-brand-ink/45 font-mono text-[10px] uppercase tracking-[0.18em]">
            Geen media-URL
          </div>
        )}
      </div>

      {/* Transcript */}
      <div>
        <div className="flex items-center justify-between mb-6 pb-4 border-b border-brand-ink/10 flex-wrap gap-2">
          <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-brand-accent font-medium">◉ Transcript</span>
          {segments && <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/40">{segments.length} segments · klik tijd om te springen</span>}
          {!segments && transcript && <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/40">{transcript.length} chars</span>}
        </div>
        {segments && segments.length > 0 ? (
          <div ref={transcriptRef} className="space-y-3">
            {segments.map((seg, i) => {
              const active = i === activeIdx;
              return (
                <button key={i} onClick={() => seekToSec(seg.start)}
                  data-seg-idx={i}
                  className={`block w-full text-left rounded-2xl p-4 transition ${
                    active ? 'bg-brand-accent/5 ring-1 ring-brand-accent/30' : 'hover:bg-brand-surface/60'
                  }`}>
                  <div className="flex items-baseline gap-3 mb-1">
                    <span className={`font-mono text-[10px] tracking-[0.1em] ${active ? 'text-brand-accent font-semibold' : 'text-brand-ink/45'}`}>
                      {fmtTime(seg.start)}
                    </span>
                    {seg.speaker && (
                      <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/55 font-medium">{seg.speaker}</span>
                    )}
                  </div>
                  <div className={`font-serif text-[16px] leading-[1.65] whitespace-pre-wrap ${active ? 'text-brand-ink' : 'text-brand-ink/80'}`}>{seg.text}</div>
                </button>
              );
            })}
          </div>
        ) : transcript ? (
          <div className="space-y-5">
            {transcript.split(/\n\n+/).filter(p => p.trim()).map((para, i) => (
              <p key={i} className="font-serif text-[17px] leading-[1.7] text-brand-ink/85 whitespace-pre-wrap">{para}</p>
            ))}
          </div>
        ) : (
          <div className="py-8 text-center">
            <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-brand-ink/40 mb-4">Nog geen transcript</div>
            <button onClick={onTranscribe} disabled={busy || transcribeDisabled}
              className="px-4 py-2.5 rounded-full bg-brand-accent text-brand-cream font-mono text-[11px] uppercase tracking-[0.18em] inline-flex items-center gap-2 disabled:opacity-50">
              {busy ? <Loader2 size={12} className="animate-spin" /> : <Mic size={12} />}
              {transcribeLabel}
            </button>
          </div>
        )}
      </div>
    </>
  );
};

const LessonsTab = ({ itemId, lessons, setLessons }: {
  itemId: string;
  lessons: Lesson[] | null;
  setLessons: (updater: (prev: Lesson[] | null) => Lesson[] | null) => void;
}) => {
  const [distilling, setDistilling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sendingToVikunja, setSendingToVikunja] = useState<Set<string>>(new Set());
  const { getDefault } = useSettings();

  const onDistill = async () => {
    setDistilling(true); setError(null);
    try {
      const updated = await distillMoreLessons(itemId, getDefault('distill'));
      setLessons(() => updated);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setDistilling(false);
    }
  };

  const setRating = async (lid: string, r: 1 | -1 | null) => {
    setLessons(prev => prev?.map(l => l.id === lid ? { ...l, rating: r } : l) ?? prev);
    try {
      const updated = await rateLesson(lid, r);
      setLessons(prev => prev?.map(l => l.id === lid ? updated : l) ?? prev);
    } catch {
      fetchLessons(itemId).then(d => setLessons(() => d)).catch(() => {});
    }
  };

  const sendToVikunja = async (lid: string) => {
    setSendingToVikunja(prev => new Set(prev).add(lid));
    try {
      const result = await sendLessonToVikunja(lid);
      if (result.success && result.task_id) {
        setLessons(prev => prev?.map(l => l.id === lid ? { ...l, vikunja_task_id: result.task_id } : l) ?? prev);
      }
    } catch (e) {
      console.error('Failed to send to Vikunja:', e);
    } finally {
      setSendingToVikunja(prev => {
        const next = new Set(prev);
        next.delete(lid);
        return next;
      });
    }
  };

  const onLessonUpdate = (updated: Lesson) =>
    setLessons(prev => prev?.map(l => l.id === updated.id ? updated : l) ?? prev);

  if (lessons === null) return <div className="text-brand-ink/40 italic text-center py-6 text-sm">Laden…</div>;
  if (lessons.length === 0) {
    return (
      <div className="text-center py-8">
        <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-brand-ink/40 mb-4">Nog geen lessen</div>
        <button onClick={onDistill} disabled={distilling}
          className="px-4 py-2 rounded-full bg-brand-accent text-brand-cream font-mono text-[10px] uppercase tracking-[0.18em] inline-flex items-center gap-2 disabled:opacity-50">
          {distilling ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />}
          Destilleer kernlessen
        </button>
        {error && <div className="text-rose-600 text-sm mt-3">{error}</div>}
      </div>
    );
  }

  return (
    <>
      <div className="flex items-center justify-between mb-4 pb-3 border-b border-brand-ink/10">
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/45">{lessons.length} lessen</span>
        <button onClick={onDistill} disabled={distilling}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-brand-surface hover:bg-brand-accent hover:text-brand-cream font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/70 transition disabled:opacity-50">
          {distilling ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
          Meer
        </button>
      </div>
      {error && <div className="text-rose-600 text-xs mb-3">{error}</div>}
    <ul className="space-y-5">
      {lessons.map(l => (
        <li key={l.id} className="group">
          <div className="flex items-start gap-3">
            <div className="flex flex-col gap-1 pt-1 shrink-0">
              <button onClick={() => setRating(l.id, l.rating === 1 ? null : 1)} title="Nuttig"
                className={`w-6 h-6 rounded-full flex items-center justify-center transition ${
                  l.rating === 1 ? 'bg-emerald-500 text-white' : 'bg-brand-surface text-brand-ink/40 hover:text-emerald-600'
                }`}><Check size={11} /></button>
              <button onClick={() => setRating(l.id, l.rating === -1 ? null : -1)} title="Niet nuttig"
                className={`w-6 h-6 rounded-full flex items-center justify-center transition ${
                  l.rating === -1 ? 'bg-rose-500 text-white' : 'bg-brand-surface text-brand-ink/40 hover:text-rose-600'
                }`}><X size={11} /></button>
              <button
                onClick={() => sendToVikunja(l.id)}
                disabled={sendingToVikunja.has(l.id) || !!l.vikunja_task_id}
                title={l.vikunja_task_id ? 'Verstuurd naar Vikunja' : 'Verstuur naar Vikunja inbox'}
                className={`w-6 h-6 rounded-full flex items-center justify-center transition ${
                  l.vikunja_task_id ? 'bg-blue-500 text-white cursor-default' : 'bg-brand-surface text-brand-ink/40 hover:text-blue-600'
                } ${sendingToVikunja.has(l.id) ? 'opacity-50' : ''}`}
              >
                {sendingToVikunja.has(l.id) ? <Loader2 size={11} className="animate-spin" /> : l.vikunja_task_id ? <Check size={11} /> : <InboxIcon size={11} />}
              </button>
            </div>
            <div className={`flex-1 min-w-0 ${l.rating === -1 ? 'opacity-50' : ''}`}>
              <div className="font-serif font-semibold text-[15px] text-brand-ink leading-tight mb-1">{renderInline(l.title)}</div>
              <div className="font-serif text-[14px] leading-[1.55] text-brand-ink/75">{renderInline(l.body)}</div>
              <LessonExpansion lesson={l} onUpdate={onLessonUpdate} />
            </div>
          </div>
        </li>
      ))}
    </ul>
    </>
  );
};

const formatDateTime = (s: string | null | undefined) => {
  if (!s) return '';
  const d = new Date(s);
  return d.toLocaleDateString('nl-NL', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
};

const AskTab = ({ itemId }: { itemId: string }) => {
  const { getDefault } = useSettings();
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [history, setHistory] = useState<AskAnswer[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);

  // Load saved questions on mount
  useEffect(() => {
    setLoadingHistory(true);
    fetchItemQuestions(itemId, 50)
      .then(qs => setHistory(qs.reverse())) // oldest first
      .catch(() => {}) // silent fail
      .finally(() => setLoadingHistory(false));
  }, [itemId]);

  useEffect(() => { setErr(null); setQ(''); }, [itemId]);

  const suggestions = [
    'Wat zijn de kernargumenten?',
    'Welk bewijs draagt de auteur aan?',
    'Wat is hier de tegenovergestelde positie?',
  ];

  const submit = async () => {
    const question = q.trim();
    if (!question || busy) return;
    setBusy(true); setErr(null);
    try {
      const ans = await askItem(itemId, question, getDefault('ask'));
      setHistory(h => [...h, ans]);
      setQ('');
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (idx: number, createdAt?: string) => {
    // Only delete if we have the ID stored (would need backend to return ID)
    // For now, just remove from local state
    setHistory(h => h.filter((_, i) => i !== idx));
  };

  return (
    <div className="space-y-4">
      {loadingHistory && history.length === 0 && (
        <div className="font-serif text-[14px] text-brand-ink/50 italic">Geschiedenis laden…</div>
      )}

      {!loadingHistory && history.length === 0 && (
        <div className="font-serif text-[14px] text-brand-ink/70 leading-relaxed">
          Stel een vraag over dit item. De assistent gebruikt de samenvatting, lessen en eventueel het transcript.
        </div>
      )}

      {history.length > 0 && (
        <div className="space-y-5 max-h-[400px] overflow-y-auto pr-2">
          {history.map((a, i) => (
            <div key={i} className="space-y-2 border-b border-brand-ink/5 pb-4 last:border-0">
              <div className="flex items-center justify-between">
                <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/45">
                  Jij <span className="text-brand-ink/30">· {a.model}</span>
                  {a.created_at && <span className="text-brand-ink/20 ml-2">· {formatDateTime(a.created_at)}</span>}
                </div>
                <button
                  onClick={() => handleDelete(i, a.created_at)}
                  className="text-brand-ink/20 hover:text-rose-500 transition"
                  title="Verwijder vraag"
                >
                  <X size={12} />
                </button>
              </div>
              <div className="font-serif text-[14px] text-brand-ink leading-[1.55]">{a.question}</div>
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-accent mt-3">Antwoord</div>
              <div className="prose-stroom font-serif text-[14px] leading-[1.6] text-brand-ink/85 max-w-none"
                   dangerouslySetInnerHTML={{ __html: sanitizeMarkdown(a.answer) }} />
              {a.sources_used.length > 0 && (
                <div className="font-mono text-[9px] uppercase tracking-[0.18em] text-brand-ink/35">
                  bron: {a.sources_used.join(' · ')}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {history.length === 0 && (
        <div className="space-y-2">
          {suggestions.map(s => (
            <button key={s} onClick={() => setQ(s)} disabled={busy}
              className="w-full text-left px-3 py-2 rounded-lg bg-brand-surface hover:bg-brand-accent hover:text-brand-cream font-serif text-[13px] text-brand-ink/75 transition disabled:opacity-50">
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="relative pt-2">
        <textarea value={q} onChange={e => setQ(e.target.value)} rows={3}
          placeholder="Type je vraag…"
          disabled={busy}
          onKeyDown={e => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') submit(); }}
          className="w-full px-4 py-3 rounded-2xl bg-brand-surface border border-brand-ink/10 font-serif text-[14px] text-brand-ink placeholder:text-brand-ink/30 focus:outline-none focus:border-brand-accent/40 resize-none disabled:opacity-60" />
        <button onClick={submit} disabled={busy || !q.trim()}
          className="absolute bottom-4 right-3 px-4 py-1.5 rounded-full bg-brand-accent text-brand-cream font-mono text-[10px] uppercase tracking-[0.18em] hover:opacity-90 disabled:opacity-50 inline-flex items-center gap-1.5">
          {busy ? <Loader2 size={11} className="animate-spin" /> : null}
          {busy ? 'Bezig…' : 'Vraag →'}
        </button>
      </div>
      {err && <div className="text-rose-600 text-xs">{err}</div>}
      <div className="font-mono text-[9px] uppercase tracking-[0.18em] text-brand-ink/30">
        ⌘↵ verstuurt · model: {getDefault('ask')}
      </div>
    </div>
  );
};

type AITab = 'summary' | 'lessons' | 'transcript' | 'ask';

const PANEL_TABS: { id: AITab; label: string }[] = [
  { id: 'summary',    label: 'Samenvatting' },
  { id: 'lessons',    label: 'Lessen' },
  { id: 'transcript', label: 'Transcript' },
  { id: 'ask',        label: 'Vraag' },
];

const TranscriptTab = ({ item }: { item: ItemDetail }) => {
  if (!item.transcript) {
    return (
      <div className="text-center py-8">
        <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-brand-ink/40 mb-3">Geen transcript</div>
        <div className="font-serif text-[14px] text-brand-ink/65 leading-relaxed">
          Alleen beschikbaar voor podcasts en video&rsquo;s.
        </div>
      </div>
    );
  }
  return (
    <div className="font-serif text-[14px] leading-[1.6] text-brand-ink/80 whitespace-pre-wrap">{item.transcript}</div>
  );
};

const AIPanelTabs = ({ tab, setTab, lessonCount, transcriptDisabled }: {
  tab: AITab; setTab: (t: AITab) => void; lessonCount: number | null; transcriptDisabled: boolean;
}) => (
  <div className="flex gap-1">
    {PANEL_TABS.map(t => {
      const disabled = t.id === 'transcript' && transcriptDisabled;
      return (
        <button key={t.id} onClick={() => !disabled && setTab(t.id)} disabled={disabled}
          className={`relative flex-1 px-2 py-2 rounded-lg font-mono text-[10px] uppercase tracking-[0.16em] transition-all ${
            disabled ? 'text-brand-ink/25 cursor-not-allowed' :
            tab === t.id ? 'bg-brand-accent text-brand-cream' : 'text-brand-ink/55 hover:text-brand-ink hover:bg-brand-surface'
          }`}>
          {t.label}
          {t.id === 'lessons' && lessonCount != null && (
            <span className={`ml-1.5 ${tab === t.id ? 'opacity-60' : 'opacity-40'}`}>{lessonCount}</span>
          )}
        </button>
      );
    })}
  </div>
);

const AIPanelBody = ({ tab, item, lessons, setLessons, onSummarize, summarizeBusy }: {
  tab: AITab; item: ItemDetail; lessons: Lesson[] | null;
  setLessons: (updater: (prev: Lesson[] | null) => Lesson[] | null) => void;
  onSummarize: () => void; summarizeBusy: boolean;
}) => (
  <>
    {tab === 'summary' && <SummaryTab item={item} onSummarize={onSummarize} busy={summarizeBusy} />}
    {tab === 'lessons' && <LessonsTab itemId={item.id} lessons={lessons} setLessons={setLessons} />}
    {tab === 'transcript' && <TranscriptTab item={item} />}
    {tab === 'ask' && <AskTab itemId={item.id} />}
  </>
);

const AIPanel = ({ item, lessons, setLessons, onSummarize, summarizeBusy }: {
  item: ItemDetail; lessons: Lesson[] | null;
  setLessons: (updater: (prev: Lesson[] | null) => Lesson[] | null) => void;
  onSummarize: () => void; summarizeBusy: boolean;
}) => {
  const [tab, setTab] = useState<AITab>('summary');
  return (
    <aside className="hidden lg:block sticky top-24 self-start w-[400px] shrink-0">
      <div className="rounded-3xl bg-brand-cream border border-brand-ink/10 overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-brand-ink/10">
          <div className="flex items-center justify-between mb-4">
            <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-brand-accent font-medium">✦ AI Companion</span>
            {item.summary_model && (
              <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-brand-ink/40">{item.summary_model}</span>
            )}
          </div>
          <AIPanelTabs tab={tab} setTab={setTab} lessonCount={lessons?.length ?? null}
            transcriptDisabled={!item.transcript} />
        </div>
        <div className="p-6 max-h-[calc(100vh-12rem)] overflow-y-auto hide-scrollbar">
          <AIPanelBody tab={tab} item={item} lessons={lessons} setLessons={setLessons}
            onSummarize={onSummarize} summarizeBusy={summarizeBusy} />
        </div>
      </div>
    </aside>
  );
};

const MobileAISections = ({ item, lessons, setLessons, onSummarize, summarizeBusy }: {
  item: ItemDetail; lessons: Lesson[] | null;
  setLessons: (updater: (prev: Lesson[] | null) => Lesson[] | null) => void;
  onSummarize: () => void; summarizeBusy: boolean;
}) => {
  const sections: { id: AITab; label: string; count?: number | null; disabled?: boolean }[] = [
    { id: 'summary', label: 'Samenvatting' },
    { id: 'lessons', label: 'Lessen', count: lessons?.length ?? null },
    { id: 'transcript', label: 'Transcript', disabled: !item.transcript },
    { id: 'ask',     label: 'Vraag' },
  ];
  return (
    <div className="lg:hidden space-y-3 mb-10">
      <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-brand-accent font-medium mb-3 flex items-center gap-2">
        ✦ AI Companion
        {item.summary_model && <span className="text-brand-ink/40">· {item.summary_model}</span>}
      </div>
      {sections.filter(s => !s.disabled).map(s => (
        <details key={s.id} className="group rounded-2xl bg-brand-cream border border-brand-ink/10 overflow-hidden">
          <summary className="cursor-pointer px-5 py-4 flex items-center justify-between font-mono text-[11px] uppercase tracking-[0.18em] text-brand-ink/70 hover:text-brand-ink list-none">
            <span className="flex items-center gap-2">
              {s.label}
              {s.count != null && <span className="text-brand-ink/40">· {s.count}</span>}
            </span>
            <ChevronDown size={14} className="transition-transform group-open:rotate-180" />
          </summary>
          <div className="px-5 pb-5">
            <AIPanelBody tab={s.id} item={item} lessons={lessons} setLessons={setLessons}
              onSummarize={onSummarize} summarizeBusy={summarizeBusy} />
          </div>
        </details>
      ))}
    </div>
  );
};

// Topic Manager Component
function TopicManager({ itemId, currentTopics, onUpdate }: { itemId: string; currentTopics: string[]; onUpdate: (item: ItemDetail) => void }) {
  const [isOpen, setIsOpen] = useState(false);
  const [topics, setTopics] = useState<{ slug: string; name: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    // Load topics immediately on mount
    fetchInboxTopics().then(t => {
      setTopics(t);
      setLoaded(true);
    }).catch(() => {
      setTopics([]);
      setLoaded(true);
    });
  }, []);

  const availableTopics = topics.filter(t => !currentTopics.includes(t.name));

  const addTopic = async (slug: string) => {
    setBusy(true);
    try {
      const updated = await addItemToTopic(itemId, slug);
      onUpdate(updated);
      setIsOpen(false);
    } catch (e) {
      console.error('Failed to add topic:', e);
    } finally {
      setBusy(false);
    }
  };

  // Only hide if we've loaded and there are truly no available topics
  if (loaded && availableTopics.length === 0 && !isOpen) return null;

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="font-mono text-[10px] uppercase tracking-[0.2em] text-brand-accent hover:text-brand-accent/70 flex items-center gap-1"
        title="Toevoegen aan topic"
      >
        <Plus size={12} /> Topic
      </button>
      {isOpen && (
        <div className="absolute left-0 top-full mt-1 z-50 bg-brand-cream border border-brand-ink/10 rounded-lg shadow-lg py-1 min-w-[150px]">
          {availableTopics.length === 0 ? (
            <div className="px-3 py-2 text-[10px] text-brand-ink/40">Alle topics al toegevoegd</div>
          ) : (
            availableTopics.map(t => (
              <button
                key={t.slug}
                onClick={() => !busy && addTopic(t.slug)}
                disabled={busy}
                className="w-full text-left px-3 py-1.5 text-[11px] hover:bg-brand-surface transition-colors"
              >
                {t.name}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

const ItemDetailView = ({ id, onBack }: { id: string; onBack: () => void }) => {
  const [item, setItem] = useState<ItemDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [lessons, setLessons] = useState<Lesson[] | null>(null);

  useEffect(() => {
    setItem(null); setError(null); setLessons(null);
    fetchItem(id).then(setItem).catch(e => setError(String(e)));
    fetchLessons(id).then(setLessons).catch(() => setLessons([]));
  }, [id]);

  useEffect(() => {
    if (!item) return;
    const proc = item.processing_status;
    // Poll while item is in any queue or processing state
    const activeStates = ['queued', 'transcribe_queued', 'summarize_queued', 'transcribing', 'summarizing'];
    if (!activeStates.includes(proc)) return;
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

  const date = item.published_at
    ? new Date(item.published_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'long', year: 'numeric' })
    : null;
  const isMedia = item.format === 'podcast' || item.format === 'video';
  const proc = item.processing_status;

  const hasTranscript = !!(item.transcript && item.transcript.trim());
  const isQueued = proc === 'queued' || proc === 'transcribe_queued' || proc === 'summarize_queued';
  const isTranscribing = proc === 'transcribing';
  const transcribeLabel = hasTranscript ? 'Transcribed'
                        : isQueued ? (item.queue_position ? `Queued #${item.queue_position}` : 'Queued…')
                        : isTranscribing ? 'Transcribing…'
                        : 'Transcribe';
  const summarizeBusy = busy === 'summarize' || proc === 'summarizing' || proc === 'summarize_queued';
  const onSummarize = () => wrap('summarize', () => summarizeItem(id));

  return (
    <motion.article initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
      className="max-w-5xl mx-auto pt-2">
      <div className="flex items-center justify-between gap-4 mb-10 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap min-w-0">
          <button onClick={onBack} title="Back to Flow"
            className="font-mono text-[10px] uppercase tracking-[0.2em] text-brand-ink/45 hover:text-brand-accent flex items-center gap-1.5">
            <ArrowLeft size={12} /> Flow
          </button>
          <span className="text-brand-ink/15">·</span>
          <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-brand-ink/70">
            {FORMAT_BADGE[item.format].label}
          </span>
          {item.topics.map(t => (
            <span key={t} className="font-mono text-[10px] uppercase tracking-[0.2em] text-brand-ink/40">{t}</span>
          ))}
          <TopicManager itemId={id} currentTopics={item.topics} onUpdate={setItem} />
        </div>
        <div className="flex items-center gap-1 flex-wrap">
          <QuietAction icon={Bookmark} label="Save" active={item.status === 'pinned'} busy={busy === 'pinned'} onClick={() => toggle('pinned')} />
          <div className="relative">
            <QuietAction
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
          <QuietAction icon={Archive} label="Archive" active={item.status === 'archived'} busy={busy === 'archived'} onClick={async () => {
            const wasArchived = item.status === 'archived';
            await toggle('archived');
            if (!wasArchived) onBack();
          }} />
        </div>
      </div>

      {error && <div className="bg-red-50 text-red-700 text-sm rounded-2xl px-4 py-3 mb-6">{error}</div>}
      {proc === 'failed' && (
        <div className="bg-amber-50 text-amber-800 text-sm rounded-2xl px-4 py-3 mb-6 font-mono uppercase tracking-[0.15em] text-[11px]">
          Processing failed — check logs
        </div>
      )}

      <div className="lg:flex lg:gap-12 xl:gap-16">
        <article className="flex-1 min-w-0 lg:max-w-[680px]">
          <h1 className="font-display font-medium text-[40px] md:text-[56px] lg:text-[64px] text-brand-ink tracking-[-0.03em] leading-[1.02] mb-8">
            {item.title}
          </h1>
          <div className="flex items-center gap-3 mb-10 pb-6 border-b border-brand-ink/10">
            {item.source_image_url ? (
              <img src={item.source_image_url} alt={item.source_name} className="w-11 h-11 rounded-full object-cover" />
            ) : (
              <div className="w-11 h-11 rounded-full bg-brand-ink/10 flex items-center justify-center font-serif text-brand-ink/45 text-sm">
                {initials(item.author ?? item.source_name)}
              </div>
            )}
            <div>
              <div className="font-serif font-semibold text-[15px] text-brand-ink">{item.author ?? item.source_name}</div>
              <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-brand-ink/50 mt-0.5">
                {item.author && <>{item.source_name} · </>}{date}
                <> · <QualityScoreEditor
                  itemId={item.id}
                  score={item.quality_score}
                  onUpdate={(newScore) => setItem(prev => prev ? { ...prev, quality_score: newScore } : prev)}
                  title={item.title}
                  summary={item.summary}
                /></>
              </div>
            </div>
          </div>

          <MobileAISections item={item} lessons={lessons} setLessons={setLessons}
            onSummarize={onSummarize} summarizeBusy={summarizeBusy} />

          {isMedia ? (
            <MediaBody item={item}
              onTranscribe={() => wrap('transcribe', () => transcribeItem(id))}
              busy={busy === 'transcribe' || isQueued || isTranscribing}
              transcribeLabel={transcribeLabel}
              transcribeDisabled={!item.media_url || hasTranscript || isQueued || isTranscribing} />
          ) : (
            <ArticleBody item={item} />
          )}

          {item.media_url && (
            <a href={item.media_url} target="_blank" rel="noreferrer"
               className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-brand-accent hover:opacity-70 mt-16 pt-8 border-t border-brand-ink/10 w-full">
              View original at {item.source_name} ↗
            </a>
          )}
        </article>
        <AIPanel item={item} lessons={lessons} setLessons={setLessons}
          onSummarize={onSummarize} summarizeBusy={summarizeBusy} />
      </div>
    </motion.article>
  );
};

const readUrl = (): { itemId: string | null; topic: string | null; admin: boolean; lessons: boolean } => {
  const p = new URLSearchParams(window.location.search);
  return {
    itemId: p.get('item'), topic: p.get('topic'),
    admin: p.get('admin') === '1', lessons: p.get('lessons') === '1',
  };
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
          <img src="/logo.png" alt="Stroom" className="w-10 h-10 rounded-lg object-cover" />
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

function AppWithStickyPlayer({ user, onLogout }: { user: User; onLogout: () => void }) {
  const { currentTrack } = useGlobalAudio();
  return (
    <>
      <SettingsProvider>
        <AuthedApp user={user} onLogout={onLogout} />
      </SettingsProvider>
      <StickyPlayer />
      {/* Spacer voor sticky player hoogte */}
      {currentTrack && <div className="h-[76px]" />}
    </>
  );
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
  return (
    <GlobalAudioProvider>
      <AppWithStickyPlayer user={user} onLogout={() => { apiLogout().finally(() => setUser(null)); }} />
    </GlobalAudioProvider>
  );
}

const DIGEST_MODEL_LABELS: Record<DigestModel, string> = {
  qwen: 'Qwen (lokaal)',
  sonnet: 'Sonnet',
  opus: 'Opus',
};

function DigestPanel({ slug, topicName, window: digestWindow }: { slug: string; topicName: string; window: DigestWindow }) {
  const { getDefault } = useSettings();
  const [digest, setDigest] = useState<TopicDigest | null | undefined>(undefined);
  const [history, setHistory] = useState<TopicDigestRun[]>([]);
  const [historyIdx, setHistoryIdx] = useState(0);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [model, setModel] = useState<DigestModel>(() => getDefault('digest'));

  const windowLabel = digestWindow === 'weekly' ? 'Weekdigest' : 'Dagdigest';

  useEffect(() => {
    setDigest(undefined); setErr(null); setOpen(false); setHistoryIdx(0);
    fetchTopicDigest(slug, digestWindow).then(setDigest).catch(() => setDigest(null));
    fetchTopicDigestHistory(slug, digestWindow, 7).then(setHistory).catch(() => setHistory([]));
  }, [slug, digestWindow]);

  useEffect(() => { localStorage.setItem('stroom-model-digest', model); }, [model]);

  useEffect(() => {
    if (!digest?.is_generating) return;
    const t = setInterval(() => {
      fetchTopicDigest(slug, digestWindow).then(d => {
        setDigest(d);
        if (d && !d.is_generating) {
          setBusy(false);
          if (d.error) setErr(d.error);
          else if (d.markdown) setOpen(true);
        }
      }).catch(() => {});
    }, 4000);
    return () => clearInterval(t);
  }, [slug, digestWindow, digest?.is_generating]);

  const regen = async () => {
    setBusy(true); setErr(null);
    try {
      const fresh = await regenerateTopicDigest(slug, model, digestWindow);
      setDigest(fresh);
      if (!fresh.is_generating) {
        setBusy(false);
        if (fresh.error) setErr(fresh.error);
      }
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : String(e));
      setBusy(false);
    }
  };

  const ago = digest?.generated_at ? new Date(digest.generated_at).toLocaleString('nl-NL', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : null;

  return (
    <section className="border border-brand-ink/10 rounded-2xl md:rounded-3xl bg-brand-surface/40 p-4 md:p-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 md:gap-4">
        <div className="flex items-center gap-2 md:gap-3 min-w-0">
          <Newspaper size={18} className="text-brand-accent shrink-0 md:w-5 md:h-5" />
          <div className="min-w-0">
            <div className="font-mono text-[10px] md:text-[11px] uppercase tracking-[0.18em] text-brand-accent truncate">{windowLabel} · {topicName}</div>
            {digest?.is_generating && (
              <div className="font-mono text-[9px] md:text-[10px] uppercase tracking-[0.15em] text-brand-ink/50 mt-1">
                Bezig met genereren…
              </div>
            )}
            {digest && !digest.is_generating && digest.generated_at && (
              <div className="font-mono text-[9px] md:text-[10px] uppercase tracking-[0.15em] text-brand-ink/50 mt-1">
                {digest.item_count} items · {digestWindow === 'weekly' ? `wk ${isoWeek(new Date(digest.generated_at))}` : `${digest.window_hours}u`} · {ago}
              </div>
            )}
            {digest === null && (
              <div className="font-mono text-[9px] md:text-[10px] uppercase tracking-[0.15em] text-brand-ink/50 mt-1">Nog geen digest</div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1 md:gap-2 flex-wrap">
          {digest?.markdown && (
            <button onClick={() => setOpen(o => !o)}
              className="flex items-center gap-1 md:gap-2 px-3 md:px-4 py-1.5 md:py-2 rounded-full font-mono text-[9px] md:text-[10px] uppercase tracking-[0.18em] bg-brand-surface hover:bg-brand-surface-low text-brand-ink/70">
              {open ? 'Verberg' : 'Toon'}
            </button>
          )}
          <select value={model} onChange={e => setModel(e.target.value as DigestModel)} disabled={busy || !!digest?.is_generating}
            className="px-2 md:px-3 py-1.5 md:py-2 rounded-full font-mono text-[9px] md:text-[10px] uppercase tracking-[0.18em] bg-brand-surface text-brand-ink/70 border border-brand-ink/10 cursor-pointer disabled:opacity-50">
            {(['qwen', 'sonnet', 'opus'] as DigestModel[]).map(m => (
              <option key={m} value={m}>{DIGEST_MODEL_LABELS[m]}</option>
            ))}
          </select>
          <button onClick={regen} disabled={busy || !!digest?.is_generating}
            className={`flex items-center gap-1 md:gap-2 px-3 md:px-4 py-1.5 md:py-2 rounded-full font-mono text-[9px] md:text-[10px] uppercase tracking-[0.18em] transition-all ${
              busy || digest?.is_generating ? 'opacity-50 cursor-wait bg-brand-surface text-brand-ink/60'
                   : 'bg-brand-accent text-brand-cream hover:opacity-90'
            }`}>
            {busy || digest?.is_generating ? <Loader2 size={12} className="animate-spin md:w-3.5 md:h-3.5" /> : <RefreshCw size={12} className="md:w-3.5 md:h-3.5" />}
            {digest?.markdown ? 'Ververs' : 'Genereer'}
          </button>
        </div>
      </div>
      {err && <div className="mt-4 text-red-600 text-sm">{err}</div>}
      {!digest?.markdown && !digest?.is_generating && digest && digest.generated_at && (
        <div className="mt-3 font-mono text-[9px] md:text-[10px] uppercase tracking-[0.15em] text-brand-ink/45">
          {digest.error
            ? (digest.error.length > 120 ? digest.error.slice(0, 120) + '…' : digest.error)
            : 'Generatie liep, maar geen output. Probeer opnieuw.'}
        </div>
      )}
      {open && (digest?.markdown || history.length > 0) && (() => {
        const showingHistory = historyIdx > 0 && history[historyIdx];
        const md = showingHistory ? history[historyIdx].markdown : (digest?.markdown ?? '');
        const stamp = showingHistory ? history[historyIdx].generated_at : digest?.generated_at;
        const stampStr = stamp ? new Date(stamp).toLocaleString('nl-NL', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—';
        const wkStr = digestWindow === 'weekly' && stamp ? ` · wk ${isoWeek(new Date(stamp))}` : '';
        return (
          <div className="mt-6 pt-6 border-t border-brand-ink/10">
            {history.length > 1 && (
              <div className="flex items-center justify-between mb-4 font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/55">
                <button onClick={() => setHistoryIdx(i => Math.min(history.length - 1, i + 1))}
                  disabled={historyIdx >= history.length - 1}
                  className="px-3 py-1.5 rounded-full bg-brand-surface hover:bg-brand-surface-low disabled:opacity-30">← ouder</button>
                <span>{historyIdx === 0 ? 'nieuwste' : `${historyIdx + 1} terug`} · {stampStr}{wkStr}</span>
                <button onClick={() => setHistoryIdx(i => Math.max(0, i - 1))}
                  disabled={historyIdx === 0}
                  className="px-3 py-1.5 rounded-full bg-brand-surface hover:bg-brand-surface-low disabled:opacity-30">nieuwer →</button>
              </div>
            )}
            <div
              className="prose-stroom font-serif text-[16px] leading-[1.65] text-brand-ink/85 max-w-none"
              dangerouslySetInnerHTML={{ __html: sanitizeMarkdown(md) }}
            />
          </div>
        );
      })()}
    </section>
  );
}

const FILTER_LABELS: Record<ItemFilter, string> = {
  all: 'Alles',
  saved: 'Opgeslagen',
  summarized: 'Met samenvatting',
  scheduled: 'Gepland',
  archived: 'Archief',
  inbox: 'Inbox',
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
            <div key={it.id} onClick={() => onOpen(it.id)}
              className="text-left p-6 rounded-2xl bg-brand-surface hover:shadow-md transition-all border border-brand-ink/5 cursor-pointer flex flex-col">
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/50 mb-3">{it.source_name}</div>
              <h3 className="font-serif font-semibold text-[18px] text-brand-ink leading-[1.25] line-clamp-3">{it.title}</h3>
              {it.published_at && (
                <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-brand-ink/40 mt-3">
                  {new Date(it.published_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}
                </div>
              )}
              <CardActions item={it} onUpdate={u => setItems(prev => prev?.map(x => x.id === it.id ? { ...x, ...u } : x) ?? prev)} />
            </div>
          ))}
        </div>
      )}
    </>
  );
}

type LessonFilter = 'useful' | 'not-useful' | 'all';

const LESSON_FILTER_LABELS: Record<LessonFilter, string> = {
  useful: 'Nuttig (👍)',
  'not-useful': 'Niet nuttig (👎)',
  all: 'Alles',
};

function LessonsDigestPanel({ window: digestWindow, filter }: { window: DigestWindow; filter: LessonsDigestFilter }) {
  const { getDefault } = useSettings();
  const [digest, setDigest] = useState<LessonsDigest | null | undefined>(undefined);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [model, setModel] = useState<DigestModel>(() => getDefault('digest'));

  const windowLabel = digestWindow === 'weekly' ? 'Weekdigest' : 'Dagdigest';

  useEffect(() => {
    setDigest(undefined); setErr(null); setOpen(false);
    fetchLessonsDigest(digestWindow, filter).then(setDigest).catch(() => setDigest(null));
  }, [digestWindow, filter]);

  useEffect(() => { localStorage.setItem('stroom-model-digest', model); }, [model]);

  useEffect(() => {
    if (!digest?.is_generating) return;
    const t = setInterval(() => {
      fetchLessonsDigest(digestWindow, filter).then(d => {
        setDigest(d);
        if (d && !d.is_generating) {
          setBusy(false);
          if (d.error) setErr(d.error);
          else if (d.markdown) setOpen(true);
        }
      }).catch(() => {});
    }, 4000);
    return () => clearInterval(t);
  }, [digestWindow, filter, digest?.is_generating]);

  const regen = async () => {
    setBusy(true); setErr(null);
    try {
      const fresh = await regenerateLessonsDigest(model, digestWindow, filter);
      setDigest(fresh);
      if (!fresh.is_generating) {
        setBusy(false);
        if (fresh.error) setErr(fresh.error);
      }
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : String(e));
      setBusy(false);
    }
  };

  const ago = digest?.generated_at ? new Date(digest.generated_at).toLocaleString('nl-NL', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : null;

  return (
    <section className="border border-brand-ink/10 rounded-2xl md:rounded-3xl bg-brand-surface/40 p-4 md:p-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 md:gap-4">
        <div className="flex items-center gap-2 md:gap-3 min-w-0">
          <BookOpen size={18} className="text-brand-accent shrink-0 md:w-5 md:h-5" />
          <div className="min-w-0">
            <div className="font-mono text-[10px] md:text-[11px] uppercase tracking-[0.18em] text-brand-accent truncate">{windowLabel} · {LESSON_FILTER_LABELS[filter as LessonFilter]}</div>
            {digest?.is_generating && (
              <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-brand-ink/50 mt-1">Bezig met genereren…</div>
            )}
            {digest && !digest.is_generating && digest.generated_at && (
              <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-brand-ink/50 mt-1">
                {digest.lesson_count} lessen · {digestWindow === 'weekly' ? `wk ${isoWeek(new Date(digest.generated_at))}` : `${digest.window_hours}u`} · {ago}
              </div>
            )}
            {digest === null && (
              <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-brand-ink/50 mt-1">Nog geen digest</div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1 md:gap-2 flex-wrap">
          {digest?.markdown && (
            <button onClick={() => setOpen(o => !o)}
              className="flex items-center gap-1 md:gap-2 px-3 md:px-4 py-1.5 md:py-2 rounded-full font-mono text-[9px] md:text-[10px] uppercase tracking-[0.18em] bg-brand-surface hover:bg-brand-surface-low text-brand-ink/70">
              {open ? 'Verberg' : 'Toon'}
            </button>
          )}
          <select value={model} onChange={e => setModel(e.target.value as DigestModel)} disabled={busy || !!digest?.is_generating}
            className="px-2 md:px-3 py-1.5 md:py-2 rounded-full font-mono text-[9px] md:text-[10px] uppercase tracking-[0.18em] bg-brand-surface text-brand-ink/70 border border-brand-ink/10 cursor-pointer disabled:opacity-50">
            {(['qwen', 'sonnet', 'opus'] as DigestModel[]).map(m => (
              <option key={m} value={m}>{DIGEST_MODEL_LABELS[m]}</option>
            ))}
          </select>
          <button onClick={regen} disabled={busy || !!digest?.is_generating}
            className={`flex items-center gap-1 md:gap-2 px-3 md:px-4 py-1.5 md:py-2 rounded-full font-mono text-[9px] md:text-[10px] uppercase tracking-[0.18em] transition-all ${
              busy || digest?.is_generating ? 'opacity-50 cursor-wait bg-brand-surface text-brand-ink/60'
                   : 'bg-brand-accent text-brand-cream hover:opacity-90'
            }`}>
            {busy || digest?.is_generating ? <Loader2 size={12} className="animate-spin md:w-3.5 md:h-3.5" /> : <RefreshCw size={12} className="md:w-3.5 md:h-3.5" />}
            {digest?.markdown ? 'Ververs' : 'Genereer'}
          </button>
        </div>
      </div>
      {err && <div className="mt-4 text-red-600 text-sm">{err}</div>}
      {!digest?.markdown && !digest?.is_generating && digest && digest.generated_at && (
        <div className="mt-3 font-mono text-[9px] md:text-[10px] uppercase tracking-[0.15em] text-brand-ink/45">
          {digest.error
            ? (digest.error.length > 120 ? digest.error.slice(0, 120) + '…' : digest.error)
            : 'Generatie liep, maar geen output. Probeer opnieuw.'}
        </div>
      )}
      {open && digest?.markdown && (
        <div
          className="mt-6 pt-6 border-t border-brand-ink/10 prose-stroom font-serif text-[16px] leading-[1.65] text-brand-ink/85 max-w-none"
          dangerouslySetInnerHTML={{ __html: sanitizeMarkdown(digest.markdown) }}
        />
      )}
    </section>
  );
}

// --- Inbox Modal ---

function InboxModal({ onClose }: { onClose: () => void }) {
  const [url, setUrl] = useState('');
  const [title, setTitle] = useState('');
  const [format, setFormat] = useState<'article' | 'podcast' | 'video'>('article');
  const [topicSlug, setTopicSlug] = useState('vandaag');
  const [description, setDescription] = useState('');
  const [author, setAuthor] = useState('');
  const [topics, setTopics] = useState<{ slug: string; name: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [fetchedThumb, setFetchedThumb] = useState<string | null>(null);

  useEffect(() => {
    fetchInboxTopics().then(setTopics).catch(() => setTopics([]));
  }, []);

  // Debounced URL fetch
  useEffect(() => {
    const trimmed = url.trim();
    if (!trimmed || !trimmed.startsWith('http')) return;

    const timer = setTimeout(async () => {
      setFetching(true);
      setError(null);
      try {
        const meta = await fetchInboxMetadata({ url: trimmed });
        if (meta.title) setTitle(meta.title);
        if (meta.description) setDescription(meta.description);
        if (meta.author) setAuthor(meta.author);
        if (meta.thumbnail_url) setFetchedThumb(meta.thumbnail_url);
        // Auto-detected format from backend
        if (meta.format) setFormat(meta.format);
      } catch (e) {
        // Silent fail - user can fill manually
        console.log('Failed to fetch metadata:', e);
      } finally {
        setFetching(false);
      }
    }, 800); // Wait 800ms after typing stops

    return () => clearTimeout(timer);
  }, [url]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await submitToInbox({ url, title, format, topic_slug: topicSlug, description: description || null, author: author || null });
      setSuccess(`${res.title} is toegevoegd aan de inbox.`);
      setUrl('');
      setTitle('');
      setDescription('');
      setAuthor('');
      setFetchedThumb(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const formatLabel: Record<string, string> = {
    article: '📄 Artikel',
    podcast: '🎙️ Podcast',
    video: '📹 Video',
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg bg-brand-cream rounded-lg shadow-xl p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <InboxIcon size={20} />
            Inbox — Content insturen
          </h2>
          <button onClick={onClose} className="p-1 hover:bg-brand-surface rounded"><X size={20} /></button>
        </div>

        {success && (
          <div className="mb-4 p-3 bg-green-100 text-green-800 rounded text-sm">{success}</div>
        )}
        {error && (
          <div className="mb-4 p-3 bg-red-100 text-red-800 rounded text-sm">{error}</div>
        )}

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">URL</label>
            <div className="relative">
              <input type="url" required value={url} onChange={e => setUrl(e.target.value)}
                placeholder="Plak een URL..." className="w-full px-3 py-2 border rounded bg-white pr-10" />
              {fetching && <Loader2 size={16} className="animate-spin absolute right-3 top-2.5 text-brand-ink/40" />}
            </div>
            <p className="text-xs text-brand-ink/50 mt-1">De titel en beschrijving worden automatisch ingevuld</p>
          </div>

          {fetchedThumb && (
            <div className="flex items-center gap-3 p-2 bg-white rounded border">
              <img src={fetchedThumb} alt="" className="w-16 h-12 object-cover rounded" />
              <div className="text-xs text-brand-ink/60">Thumbnail gevonden</div>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium mb-1">Titel</label>
            <input type="text" required value={title} onChange={e => setTitle(e.target.value)}
              placeholder="Titel van het item" className="w-full px-3 py-2 border rounded bg-white" />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">Type <span className="text-xs text-brand-ink/50">(auto)</span></label>
              <select value={format} onChange={e => setFormat(e.target.value as any)} className="w-full px-3 py-2 border rounded bg-white">
                <option value="article">{formatLabel.article}</option>
                <option value="podcast">{formatLabel.podcast}</option>
                <option value="video">{formatLabel.video}</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Topic</label>
              <select value={topicSlug} onChange={e => setTopicSlug(e.target.value)} className="w-full px-3 py-2 border rounded bg-white">
                {topics.map(t => <option key={t.slug} value={t.slug}>{t.name}</option>)}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Auteur (optioneel)</label>
            <input type="text" value={author} onChange={e => setAuthor(e.target.value)}
              placeholder="Naam van de auteur" className="w-full px-3 py-2 border rounded bg-white" />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Beschrijving (optioneel)</label>
            <textarea value={description} onChange={e => setDescription(e.target.value)}
              placeholder="Korte beschrijving..." rows={3} className="w-full px-3 py-2 border rounded bg-white text-sm" />
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm hover:bg-brand-surface rounded">Annuleren</button>
            <button type="submit" disabled={busy} className="px-4 py-2 text-sm bg-brand-accent text-white rounded hover:bg-brand-accent/90 disabled:opacity-50 flex items-center gap-2">
              {busy && <Loader2 size={14} className="animate-spin" />}
              Toevoegen aan inbox
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function LessonsPage({ onBack, onOpenItem }: { onBack: () => void; onOpenItem: (id: string) => void }) {
  const [lessons, setLessons] = useState<Lesson[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<LessonFilter>('useful');

  useEffect(() => {
    setLessons(null); setError(null);
    const r = filter === 'useful' ? 1 : filter === 'not-useful' ? -1 : null;
    fetchAllLessons(r).then(setLessons).catch(e => setError(String(e)));
  }, [filter]);

  return (
    <div className="max-w-4xl mx-auto pt-2">
      <button onClick={onBack}
        className="mb-8 font-mono text-[11px] uppercase tracking-[0.18em] text-brand-ink/50 hover:text-brand-accent flex items-center gap-2">
        <ArrowLeft size={14} /> Terug
      </button>

      <h1 className="font-display text-5xl md:text-6xl text-brand-ink font-medium tracking-[-0.04em] mb-4">Lessen</h1>
      <p className="font-serif text-[15px] text-brand-ink/60 mb-8">
        Alle kernlessen die je hebt aangemerkt — gegroepeerd per bron.
      </p>

      <div className="flex gap-2 mb-10">
        {(['useful', 'not-useful', 'all'] as LessonFilter[]).map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`px-4 py-1.5 rounded-full text-[12px] font-medium transition-all ${
              filter === f ? 'bg-brand-accent text-brand-cream shadow-sm'
              : 'bg-brand-surface hover:bg-brand-surface-low text-brand-ink/70'
            }`}>{LESSON_FILTER_LABELS[f]}</button>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-10">
        <LessonsDigestPanel window="daily" filter={filter as LessonsDigestFilter} />
        <LessonsDigestPanel window="weekly" filter={filter as LessonsDigestFilter} />
      </div>

      {error && <div className="text-red-600 text-sm mb-6">Fout: {error}</div>}
      {lessons === null ? (
        <div className="text-brand-ink/40 italic">Laden…</div>
      ) : lessons.length === 0 ? (
        <div className="text-brand-ink/40 italic">Geen lessen in deze categorie.</div>
      ) : (
        <ul className="space-y-6">
          {lessons.map(l => (
            <li key={l.id} className="border-t border-brand-ink/10 pt-5">
              <div className="flex items-start gap-3 mb-2">
                <span className={`mt-1 w-6 h-6 flex items-center justify-center rounded-full shrink-0 ${
                  l.rating === 1 ? 'bg-emerald-500 text-white' :
                  l.rating === -1 ? 'bg-rose-500 text-white' :
                  'bg-brand-surface text-brand-ink/40'
                }`}>
                  {l.rating === 1 ? <Check size={12} /> : l.rating === -1 ? <X size={12} /> : null}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="font-serif font-semibold text-[18px] text-brand-ink mb-1">{renderInline(l.title)}</div>
                  <div className="font-serif text-[16px] leading-[1.55] text-brand-ink/80 mb-2">{renderInline(l.body)}</div>
                  <LessonExpansion lesson={l} onUpdate={(u) => setLessons(prev => prev?.map(x => x.id === u.id ? u : x) ?? prev)} />
                  <div className="mt-2 font-mono text-[10px] uppercase tracking-[0.15em] text-brand-ink/50 flex items-center gap-3 flex-wrap">
                    <button onClick={() => onOpenItem(l.item_id)}
                      className="hover:text-brand-accent transition-colors text-left">
                      {l.source_name} · {l.item_title}
                    </button>
                    {l.media_url && (
                      <a href={l.media_url} target="_blank" rel="noreferrer"
                        className="text-brand-accent hover:underline inline-flex items-center gap-1">
                        <ExternalLink size={10} /> bron
                      </a>
                    )}
                    {l.rated_at && (
                      <span className="text-brand-ink/30">
                        {new Date(l.rated_at).toLocaleDateString('nl-NL', { day: '2-digit', month: 'short' })}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
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
  const [lessonsView, setLessonsView] = useState<boolean>(() => readUrl().lessons);
  const [inboxOpen, setInboxOpen] = useState<boolean>(false);

  useEffect(() => {
    const onPop = () => {
      const { itemId, topic, admin, lessons } = readUrl();
      setItemId(itemId);
      setAdminMode(admin);
      setLessonsView(lessons);
      if (topic) setActiveSlug(topic);
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const goHome = () => {
    const url = new URL(window.location.href);
    url.searchParams.delete('item');
    url.searchParams.delete('admin');
    url.searchParams.delete('lessons');
    window.history.pushState({}, '', url.toString());
    setItemId(null);
    setAdminMode(false);
    setLessonsView(false);
    setActiveFilter('all');
    setActiveWindow('all');
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
  };

  const openLessons = () => {
    const url = new URL(window.location.href);
    url.searchParams.set('lessons', '1');
    url.searchParams.delete('item');
    url.searchParams.delete('admin');
    window.history.pushState({}, '', url.toString());
    setLessonsView(true);
    setItemId(null);
    setAdminMode(false);
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
  };

  const closeLessons = () => {
    const url = new URL(window.location.href);
    url.searchParams.delete('lessons');
    window.history.pushState({}, '', url.toString());
    setLessonsView(false);
  };

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
        <div className="flex justify-between items-center px-4 md:px-12 py-3 md:py-6 w-full max-w-screen-2xl mx-auto">
          <button onClick={goHome} title="Naar home"
            className="text-2xl md:text-3xl text-brand-ink flex items-center gap-2 md:gap-3 hover:opacity-80 transition-opacity">
            <img src="/logo.png" alt="Stroom" className="w-8 h-8 md:w-10 md:h-10 rounded-lg object-cover" />
            <span className="pt-1 font-display italic font-light text-brand-ink tracking-[-0.02em]">Stroom</span>
          </button>
          <div className="flex gap-3 md:gap-6 items-center text-brand-ink/40">
            <button className="hover:text-brand-accent transition-colors p-1 md:p-0"><Search size={18} strokeWidth={2.5} className="md:w-5 md:h-5" /></button>
            <button onClick={openLessons} title="Alle lessen"
                    className="hover:text-brand-accent transition-colors p-1 md:p-0">
              <BookOpen size={18} strokeWidth={2.5} className="md:w-5 md:h-5" />
            </button>
            <button onClick={() => setInboxOpen(true)} title="Inbox — Content insturen"
                    className="hover:text-brand-accent transition-colors p-1 md:p-0">
              <InboxIcon size={18} strokeWidth={2.5} className="md:w-5 md:h-5" />
            </button>
            <button onClick={toggleDark} title={dark ? 'Lichtmodus' : 'Donkermodus'}
                    className="hover:text-brand-accent transition-colors p-1 md:p-0">
              {dark ? <Sun size={18} strokeWidth={2.5} className="md:w-5 md:h-5" /> : <Moon size={18} strokeWidth={2.5} className="md:w-5 md:h-5" />}
            </button>
            <button onClick={openAdmin} title="Sources beheren"
                    className="hover:text-brand-accent transition-colors p-1 md:p-0">
              <Settings size={18} strokeWidth={2.5} className="md:w-5 md:h-5" />
            </button>
            <button onClick={onLogout} title={`Uitloggen (${user.email})`}
                    className="hover:text-brand-accent transition-colors flex items-center gap-2 text-[12px] font-mono uppercase tracking-[0.15em] p-1 md:p-0">
              <UserIcon size={18} strokeWidth={2.5} className="md:w-5 md:h-5" />
              <span className="hidden md:inline">Uitloggen</span>
            </button>
          </div>
        </div>
      </nav>

      <main className="relative z-10 w-full max-w-screen-2xl mx-auto px-6 md:px-12 pb-32 pt-10">
        {adminMode ? (
          <AdminPage onBack={closeAdmin} />
        ) : lessonsView ? (
          <LessonsPage onBack={closeLessons} onOpenItem={openItem} />
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
                {(['all', 'saved', 'summarized', 'scheduled', 'archived', 'inbox'] as ItemFilter[]).map(f => (
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
                <div className="grid md:grid-cols-2 gap-4 mb-12">
                  <DigestPanel slug={data.slug} topicName={data.name} window="daily" />
                  <DigestPanel slug={data.slug} topicName={data.name} window="weekly" />
                </div>
                {data.rails.map(rail => <Rail key={rail.format} format={rail.format} items={rail.items} onOpen={openItem}
                  onUpdate={(id, u) => setData(d => d ? {
                    ...d,
                    rails: d.rails.map(r => ({ ...r, items: r.items.map(it => it.id === id ? { ...it, ...u } : it) })),
                  } : d)}
                  onArchiveItem={(id) => setData(d => d ? {
                    ...d,
                    rails: d.rails.map(r => ({ ...r, items: r.items.filter(it => it.id !== id) })),
                  } : d)}
                  onArchiveAll={async (format) => {
                    const targetRail = data.rails.find(r => r.format === format);
                    if (!targetRail) return;
                    await Promise.all(targetRail.items.map(it => setItemStatus(it.id, 'archived').catch(() => null)));
                    if (activeSlug) {
                      const fresh = await fetchHuygens(activeSlug);
                      setData(fresh);
                    }
                  }} />)}
              </>
            ) : (
              !error && <div className="text-brand-ink/40 italic">Loading…</div>
            )}
          </>
        )}
      </main>

      {inboxOpen && <InboxModal onClose={() => setInboxOpen(false)} />}
    </div>
  );
}
