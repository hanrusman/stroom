import React from 'react';
import { PlayCircle, Headphones } from 'lucide-react';
import { Badge } from './Badge';
import { cn } from './cn';

export type ContentFormat = 'article' | 'podcast' | 'video';

export interface ContentCardProps {
  title: string;
  /** Short plain-text summary/excerpt. Clamped to a few lines. */
  summary?: string;
  /** Cover/thumbnail image URL. */
  imageUrl?: string;
  /** Source or author name, shown in the meta row. */
  sourceName?: string;
  /** Optional secondary meta (e.g. "5 min" or a relative date). */
  meta?: string;
  /** Drives the layout and badge: a full article, a compact podcast row, or a video tile. */
  format?: ContentFormat;
  onOpen?: () => void;
  /** Optional action row rendered at the bottom (e.g. bookmark/archive buttons). */
  actions?: React.ReactNode;
  className?: string;
}

function MetaRow({ sourceName, meta }: { sourceName?: string; meta?: string }) {
  if (!sourceName && !meta) return null;
  return (
    <div className="mt-3 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.16em] text-brand-ink/45">
      {sourceName && <span className="truncate">{sourceName}</span>}
      {sourceName && meta && <span>•</span>}
      {meta && <span className="shrink-0">{meta}</span>}
    </div>
  );
}

/**
 * The core Stroom feed item. `article` is the tall image-topped card, `podcast` is a
 * compact horizontal row with square art, and `video` is a 16:9 tile with a play badge.
 * Presentational — pass `onOpen` and an `actions` slot for interactivity.
 * @category Composites
 */
export function ContentCard({
  title,
  summary,
  imageUrl,
  sourceName,
  meta,
  format = 'article',
  onOpen,
  actions,
  className,
}: ContentCardProps) {
  if (format === 'podcast') {
    return (
      <article
        onClick={onOpen}
        className={cn(
          'w-full md:w-[360px] rounded-2xl overflow-hidden p-3 bg-brand-surface border border-brand-ink/5 hover:shadow-sm transition-all cursor-pointer group',
          className,
        )}
      >
        <div className="flex gap-3">
          <div className="w-24 h-24 shrink-0 rounded-xl overflow-hidden bg-brand-surface-low flex items-center justify-center">
            {imageUrl ? (
              <img src={imageUrl} alt={title} className="w-full h-full object-cover" />
            ) : (
              <Headphones size={24} className="text-brand-ink/30" />
            )}
          </div>
          <div className="flex flex-col flex-1 min-w-0">
            <h3 className="font-serif font-semibold text-[15px] text-brand-ink group-hover:text-brand-accent transition-colors line-clamp-3 leading-[1.25] mb-1">
              {title}
            </h3>
            <MetaRow sourceName={sourceName} meta={meta} />
          </div>
        </div>
        {actions && <div className="mt-2">{actions}</div>}
      </article>
    );
  }

  if (format === 'video') {
    return (
      <article
        onClick={onOpen}
        className={cn('w-full md:w-[360px] flex flex-col gap-3 group cursor-pointer', className)}
      >
        <div className="w-full aspect-video rounded-2xl overflow-hidden relative bg-brand-surface">
          {imageUrl ? (
            <img
              src={imageUrl}
              alt={title}
              className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-700 ease-out"
            />
          ) : (
            <div className="w-full h-full bg-gradient-to-br from-brand-surface to-brand-surface-low" />
          )}
          <div className="absolute top-3 left-3">
            <Badge tone="accent">
              <PlayCircle size={10} /> video
            </Badge>
          </div>
        </div>
        <div className="flex flex-col gap-1 px-1">
          <h3 className="font-serif font-semibold text-[18px] text-brand-ink group-hover:text-brand-accent transition-colors line-clamp-2 leading-[1.25]">
            {title}
          </h3>
          {summary && <p className="text-brand-ink/65 line-clamp-2 text-[13px] leading-[1.45]">{summary}</p>}
          <MetaRow sourceName={sourceName} meta={meta} />
          {actions && <div className="mt-2">{actions}</div>}
        </div>
      </article>
    );
  }

  // article
  return (
    <article
      onClick={onOpen}
      className={cn(
        'w-full md:w-[340px] rounded-3xl overflow-hidden flex flex-col bg-brand-surface border border-brand-ink/5 hover:shadow-md transition-all cursor-pointer group',
        className,
      )}
    >
      {imageUrl ? (
        <div className="w-full aspect-[16/9] overflow-hidden bg-brand-surface-low shrink-0">
          <img
            src={imageUrl}
            alt={title}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-700 ease-out"
          />
        </div>
      ) : (
        <div className="w-full h-2 bg-brand-accent/30 shrink-0" />
      )}
      <div className="p-6 flex flex-col flex-1 min-h-0">
        <h3 className="font-serif font-semibold text-[22px] text-brand-ink group-hover:text-brand-accent transition-colors line-clamp-3 leading-[1.2] tracking-[-0.01em] mb-3">
          {title}
        </h3>
        {summary && <p className="text-brand-ink/70 line-clamp-5 text-[13px] leading-[1.55] flex-1">{summary}</p>}
        <MetaRow sourceName={sourceName} meta={meta} />
        {actions && <div className="mt-4">{actions}</div>}
      </div>
    </article>
  );
}
